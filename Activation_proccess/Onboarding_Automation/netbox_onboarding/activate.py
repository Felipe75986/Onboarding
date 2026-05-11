from __future__ import annotations

import time
from datetime import datetime

from file_logger import FileLogger
from .client import NetboxClient
from .manifest import OnboardingManifest


# ---------------------------------------------------------------------------
# Endpoint mapping: object type -> NetBox API endpoint
# ---------------------------------------------------------------------------
OBJECT_ENDPOINTS = {
    "devices": "dcim/devices",
    "ip_addresses": "ipam/ip-addresses",
    "vlans": "ipam/vlans",
    "prefixes": "ipam/prefixes",
}


def activate_from_manifest(
    client: NetboxClient,
    manifest_path: str,
    logger: FileLogger,
) -> tuple[int, int, dict[str, str]]:
    """Change all objects in a manifest from planned to active.

    Returns (succeeded_count, failed_count, {description: error}).
    """
    start = time.time()
    manifest_data = OnboardingManifest.load(manifest_path)

    current_status = manifest_data.get("status", "")
    if current_status != "planned":
        logger.warn(
            "Manifest is not in planned status",
            current_status=current_status,
            path=manifest_path,
        )

    site = manifest_data.get("site", "unknown")
    rack = manifest_data.get("rack", "unknown")
    logger.info(
        "Starting activation",
        manifest=manifest_path,
        site=site,
        rack=rack,
    )

    succeeded = 0
    failed_count = 0
    errors: dict[str, str] = {}

    # -- Activate chassis --------------------------------------------------
    chassis = manifest_data.get("chassis")
    if chassis and chassis.get("id"):
        desc = f"chassis:{chassis['name']}"
        ok = _activate_object(
            client, "dcim/devices", chassis["id"], desc, logger,
        )
        if ok:
            succeeded += 1
        else:
            failed_count += 1

    # -- Activate each object type -----------------------------------------
    for obj_type, endpoint in OBJECT_ENDPOINTS.items():
        objects = manifest_data.get(obj_type, [])
        if not objects:
            continue

        logger.info(f"Activating {obj_type}", count=len(objects))

        for obj in objects:
            obj_id = obj.get("id")
            if not obj_id:
                continue

            # Build a human-readable description
            desc = _describe_object(obj_type, obj)

            ok = _activate_object(client, endpoint, obj_id, desc, logger)
            if ok:
                succeeded += 1
            else:
                failed_count += 1
                errors[desc] = "PATCH failed"

    # -- Update manifest file with activated status ------------------------
    manifest_data["status"] = "active"
    manifest_data["activated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    import json
    from pathlib import Path

    with Path(manifest_path).open("w", encoding="utf-8") as fh:
        json.dump(manifest_data, fh, indent=2, ensure_ascii=False)

    elapsed = round(time.time() - start, 2)
    logger.info(
        "Activation complete",
        succeeded=succeeded,
        failed=failed_count,
        duration_seconds=elapsed,
    )

    return succeeded, failed_count, errors


def _activate_object(
    client: NetboxClient,
    endpoint: str,
    obj_id: int,
    description: str,
    logger: FileLogger,
) -> bool:
    """PATCH a single object to status active. Returns True on success."""
    result = client.update(f"{endpoint}/{obj_id}/", {"status": "active"})
    if result:
        logger.info("Activated", object=description, id=obj_id)
        return True
    logger.error("Failed to activate", object=description, id=obj_id)
    return False


def _describe_object(obj_type: str, obj: dict) -> str:
    """Build a human-readable description for logging."""
    if obj_type == "devices":
        return f"device:{obj.get('name', obj.get('id'))}"
    elif obj_type == "ip_addresses":
        return f"ip:{obj.get('address', obj.get('id'))}"
    elif obj_type == "vlans":
        return f"vlan:{obj.get('vid', obj.get('id'))}"
    elif obj_type == "prefixes":
        return f"prefix:{obj.get('prefix', obj.get('id'))}"
    return f"{obj_type}:{obj.get('id')}"
