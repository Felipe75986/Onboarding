from __future__ import annotations

import ipaddress

from file_logger import FileLogger
from .client import NetboxClient
from .cache import NetboxCache
from .config import OnboardingConfig, VID_RANGE
from .devices import create_ip_address


# ---------------------------------------------------------------------------
# VLAN Group
# ---------------------------------------------------------------------------
def ensure_vlan_group(
    client: NetboxClient,
    cache: NetboxCache,
    vlan_group: str,
    logger: FileLogger,
) -> int:
    """Ensure the VLAN group exists. Creates it if missing. Returns group ID."""
    group = cache.find_vlan_group(vlan_group)
    if group:
        logger.info("VLAN group already exists", vlan_group=vlan_group, id=group["id"])
        return group["id"]

    logger.info("Creating VLAN group", vlan_group=vlan_group)
    payload = {
        "name": vlan_group,
        "slug": vlan_group,
        "vid_ranges": VID_RANGE,
        "description": vlan_group.replace("vg-", "").upper(),
    }
    result = client.create("ipam/vlan-groups/", payload)
    if result:
        cache.get_vlan_groups(force_refresh=True)
        logger.info("VLAN group created", vlan_group=vlan_group, id=result["id"])
        return result["id"]

    logger.error("Failed to create VLAN group", vlan_group=vlan_group)
    raise RuntimeError(f"Cannot create VLAN group {vlan_group}")


# ---------------------------------------------------------------------------
# VLAN
# ---------------------------------------------------------------------------
def ensure_vlan(
    client: NetboxClient,
    cache: NetboxCache,
    vlan_id: int,
    vlan_group: str,
    config: OnboardingConfig,
    logger: FileLogger,
) -> int:
    """Ensure the VLAN exists in the group. Creates if missing. Returns VLAN NetBox ID."""
    existing = cache.find_vlan_in_group(vlan_id, vlan_group)
    if existing:
        logger.info("VLAN already exists", vid=vlan_id, vlan_group=vlan_group, id=existing)
        return existing

    # Need the group ID to create the VLAN
    group = cache.find_vlan_group(vlan_group)
    if not group:
        logger.error("VLAN group not found for VLAN creation", vlan_group=vlan_group)
        raise RuntimeError(f"VLAN group {vlan_group} not found")

    vlan_name = f'{vlan_group.replace("vg-", "").upper()}-Vlan{vlan_id}'
    payload = {
        "vid": vlan_id,
        "name": vlan_name,
        "group": group["id"],
        "status": config.reserva,
    }

    logger.info("Creating VLAN", vid=vlan_id, name=vlan_name, group=vlan_group)
    result = client.create("ipam/vlans/", payload)
    if result:
        cache.get_vlans_for_group(group["id"], force_refresh=True)
        logger.info("VLAN created", vid=vlan_id, id=result["id"])
        return result["id"]

    logger.error("Failed to create VLAN", vid=vlan_id, vlan_group=vlan_group)
    raise RuntimeError(f"Cannot create VLAN {vlan_id} in {vlan_group}")


# ---------------------------------------------------------------------------
# Switch virtual interface
# ---------------------------------------------------------------------------
def create_switch_interface(
    client: NetboxClient,
    vlan_group: str,
    vlan_id: int,
    logger: FileLogger,
) -> int | None:
    """Create a virtual interface on the switch device derived from the VLAN group."""
    switch_name = vlan_group.replace("vg-", "").upper()
    switch = client.get_single(f"dcim/devices/?name={switch_name}")
    if not switch:
        logger.warn("Switch not found for interface creation", switch=switch_name)
        return None

    payload = {
        "device": switch["id"],
        "name": f"Vlan{vlan_id}",
        "type": "virtual",
        "enabled": True,
        "mgmt_only": False,
    }
    logger.info("Creating switch interface", switch=switch_name, interface=f"Vlan{vlan_id}")
    result = client.create("dcim/interfaces/", payload)
    if result:
        logger.info("Switch interface created", id=result["id"])
        return result["id"]

    logger.error("Failed to create switch interface", switch=switch_name)
    return None


