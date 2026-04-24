from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from file_logger import FileLogger
from .client import SpreadsheetError


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ChassisInfo:
    name: str
    device_type: str
    role_name: str
    site: str
    rack: str
    position: str
    procurement_ticket: str
    face: str = "front"


@dataclass
class DeviceInfo:
    name: str
    device_type: str
    platform_name: str
    rack: str
    position: str
    automation_instance: str
    procurement_ticket: str
    role_name: str
    site: str
    serial: str
    ip_ipmi: str
    ip_eth0: str
    ipv6_eth0: str
    vlan: str
    vlan_group: str
    slot: int
    status: str


@dataclass
class SpreadsheetData:
    site: str
    rack: str
    ticket: str
    platform: str
    procurement_ticket: str
    chassis: ChassisInfo | None
    devices: list[DeviceInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV Parser
# ---------------------------------------------------------------------------
def parse_onboarding_csv(
    file_path: str,
    status: str,
    logger: FileLogger,
) -> SpreadsheetData:
    """Parse the onboarding CSV using pandas and return structured data."""
    logger.info("Parsing spreadsheet", file=file_path)

    try:
        df = pd.read_csv(
            file_path,
            header=None,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Failed to read CSV file", file=file_path, error=str(exc))
        raise SpreadsheetError(f"Cannot read CSV: {exc}") from exc

    # -- Metadata (rows 0-7) -----------------------------------------------
    try:
        site = str(df.iloc[0, 1]).strip()
        rack = str(df.iloc[2, 1]).strip()
        ticket = str(df.iloc[3, 4]).strip()
        platform = str(df.iloc[3, 1]).strip()
        chassis_name = str(df.iloc[4, 1]).strip()
        chassis_type = str(df.iloc[4, 4]).strip()
        chassis_ru = str(df.iloc[4, 7]).strip()
        procurement_ticket = str(df.iloc[5, 1]).strip()
    except (IndexError, KeyError) as exc:
        logger.error("Spreadsheet metadata extraction failed", error=str(exc))
        raise SpreadsheetError(f"Invalid spreadsheet format: {exc}") from exc

    logger.info(
        "Metadata extracted",
        site=site,
        rack=rack,
        ticket=ticket,
        platform=platform,
    )

    # -- Chassis -----------------------------------------------------------
    chassis: ChassisInfo | None = None
    if chassis_name:
        chassis = ChassisInfo(
            name=chassis_name,
            device_type=chassis_type,
            role_name="Enclosure",
            site=site,
            rack=rack,
            position=chassis_ru,
            procurement_ticket=procurement_ticket,
        )
        logger.info("Chassis found", chassis=chassis_name, type=chassis_type)

    # -- Devices (row 8+) --------------------------------------------------
    df_devices = df.iloc[8:].reset_index(drop=True)
    # Strip all string cells in bulk
    df_devices = df_devices.apply(lambda col: col.str.strip())
    # Filter out empty rows (column 0 = device name)
    df_devices = df_devices[df_devices.iloc[:, 0] != ""]

    devices: list[DeviceInfo] = []
    for idx, row in df_devices.iterrows():
        try:
            device = DeviceInfo(
                name=row.iloc[0],
                device_type=row.iloc[3],
                platform_name=platform,
                rack=rack,
                position=row.iloc[4],
                automation_instance=row.iloc[2],
                procurement_ticket=procurement_ticket,
                role_name="Bare Metal",
                site=site,
                serial=row.iloc[5],
                ip_ipmi=row.iloc[10],
                ip_eth0=row.iloc[11],
                ipv6_eth0=row.iloc[13],
                vlan=row.iloc[15],
                vlan_group=row.iloc[16],
                slot=len(devices) + 1,
                status=status,
            )
            devices.append(device)
        except (IndexError, KeyError) as exc:
            logger.warn(
                "Skipping malformed device row",
                row_index=int(idx) + 8,
                error=str(exc),
            )

    logger.info("Spreadsheet parsing complete", device_count=len(devices))

    return SpreadsheetData(
        site=site,
        rack=rack,
        ticket=ticket,
        platform=platform,
        procurement_ticket=procurement_ticket,
        chassis=chassis,
        devices=devices,
    )
