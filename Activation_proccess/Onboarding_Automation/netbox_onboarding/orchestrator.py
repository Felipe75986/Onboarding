from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from file_logger import FileLogger
from .config import load_config, create_session, OnboardingConfig, IP_TAG_IDS
from .client import NetboxClient
from .cache import NetboxCache
from .manifest import OnboardingManifest
from .spreadsheet import parse_onboarding_csv, SpreadsheetData, DeviceInfo
from .validators import validate_and_resolve, resolve_status_from_switches
from .devices import (
    create_chassis,
    create_devices,
    create_interfaces_bulk,
    create_ip_address,
    update_device_primary_ip,
)
from .networking import create_network_infrastructure, create_prefix


# ---------------------------------------------------------------------------
# Results tracker
# ---------------------------------------------------------------------------
@dataclass
class OnboardingResults:
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # device_name -> error
    manifest_path: str | None = None

    def log_summary(self, logger: FileLogger, elapsed: float) -> None:
        logger.info(
            "Onboarding complete",
            created=len(self.succeeded),
            failed=len(self.failed),
            duration_seconds=round(elapsed, 2),
            succeeded_devices=self.succeeded,
            failed_devices=list(self.failed.keys()),
            manifest=self.manifest_path,
        )
        for name, err in self.failed.items():
            logger.error("Device failed", device=name, reason=err)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def run(
    logger: FileLogger | None = None,
    switch_names: list[str] | None = None,
) -> OnboardingResults:
    """Execute the full NetBox onboarding workflow.

    Args:
        logger: Optional FileLogger instance.
        switch_names: Optional list of switch names to check status in NetBox.
            If provided, the resolved status overrides the env var.
    """
    start = time.time()

    # -- Config & session --------------------------------------------------
    config = load_config()
    session = create_session()

    if logger is None:
        logger = FileLogger(
            logs_dir=Path("logs"),
            process_name="netbox_onboarding",
            username="system",
        )

    logger.info("Starting onboarding", file=config.file_name, status=config.status)

    # -- Client & cache ----------------------------------------------------
    client = NetboxClient(config, session, logger)
    cache = NetboxCache(client, logger)

    # -- Resolve status from switches (if provided) ------------------------
    if switch_names:
        resolved_status = resolve_status_from_switches(
            client, switch_names, config.status, logger,
        )
        if resolved_status != config.status:
            logger.info(
                "Status overridden by switch check",
                old=config.status,
                new=resolved_status,
            )
            config = replace(config, status=resolved_status, reserva=resolved_status)

    # -- Parse spreadsheet -------------------------------------------------
    data = parse_onboarding_csv(config.file_name, config.status, logger)

    # -- Warm up cache (parallel) ------------------------------------------
    cache.warm_up()

    # -- Validate ----------------------------------------------------------
    validation = validate_and_resolve(data, cache, config, logger)

    if validation.errors:
        logger.warn(
            "Validation produced errors",
            error_count=len(validation.errors),
            errors=validation.errors,
        )

    if not validation.valid_devices:
        logger.error("No valid devices after validation, aborting")
        results = OnboardingResults()
        results.log_summary(logger, time.time() - start)
        return results

    # -- Initialize manifest -----------------------------------------------
    manifest = OnboardingManifest(
        site=data.site,
        rack=data.rack,
        ticket=data.ticket,
        status=config.status,
        logger=logger,
    )

    # -- Create chassis (if present) ---------------------------------------
    chassis_id: int | None = None
    if validation.chassis_payload:
        chassis_id = create_chassis(client, validation.chassis_payload, logger)
        if chassis_id:
            manifest.set_chassis(chassis_id, validation.chassis_payload["name"])

    # -- Pre-warm VLAN cache -----------------------------------------------
    cache.get_vlan_groups(force_refresh=True)

    # -- Pre-create VLANs (deduplicated) -----------------------------------
    vlan_lookup: dict[tuple[str, int], tuple[int | None, int | None]] = {}
    unique_vlans: set[tuple[str, int]] = set()
    for dev in data.devices:
        if dev.vlan_group and dev.vlan:
            unique_vlans.add((dev.vlan_group, int(dev.vlan)))

    for vlan_group, vlan_id in unique_vlans:
        try:
            vlan_nb_id, switch_iface_id = create_network_infrastructure(
                client, cache, vlan_group, vlan_id, config, logger,
            )
            vlan_lookup[(vlan_group, vlan_id)] = (vlan_nb_id, switch_iface_id)
            if vlan_nb_id:
                manifest.add_vlan(vlan_nb_id, vlan_id, vlan_group)
        except Exception as exc:
            logger.error(
                "Failed to create network infrastructure",
                vlan_group=vlan_group,
                vlan_id=vlan_id,
                error=str(exc),
            )
            vlan_lookup[(vlan_group, vlan_id)] = (None, None)

    # -- Create devices ----------------------------------------------------
    created_devices = create_devices(client, validation.valid_devices, chassis_id, logger)

    if not created_devices:
        logger.error("No devices were created")
        results = OnboardingResults()
        manifest.save()
        results.manifest_path = str(manifest.file_path)
        results.log_summary(logger, time.time() - start)
        return results

    for device in created_devices:
        manifest.add_device(device["id"], device["name"])

    logger.info("Devices created", count=len(created_devices))

    # -- Post-creation: interfaces, IPs, prefixes -------------------------
    results = OnboardingResults()

    for device in created_devices:
        device_id = device["id"]
        device_name = device["name"]

        # Find the matching raw device data
        device_data = next((d for d in data.devices if d.name == device_name), None)
        if not device_data:
            logger.warn("No spreadsheet data found for created device", device=device_name)
            continue

        try:
            _process_device(
                client, cache, config, device_id, device_name,
                device_data, data, validation.site_id, vlan_lookup,
                manifest, logger,
            )
            results.succeeded.append(device_name)
        except Exception as exc:
            logger.error(
                "Failed to process device",
                device=device_name,
                error=str(exc),
            )
            results.failed[device_name] = str(exc)

    # -- Save manifest -----------------------------------------------------
    manifest.save()
    results.manifest_path = str(manifest.file_path)

    results.log_summary(logger, time.time() - start)
    return results


