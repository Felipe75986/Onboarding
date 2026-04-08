from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd

from file_logger import FileLogger
from .client import NetboxClient, SpreadsheetError
from .config import OnboardingConfig
from .manifest import OnboardingManifest


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class SwitchMapping:
    cable_color: str       # "blue", "black", "white"
    switch_name: str       # e.g. "SWACC26-LAX5"
    device_interface: str  # "ETH0", "PXE", "IPMI"


@dataclass
class CableInfo:
    device_name: str
    device_interface: str  # "ETH0", "PXE", "IPMI"
    switch_name: str
    switch_port: str       # e.g. "Ethernet1/1"
    cable_color: str       # "blue", "black", "white"


@dataclass
class DeliveryData:
    rack: str
    switch_mappings: list[SwitchMapping]
    cables: list[CableInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV Parser
# ---------------------------------------------------------------------------

# Color → device interface mapping
COLOR_INTERFACE_MAP = {
    "blue": "ETH0",
    "black": "PXE",
    "white": "IPMI",
}


def parse_delivery_csv(file_path: str, logger: FileLogger) -> DeliveryData:
    """Parse a Delivery CSV and return structured cable data."""
    logger.info("Parsing delivery spreadsheet", file=file_path)

    try:
        df = pd.read_csv(
            file_path,
            header=None,
            dtype=str,
            keep_default_na=False,
        )
    except Exception as exc:
        logger.error("Failed to read delivery CSV", file=file_path, error=str(exc))
        raise SpreadsheetError(f"Cannot read delivery CSV: {exc}") from exc

    # -- Rack name (row 0, col 2) ------------------------------------------
    rack = str(df.iloc[0, 2]).strip()
    logger.info("Rack identified", rack=rack)

    # -- Switch mappings (rows 2-4) ----------------------------------------
    # Row 2: Port 1 Blue  → col 3 = switch name
    # Row 3: Port 2 Black → col 3 = switch name
    # Row 4: White Cable   → col 3 = switch name
    switch_mappings: list[SwitchMapping] = []
    color_switch_map: dict[str, str] = {}

    mapping_rows = [
        (2, "blue", "ETH0"),
        (3, "black", "PXE"),
        (4, "white", "IPMI"),
    ]

    for row_idx, color, interface in mapping_rows:
        switch_name = str(df.iloc[row_idx, 3]).strip()
        if switch_name:
            mapping = SwitchMapping(
                cable_color=color,
                switch_name=switch_name,
                device_interface=interface,
            )
            switch_mappings.append(mapping)
            color_switch_map[color] = switch_name
            logger.info(
                "Switch mapping found",
                color=color,
                switch=switch_name,
                interface=interface,
            )

    # -- Device cables (row 8+) --------------------------------------------
    # Col 0: server name
    # Col 4: port number for Blue (ETH0)
    # Col 6: port number for Black (PXE)
    # Col 8: port number for White (IPMI)
    df_devices = df.iloc[8:].reset_index(drop=True)
    df_devices = df_devices.apply(lambda col: col.str.strip())
    df_devices = df_devices[df_devices.iloc[:, 0] != ""]

    cables: list[CableInfo] = []

    cable_columns = [
        (4, "blue", "ETH0"),   # col 4 → port for Blue → ETH0
        (6, "black", "PXE"),   # col 6 → port for Black → PXE
        (8, "white", "IPMI"),  # col 8 → port for White → IPMI
    ]

    for _, row in df_devices.iterrows():
        device_name = row.iloc[0]

        for col_idx, color, interface in cable_columns:
            port_number = row.iloc[col_idx]
            if not port_number:
                continue

            switch_name = color_switch_map.get(color)
            if not switch_name:
                logger.warn(
                    "No switch mapping for color",
                    device=device_name,
                    color=color,
                )
                continue

            cable = CableInfo(
                device_name=device_name,
                device_interface=interface,
                switch_name=switch_name,
                switch_port=f"Ethernet1/{port_number}",
                cable_color=color,
            )
            cables.append(cable)

    logger.info(
        "Delivery parsing complete",
        rack=rack,
        devices=len(df_devices),
        cables=len(cables),
    )

    return DeliveryData(rack=rack, switch_mappings=switch_mappings, cables=cables)


# ---------------------------------------------------------------------------
# Cable creation
# ---------------------------------------------------------------------------
def create_cables(
    client: NetboxClient,
    delivery: DeliveryData,
    logger: FileLogger,
    manifest: OnboardingManifest | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Create cable connections in NetBox.

    Returns (succeeded descriptions, failed {description: error}).
    """
    start = time.time()
    succeeded: list[str] = []
    failed: dict[str, str] = {}

    # -- Cache: switch name -> {device dict, interfaces dict} --------------
    switch_cache: dict[str, dict] = {}        # name -> device dict
    switch_ifaces: dict[int, dict[str, int]] = {}  # switch_id -> {iface_name: iface_id}

    def get_switch(name: str) -> dict | None:
        if name not in switch_cache:
            result = client.get_single(f"dcim/devices/?name={name}")
            switch_cache[name] = result
            if result:
                logger.info("Switch found", switch=name, id=result["id"])
            else:
                logger.error("Switch not found in NetBox", switch=name)
        return switch_cache[name]

    def get_switch_interface(switch_id: int, iface_name: str) -> int | None:
        if switch_id not in switch_ifaces:
            # Fetch all interfaces for this switch at once
            interfaces = client.get(f"dcim/interfaces/?device_id={switch_id}&limit=500")
            switch_ifaces[switch_id] = {i["name"]: i["id"] for i in interfaces}
            logger.info(
                "Switch interfaces cached",
                switch_id=switch_id,
                count=len(switch_ifaces[switch_id]),
            )
        return switch_ifaces[switch_id].get(iface_name)

    # -- Create each cable -------------------------------------------------
    for cable in delivery.cables:
        desc = f"{cable.device_name}:{cable.device_interface} -> {cable.switch_name}:{cable.switch_port}"
        logger.info("Creating cable", cable=desc)

        try:
            # 1. Find device
            device = client.get_single(f"dcim/devices/?name={cable.device_name}")
            if not device:
                raise ValueError(f"Device '{cable.device_name}' not found in NetBox")

            # 2. Find device interface
            device_iface = client.get_single(
                f"dcim/interfaces/?device_id={device['id']}&name={cable.device_interface}"
            )
            if not device_iface:
                raise ValueError(
                    f"Interface '{cable.device_interface}' not found on device '{cable.device_name}'"
                )

            # 3. Find switch
            switch = get_switch(cable.switch_name)
            if not switch:
                raise ValueError(f"Switch '{cable.switch_name}' not found in NetBox")

            # 4. Find switch port
            switch_port_id = get_switch_interface(switch["id"], cable.switch_port)
            if not switch_port_id:
                raise ValueError(
                    f"Port '{cable.switch_port}' not found on switch '{cable.switch_name}'"
                )

            # 5. Create cable
            cable_payload = {
                "a_terminations": [
                    {"object_type": "dcim.interface", "object_id": device_iface["id"]}
                ],
                "b_terminations": [
                    {"object_type": "dcim.interface", "object_id": switch_port_id}
                ],
                "status": "connected",
            }

            result = client.create("dcim/cables/", cable_payload)
            if result:
                cable_id = result.get("id")
                logger.info("Cable created", cable=desc, id=cable_id)
                succeeded.append(desc)
                if manifest and cable_id:
                    manifest.add_cable(cable_id, desc)
            else:
                raise ValueError("Cable creation returned empty response")

        except Exception as exc:
            logger.error("Cable creation failed", cable=desc, error=str(exc))
            failed[desc] = str(exc)

    elapsed = round(time.time() - start, 2)
    logger.info(
        "Cable creation complete",
        total=len(delivery.cables),
        succeeded=len(succeeded),
        failed=len(failed),
        duration_seconds=elapsed,
    )

    return succeeded, failed
