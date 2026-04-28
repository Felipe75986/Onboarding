from __future__ import annotations

from dataclasses import dataclass, field

from file_logger import FileLogger
from .client import NetboxClient
from .cache import NetboxCache
from .config import OnboardingConfig, ONBOARDING_TENANT_ID, SEGMENTATION_TAG_ID
from .spreadsheet import SpreadsheetData


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    valid_devices: list[dict] = field(default_factory=list)
    chassis_payload: dict | None = None
    site_id: int | None = None
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------
def validate_and_resolve(
    data: SpreadsheetData,
    cache: NetboxCache,
    config: OnboardingConfig,
    logger: FileLogger,
) -> ValidationResult:
    """Validate spreadsheet data against NetBox and build API-ready payloads.

    Collects ALL errors instead of failing on the first one.
    """
    logger.info("Validating device types, roles, platforms and sites")

    result = ValidationResult()

    types = cache.device_types
    roles = cache.device_roles
    platforms = cache.platforms
    sites = cache.sites

    # -- Resolve site ID (used by prefixes later) --------------------------
    if data.site in sites:
        result.site_id = sites[data.site]
    else:
        msg = f"Site '{data.site}' not found in NetBox"
        logger.error("Validation failed", reason=msg)
        result.errors.append(msg)
        return result  # cannot proceed without a valid site

    # -- Validate chassis --------------------------------------------------
    if data.chassis:
        ch = data.chassis
        errors_chassis: list[str] = []

        if ch.device_type not in types:
            errors_chassis.append(f"device_type '{ch.device_type}' not found")
        if ch.role_name not in roles:
            errors_chassis.append(f"role '{ch.role_name}' not found")
        if ch.site not in sites:
            errors_chassis.append(f"site '{ch.site}' not found")

        if errors_chassis:
            for err in errors_chassis:
                msg = f"Chassis '{ch.name}': {err}"
                logger.warn("Chassis validation failed", chassis=ch.name, reason=err)
                result.errors.append(msg)
        else:
            result.chassis_payload = {
                "name": ch.name,
                "device_type": types[ch.device_type],
                "role": roles[ch.role_name],
                "site": sites[ch.site],
                "status": config.status,
                "rack": ch.rack,
                "face": ch.face,
                "position": ch.position,
                "custom_fields": {"procurement_ticket_url": ch.procurement_ticket},
                "tenant": ONBOARDING_TENANT_ID,
            }
            logger.info("Chassis validated", chassis=ch.name)

    # -- Validate devices --------------------------------------------------
    for dev in data.devices:
        dev_errors: list[str] = []

        if dev.device_type not in types:
            dev_errors.append(f"device_type '{dev.device_type}' not found")
        if dev.platform_name not in platforms:
            dev_errors.append(f"platform '{dev.platform_name}' not found")
        if dev.role_name not in roles:
            dev_errors.append(f"role '{dev.role_name}' not found")
        if dev.site not in sites:
            dev_errors.append(f"site '{dev.site}' not found")

        if dev_errors:
            for err in dev_errors:
                msg = f"Device '{dev.name}': {err}"
                logger.warn("Device validation failed", device=dev.name, reason=err)
                result.errors.append(msg)
            continue

        position = dev.position if dev.position else None
        face = "front" if position else None

        payload = {
            "name": dev.name,
            "device_type": types[dev.device_type],
            "role": roles[dev.role_name],
            "site": sites[dev.site],
            "platform": platforms[dev.platform_name],
            "status": dev.status,
            "serial": dev.serial,
            "rack": dev.rack,
            "slot": dev.slot,
            "face": face,
            "position": position,
            "tags": [SEGMENTATION_TAG_ID],
            "tenant": ONBOARDING_TENANT_ID,
            "custom_fields": {
                "automation_instance": dev.automation_instance,
                "procurement_ticket_url": dev.procurement_ticket,
                "syncable": True,
            },
        }
        result.valid_devices.append(payload)

    logger.info(
        "Validation complete",
        valid=len(result.valid_devices),
        errors=len(result.errors),
    )
    return result


# ---------------------------------------------------------------------------
# Switch status resolution
# ---------------------------------------------------------------------------
def resolve_status_from_switches(
    client: NetboxClient,
    switch_names: list[str],
    fallback_status: str,
    logger: FileLogger,
) -> str:
    """Check switch statuses in NetBox and derive the onboarding status.

    - All switches "active" → returns "active"
    - Any switch "planned"  → returns "planned"
    - Switch not found      → warning, uses fallback
    """
    if not switch_names:
        logger.info("No switches to check, using fallback status", status=fallback_status)
        return fallback_status

    statuses: list[str] = []

    for name in switch_names:
        switch = client.get_single(f"dcim/devices/?name={name}")
        if not switch:
            logger.warn("Switch not found, using fallback status", switch=name)
            continue
        switch_status = switch.get("status", {}).get("value", "")
        statuses.append(switch_status)
        logger.info("Switch status checked", switch=name, status=switch_status)

    if not statuses:
        logger.warn("No switches found in NetBox, using fallback", status=fallback_status)
        return fallback_status

    if any(s == "planned" for s in statuses):
        resolved = "planned"
    else:
        resolved = "active"

    logger.info("Status resolved from switches", resolved=resolved, switch_statuses=statuses)
    return resolved
