import os
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import ConfigError

# Make the sibling Onboarding_Automation/ importable so we can reuse the
# canonical NetBox base URL. CLAUDE.md hard rule: never duplicate sandbox
# constants — they live in netbox_onboarding/config.py and only there.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ONBOARDING_DIR = _REPO_ROOT / "Onboarding_Automation"
if str(_ONBOARDING_DIR) not in sys.path:
    sys.path.insert(0, str(_ONBOARDING_DIR))

from netbox_onboarding.config import BASE_URL  # noqa: E402


@dataclass(frozen=True)
class DhcpConfig:
    netbox_token: str
    netbox_base_url: str
    netbox_url_api: str
    switch_username: str | None
    switch_password: str | None
    switch_secret: str | None
    dhcp_server_host: str
    dhcp_server_user: str
    dhcp_server_password: str


def load_config() -> DhcpConfig:
    """Read RD_OPTION_* env vars and return a validated DhcpConfig.

    Always required: RD_OPTION_NETBOXTOKEN, RD_OPTION_DHCP_SERVER_HOST,
    RD_OPTION_DHCP_SERVER_USER, RD_OPTION_DHCP_SERVER_PASSWORD.

    Switch credentials (RD_OPTION_SWITCH_*) load to None when missing —
    parse_inputs() validates them when mode == "individual".
    """
    token = os.getenv("RD_OPTION_NETBOXTOKEN")
    dhcp_host = os.getenv("RD_OPTION_DHCP_SERVER_HOST")
    dhcp_user = os.getenv("RD_OPTION_DHCP_SERVER_USER")
    dhcp_pass = os.getenv("RD_OPTION_DHCP_SERVER_PASSWORD")

    missing = []
    if not token:
        missing.append("RD_OPTION_NETBOXTOKEN")
    if not dhcp_host:
        missing.append("RD_OPTION_DHCP_SERVER_HOST")
    if not dhcp_user:
        missing.append("RD_OPTION_DHCP_SERVER_USER")
    if not dhcp_pass:
        missing.append("RD_OPTION_DHCP_SERVER_PASSWORD")
    if missing:
        raise ConfigError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return DhcpConfig(
        netbox_token=token,
        netbox_base_url=BASE_URL,
        netbox_url_api=f"{BASE_URL}/api",
        switch_username=os.getenv("RD_OPTION_SWITCH_USERNAME") or None,
        switch_password=os.getenv("RD_OPTION_SWITCH_PASSWORD") or None,
        switch_secret=os.getenv("RD_OPTION_SWITCH_SECRET") or None,
        dhcp_server_host=dhcp_host,
        dhcp_server_user=dhcp_user,
        dhcp_server_password=dhcp_pass,
    )


def create_session() -> requests.Session:
    """Build a requests session with retry strategy and SSL warnings disabled."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
