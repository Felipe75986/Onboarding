import re
import time

from netmiko import ConnectHandler

from .exceptions import MacCollectionError


_MAC_RE = re.compile(r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}")

_TIMEOUTS = {
    "timeout": 120,
    "session_timeout": 120,
    "auth_timeout": 120,
    "banner_timeout": 120,
    "blocking_timeout": 120,
    "conn_timeout": 120,
}


def collect_macs_for_port(
    host: str,
    device_os: str,
    port: str,
    username: str,
    password: str,
    secret: str | None = None,
) -> list[str]:
    """SSH into a switch and return all MACs seen on the given port.

    Returns MACs in Cisco dot notation (e.g. '905a.0818.5214').

    For cisco_nxos: queries "show mac address-table interface ethernet1/<port>".
    For cisco_ios:  enters enable mode first, then queries the IOS equivalent.

    Raises MacCollectionError on connection failure or when no MACs are found.
    """
    connect_params = {
        "device_type": device_os,
        "host": host,
        "username": username,
        "password": password,
        "verbose": False,
        "fast_cli": False,
        "global_delay_factor": 2,
        **_TIMEOUTS,
    }
    if secret:
        connect_params["secret"] = secret

    try:
        with ConnectHandler(**connect_params) as conn:
            conn.write_channel("\n")
            time.sleep(1)

            try:
                conn.find_prompt()
            except Exception:
                pass

            if device_os == "cisco_nxos":
                output = conn.send_command(
                    f"show mac address-table interface ethernet1/{port}",
                    read_timeout=60,
                )
            else:
                try:
                    conn.send_command_timing("enable", delay_factor=2)
                    if secret:
                        conn.send_command_timing(secret, delay_factor=2)
                except Exception:
                    pass
                output = conn.send_command(
                    f"show mac address interface ethernet1/{port}",
                    read_timeout=60,
                )

    except MacCollectionError:
        raise
    except Exception as exc:
        raise MacCollectionError(
            f"Failed to connect to switch {host} port {port}: {exc}"
        ) from exc

    macs = _MAC_RE.findall(output.lower())
    if not macs:
        raise MacCollectionError(
            f"No MACs found on {host} port {port}. "
            f"Switch output (first 500 chars):\n{output[:500]}"
        )
    return macs