# ---------------------------------------------------------------------------
# Per-device processing
# ---------------------------------------------------------------------------
def _process_device(
    client: NetboxClient,
    cache: NetboxCache,
    config: OnboardingConfig,
    device_id: int,
    device_name: str,
    device_data: DeviceInfo,
    spreadsheet: SpreadsheetData,
    validation_site_id: int,
    vlan_lookup: dict[tuple[str, int], tuple[int | None, int | None]],
    manifest: OnboardingManifest,
    logger: FileLogger,
) -> None:
    """Create interfaces, IPs, and prefixes for a single device."""
    logger.info("Processing device", device=device_name, device_id=device_id)

    # -- Interfaces (bulk) -------------------------------------------------
    interface_ids = create_interfaces_bulk(client, device_id, logger)

    for iface_name, iface_id in interface_ids.items():
        manifest.add_interface(iface_id, iface_name, device_name)

    # -- Resolve VLAN from lookup ------------------------------------------
    vlan: int | None = None
    switch_interface_id: int | None = None
    if device_data.vlan_group and device_data.vlan:
        key = (device_data.vlan_group, int(device_data.vlan))
        vlan, switch_interface_id = vlan_lookup.get(key, (None, None))

    # -- IP addresses ------------------------------------------------------
    ip_mapping = [
        ("ip_eth0", "ETH0", IP_TAG_IDS["ip_eth0"]),
        ("ipv6_eth0", "ETH0", IP_TAG_IDS["ipv6_eth0"]),
        ("ip_ipmi", "IPMI", IP_TAG_IDS["ip_ipmi"]),
    ]

    for ip_attr, interface_name, tag_id in ip_mapping:
        ip_value = getattr(device_data, ip_attr, "")
        if not ip_value or interface_name not in interface_ids:
            continue

        ip_payload = {
            "address": ip_value,
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": interface_ids[interface_name],
            "status": config.reserva,
            "description": spreadsheet.ticket,
            "tags": [{"id": tag_id}],
        }
        response = create_ip_address(client, ip_payload, logger)

        if response:
            manifest.add_ip(response["id"], response.get("display", ip_value), device_name)

        if response and ip_attr == "ip_eth0":
            update_device_primary_ip(client, device_id, response["id"], "ipv4", logger)
            prefix_result = create_prefix(
                client, response["display"], ip_attr, vlan,
                validation_site_id, spreadsheet.ticket,
                switch_interface_id, config, logger,
            )
            if prefix_result:
                manifest.add_prefix(prefix_result["id"], prefix_result["prefix"])
        elif response and ip_attr == "ipv6_eth0":
            update_device_primary_ip(client, device_id, response["id"], "ipv6", logger)
            prefix_result = create_prefix(
                client, response["display"], ip_attr, vlan,
                validation_site_id, spreadsheet.ticket,
                switch_interface_id, config, logger,
            )
            if prefix_result:
                manifest.add_prefix(prefix_result["id"], prefix_result["prefix"])
