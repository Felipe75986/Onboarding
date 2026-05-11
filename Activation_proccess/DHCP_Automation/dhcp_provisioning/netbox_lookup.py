from dataclasses import dataclass

import requests

from .exceptions import MacCollectionError


@dataclass(frozen=True)
class SwitchInfo:
    host: str
    device_os: str  # "cisco_nxos" or "cisco_ios"


def get_switch_info(
    session: requests.Session,
    token: str,
    url_api: str,
    label: str,
) -> SwitchInfo:
    """Look up a switch in NetBox by name, return its management IP and OS type.

    device_os is "cisco_nxos" when the device type model or manufacturer contains
    "nexus"; falls back to "cisco_ios" otherwise (IOS-XE/IOS access switches).

    Raises MacCollectionError if the device is not in NetBox or has no primary IP.
    """
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    url = f"{url_api.rstrip('/')}/dcim/devices/"

    try:
        resp = session.get(url, headers=headers, params={"name": label}, verify=False)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise MacCollectionError(
            f"NetBox request failed while looking up switch {label!r}: {exc}"
        ) from exc

    results = resp.json().get("results", [])
    if not results:
        raise MacCollectionError(
            f"Switch {label!r} not found in NetBox. "
            "Verify the label matches the NetBox device name exactly."
        )

    device = results[0]

    primary_ip = (device.get("primary_ip4") or {})
    address = primary_ip.get("address", "")
    if not address:
        raise MacCollectionError(
            f"Switch {label!r} has no primary IPv4 address configured in NetBox."
        )

    host = address.split("/")[0]

    device_type = device.get("device_type") or {}
    manufacturer_name = str((device_type.get("manufacturer") or {}).get("name", "")).lower()
    model_name = str(device_type.get("model", "")).lower()

    if "nexus" in manufacturer_name or "nexus" in model_name or "nxos" in model_name:
        device_os = "cisco_nxos"
    else:
        device_os = "cisco_ios"

    return SwitchInfo(host=host, device_os=device_os)
