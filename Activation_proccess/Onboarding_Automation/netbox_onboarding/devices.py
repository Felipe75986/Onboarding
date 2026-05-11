from __future__ import annotations

from file_logger import FileLogger
from .client import NetboxClient
from .config import OnboardingConfig


# ---------------------------------------------------------------------------
# Chassis
# ---------------------------------------------------------------------------
def create_chassis(
    client: NetboxClient,
    payload: dict,
    logger: FileLogger,
) -> int | None:
    """Create a chassis device in NetBox. Returns the chassis ID or None."""
    logger.info("Creating chassis", chassis=payload["name"])
    response = client.create("dcim/devices/", payload)
    if response:
        chassis_id = response["id"]
        logger.info("Chassis created", chassis=payload["name"], id=chassis_id)
        return chassis_id
    logger.error("Failed to create chassis", chassis=payload["name"])
    return None


# ---------------------------------------------------------------------------
# Device bay
# ---------------------------------------------------------------------------
def create_device_bay(
    client: NetboxClient,
    chassis_id: int,
    device_id: int,
    slot: int,
    logger: FileLogger,
) -> None:
    """Create a device bay linking a device to a chassis slot."""
    logger.info("Creating device bay", chassis_id=chassis_id, device_id=device_id, slot=slot)
    data = {
        "device": {"id": chassis_id},
        "name": f"slot-{slot}",
        "installed_device": {"id": device_id},
    }
    result = client.create("dcim/device-bays/", data)
    if result:
        logger.info("Device bay created", slot=slot, device_id=device_id)
    else:
        logger.error("Failed to create device bay", slot=slot, device_id=device_id)


# ---------------------------------------------------------------------------
# Devices (single and bulk)
# ---------------------------------------------------------------------------
def create_devices(
    client: NetboxClient,
    payloads: list[dict],
    chassis_id: int | None,
    logger: FileLogger,
) -> list[dict]:
    """Create devices. Uses bulk POST when no chassis; sequential otherwise."""
    created: list[dict] = []

    if not chassis_id:
        # Bulk creation — extract slots before sending (not a NetBox field)
        clean_payloads = []
        slots = []
        for p in payloads:
            p_copy = dict(p)
            slots.append(p_copy.pop("slot", None))
            clean_payloads.append(p_copy)

        logger.info("Creating devices in bulk", count=len(clean_payloads))
        results = client.bulk_create("dcim/devices/", clean_payloads)
        for device in results:
            logger.info("Device created", device=device["name"], id=device["id"])
            created.append(device)
    else:
        # Sequential — need to link each device to chassis bay
        for payload in payloads:
            p_copy = dict(payload)
            slot = p_copy.pop("slot", None)
            name = p_copy["name"]

            logger.info("Creating device", device=name)
            response = client.create("dcim/devices/", p_copy)
            if response:
                logger.info("Device created", device=name, id=response["id"])
                created.append(response)
                if slot is not None:
                    create_device_bay(client, chassis_id, response["id"], slot, logger)
            else:
                logger.error("Failed to create device", device=name)

    return created


# ---------------------------------------------------------------------------
# Interfaces (bulk)
# ---------------------------------------------------------------------------
def create_interfaces_bulk(
    client: NetboxClient,
    device_id: int,
    logger: FileLogger,
) -> dict[str, int]:
    """Create IPMI, PXE, and ETH0 interfaces in a single bulk POST.

    Returns a mapping of interface name -> interface ID.
    """
    interfaces = [
        {
            "device": device_id,
            "name": "IPMI",
            "type": "1000base-t",
            "enabled": True,
            "mgmt_only": True,
        },
        {
            "device": device_id,
            "name": "PXE",
            "type": "1000base-t",
            "enabled": True,
            "mgmt_only": True,
        },
        {
            "device": device_id,
            "name": "ETH0",
            "type": "1000base-t",
            "enabled": True,
            "mgmt_only": False,
        },
    ]

    logger.info("Creating interfaces (bulk)", device_id=device_id)
    results = client.bulk_create("dcim/interfaces/", interfaces)

    interface_ids: dict[str, int] = {}
    for iface in results:
        interface_ids[iface["name"]] = iface["id"]
        logger.info("Interface created", name=iface["name"], id=iface["id"])

    return interface_ids


# ---------------------------------------------------------------------------
# IP Addresses
# ---------------------------------------------------------------------------
def create_ip_address(
    client: NetboxClient,
    payload: dict,
    logger: FileLogger,
) -> dict | None:
    """Create an IP address if it doesn't already exist."""
    address = payload["address"]
    logger.info("Creating IP address", address=address)

    # Check existence
    existing = client.get(f"ipam/ip-addresses/?q={address}")
    if existing:
        logger.info("IP already exists, skipping", address=address)
        return None

    result = client.create("ipam/ip-addresses/", payload)
    if result:
        logger.info("IP created", address=address, id=result["id"])
        return result
    logger.error("Failed to create IP", address=address)
    return None


# ---------------------------------------------------------------------------
# Primary IP assignment
# ---------------------------------------------------------------------------
def update_device_primary_ip(
    client: NetboxClient,
    device_id: int,
    ip_id: int,
    version: str,
    logger: FileLogger,
) -> None:
    """Set the primary IPv4 or IPv6 on a device."""
    logger.info("Updating primary IP", device_id=device_id, version=version, ip_id=ip_id)
    key = "primary_ip6" if version == "ipv6" else "primary_ip4"
    client.update(f"dcim/devices/{device_id}/", {key: ip_id})
