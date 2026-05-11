from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from file_logger import FileLogger


class OnboardingManifest:
    """Tracks all NetBox object IDs created during an onboarding run.

    The manifest is saved as a JSON file in the manifests/ directory
    and can later be used by the activation script to change status
    from planned to active.
    """

    def __init__(
        self,
        site: str,
        rack: str,
        ticket: str,
        status: str,
        logger: FileLogger,
        manifests_dir: str | Path = "manifests",
    ) -> None:
        self._logger = logger
        self._manifests_dir = Path(manifests_dir)
        self._manifests_dir.mkdir(parents=True, exist_ok=True)

        self._data: dict = {
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "site": site,
            "rack": rack,
            "ticket": ticket,
            "status": status,
            "chassis": None,
            "devices": [],
            "interfaces": [],
            "ip_addresses": [],
            "vlans": [],
            "prefixes": [],
            "cables": [],
        }

    # -- Add methods -------------------------------------------------------

    def set_chassis(self, chassis_id: int, name: str) -> None:
        self._data["chassis"] = {"id": chassis_id, "name": name}

    def add_device(self, device_id: int, name: str) -> None:
        self._data["devices"].append({"id": device_id, "name": name})

    def add_interface(self, interface_id: int, name: str, device: str) -> None:
        self._data["interfaces"].append(
            {"id": interface_id, "name": name, "device": device}
        )

    def add_ip(self, ip_id: int, address: str, device: str) -> None:
        self._data["ip_addresses"].append(
            {"id": ip_id, "address": address, "device": device}
        )

    def add_vlan(self, vlan_id: int, vid: int, group: str) -> None:
        # Avoid duplicates (same VLAN may be referenced by multiple devices)
        for existing in self._data["vlans"]:
            if existing["id"] == vlan_id:
                return
        self._data["vlans"].append({"id": vlan_id, "vid": vid, "group": group})

    def add_prefix(self, prefix_id: int, prefix: str) -> None:
        for existing in self._data["prefixes"]:
            if existing["id"] == prefix_id:
                return
        self._data["prefixes"].append({"id": prefix_id, "prefix": prefix})

    def add_cable(self, cable_id: int, description: str) -> None:
        self._data["cables"].append({"id": cable_id, "description": description})

    # -- Persistence -------------------------------------------------------

    @property
    def file_path(self) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        site = self._data["site"].replace(" ", "_")
        rack = self._data["rack"].replace(" ", "_")
        return self._manifests_dir / f"{date_str}_{site}_{rack}.json"

    def save(self) -> Path:
        """Write the manifest to disk. Returns the file path."""
        path = self.file_path
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

        total = (
            len(self._data["devices"])
            + len(self._data["ip_addresses"])
            + len(self._data["vlans"])
            + len(self._data["prefixes"])
            + len(self._data["cables"])
        )
        self._logger.info(
            "Manifest saved",
            path=str(path),
            total_objects=total,
            status=self._data["status"],
        )
        return path

    @staticmethod
    def load(path: str | Path) -> dict:
        """Load a manifest from disk."""
        with Path(path).open("r", encoding="utf-8") as fh:
            return json.load(fh)