# ---------------------------------------------------------------------------
# Network infrastructure orchestrator
# ---------------------------------------------------------------------------
def create_network_infrastructure(
    client: NetboxClient,
    cache: NetboxCache,
    vlan_group: str,
    vlan_id: int,
    config: OnboardingConfig,
    logger: FileLogger,
) -> tuple[int | None, int | None]:
    """Create VLAN group, VLAN, and switch interface.

    Returns (vlan_netbox_id, switch_interface_id).
    """
    # Switch interface
    switch_interface_id = create_switch_interface(client, vlan_group, vlan_id, logger)

    # VLAN group
    ensure_vlan_group(client, cache, vlan_group, logger)

    # VLAN
    vlan_netbox_id = ensure_vlan(client, cache, vlan_id, vlan_group, config, logger)

    return vlan_netbox_id, switch_interface_id


# ---------------------------------------------------------------------------
# Prefix creation
# ---------------------------------------------------------------------------
def create_prefix(
    client: NetboxClient,
    ip_addr: str,
    ip_type: str,
    vlan_id: int | None,
    site_id: int,
    ticket: str,
    switch_interface_id: int | None,
    config: OnboardingConfig,
    logger: FileLogger,
) -> dict | None:
    """Create IPv4/IPv6 prefix and gateway IP address. Returns created prefix or None."""
    gw_interface_type = "dcim.interface" if switch_interface_id else None

    if ip_type == "ip_eth0":
        return _create_ipv4_prefix(
            client, ip_addr, vlan_id, site_id, ticket,
            switch_interface_id, gw_interface_type, config, logger,
        )
    elif ip_type == "ipv6_eth0":
        return _create_ipv6_prefix(
            client, ip_addr, vlan_id, site_id, ticket,
            switch_interface_id, gw_interface_type, config, logger,
        )
    return None


def _create_ipv4_prefix(
    client: NetboxClient,
    ip_addr: str,
    vlan_id: int | None,
    site_id: int,
    ticket: str,
    switch_interface_id: int | None,
    gw_interface_type: str | None,
    config: OnboardingConfig,
    logger: FileLogger,
) -> dict | None:
    """Create an IPv4 /31 prefix and its gateway. Returns created prefix or None."""
    ipv4 = ipaddress.ip_interface(ip_addr)
    if ipv4.network.prefixlen != 31:
        return None

    network = str(ipv4.network)
    logger.info("Creating IPv4 prefix", prefix=network)

    prefix_data = [{"prefix": network, "site": site_id, "status": config.reserva, "description": ticket}]
    if vlan_id:
        prefix_data[0]["vlan"] = {"id": vlan_id}

    existing = client.get(f"ipam/prefixes/?within_include={ipv4.network}")
    result = None
    if existing:
        logger.info("IPv4 prefix already exists", prefix=network)
    else:
        result = client.create("ipam/prefixes/", prefix_data)
        if isinstance(result, list) and result:
            result = result[0]

    # Gateway IP
    gw_payload = {
        "address": network,
        "assigned_object_id": switch_interface_id,
        "assigned_object_type": gw_interface_type,
        "status": config.reserva,
        "role": "vip",
        "description": "Gateway IPv4",
    }
    create_ip_address(client, gw_payload, logger)

    return result


def _create_ipv6_prefix(
    client: NetboxClient,
    ip_addr: str,
    vlan_id: int | None,
    site_id: int,
    ticket: str,
    switch_interface_id: int | None,
    gw_interface_type: str | None,
    config: OnboardingConfig,
    logger: FileLogger,
) -> dict | None:
    """Create an IPv6 /64 prefix and its gateway. Returns created prefix or None."""
    ipv6 = ipaddress.ip_interface(ip_addr)
    if ipv6.network.prefixlen != 64:
        return None

    network = str(ipv6.network)
    logger.info("Creating IPv6 prefix", prefix=network)

    prefix_data = [{"prefix": network, "site": site_id, "status": config.reserva, "description": ticket}]
    if vlan_id:
        prefix_data[0]["vlan"] = {"id": vlan_id}

    existing = client.get(f"ipam/prefixes/?within_include={ipv6.network}")
    result = None
    if existing:
        logger.info("IPv6 prefix already exists", prefix=network)
    else:
        result = client.create("ipam/prefixes/", prefix_data)
        if isinstance(result, list) and result:
            result = result[0]

    # Gateway IP (::1 in the /64)
    gw_ipv6 = f"{ipv6.network[1]}/64"
    gw_payload = {
        "address": gw_ipv6,
        "assigned_object_id": switch_interface_id,
        "assigned_object_type": gw_interface_type,
        "status": config.reserva,
        "role": "vip",
        "description": "Gateway IPv6",
    }
    create_ip_address(client, gw_payload, logger)

    return result
