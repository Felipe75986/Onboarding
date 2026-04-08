from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from file_logger import FileLogger
from .client import NetboxClient


class NetboxCache:
    """Caches NetBox reference data to minimize API round-trips."""

    def __init__(self, client: NetboxClient, logger: FileLogger) -> None:
        self._client = client
        self._logger = logger

        # Type lookups: model/name -> id
        self._device_types: dict[str, int] | None = None
        self._device_roles: dict[str, int] | None = None
        self._platforms: dict[str, int] | None = None
        self._sites: dict[str, int] | None = None

        # VLAN caches
        self._vlan_groups: list[dict] | None = None
        self._vlans: dict[int, list[dict]] = {}  # group_id -> vlans

    # ------------------------------------------------------------------
    # Parallel warm-up
    # ------------------------------------------------------------------

    def warm_up(self) -> None:
        """Pre-fetch device types, roles, platforms, and sites in parallel."""
        self._logger.info("Warming up NetBox cache (parallel fetch)")

        def fetch_types():
            data = self._client.get("dcim/device-types/")
            self._device_types = {dt["model"]: dt["id"] for dt in data}

        def fetch_roles():
            data = self._client.get("dcim/device-roles/")
            self._device_roles = {dr["name"]: dr["id"] for dr in data}

        def fetch_platforms():
            data = self._client.get("dcim/platforms/")
            self._platforms = {dp["name"]: dp["id"] for dp in data}

        def fetch_sites():
            data = self._client.get("dcim/sites/")
            self._sites = {s["name"]: s["id"] for s in data}

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(fetch_types),
                executor.submit(fetch_roles),
                executor.submit(fetch_platforms),
                executor.submit(fetch_sites),
            ]
            for f in futures:
                f.result()  # propagate exceptions

        self._logger.info(
            "Cache warm-up complete",
            device_types=len(self._device_types or {}),
            device_roles=len(self._device_roles or {}),
            platforms=len(self._platforms or {}),
            sites=len(self._sites or {}),
        )

    # ------------------------------------------------------------------
    # Type lookups
    # ------------------------------------------------------------------

    @property
    def device_types(self) -> dict[str, int]:
        if self._device_types is None:
            data = self._client.get("dcim/device-types/")
            self._device_types = {dt["model"]: dt["id"] for dt in data}
        return self._device_types

    @property
    def device_roles(self) -> dict[str, int]:
        if self._device_roles is None:
            data = self._client.get("dcim/device-roles/")
            self._device_roles = {dr["name"]: dr["id"] for dr in data}
        return self._device_roles

    @property
    def platforms(self) -> dict[str, int]:
        if self._platforms is None:
            data = self._client.get("dcim/platforms/")
            self._platforms = {dp["name"]: dp["id"] for dp in data}
        return self._platforms

    @property
    def sites(self) -> dict[str, int]:
        if self._sites is None:
            data = self._client.get("dcim/sites/")
            self._sites = {s["name"]: s["id"] for s in data}
        return self._sites

    # ------------------------------------------------------------------
    # VLAN groups & VLANs
    # ------------------------------------------------------------------

    def get_vlan_groups(self, force_refresh: bool = False) -> list[dict]:
        if self._vlan_groups is None or force_refresh:
            self._vlan_groups = self._client.get("ipam/vlan-groups/")
        return self._vlan_groups

    def get_vlans_for_group(self, group_id: int, force_refresh: bool = False) -> list[dict]:
        if group_id not in self._vlans or force_refresh:
            self._vlans[group_id] = self._client.get(f"ipam/vlans/?group_id={group_id}")
        return self._vlans[group_id]

    def find_vlan_group(self, name: str) -> dict | None:
        groups = self.get_vlan_groups()
        return next((g for g in groups if g["name"] == name), None)

    def find_vlan_in_group(self, vlan_id: int, group_name: str) -> int | None:
        """Return the VLAN's NetBox ID if it exists in the group, else None."""
        group = self.find_vlan_group(group_name)
        if not group:
            return None
        vlans = self.get_vlans_for_group(group["id"])
        for vlan in vlans:
            if vlan["vid"] == vlan_id:
                return vlan["id"]
        return None
