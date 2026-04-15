import os
from dataclasses import dataclass

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://netbox.latitude.co"
ONBOARDING_TENANT_ID = 18458
SEGMENTATION_TAG_ID = 61
IP_TAG_IDS = {"ip_eth0": 24, "ipv6_eth0": 25, "ip_ipmi": 26}
VID_RANGE = [[3738, 3831]]


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OnboardingConfig:
    file_name: str
    token: str
    reserva: str
    base_url: str
    url_api: str
    status: str  # "planned" when reserva == "reserved", else "active"


def load_config() -> OnboardingConfig:
    """Read environment variables and return a validated config."""
    file_name = os.getenv("RD_FILE_PLANILHA")
    token = os.getenv("RD_OPTION_NETBOXTOKEN")
    reserva = os.getenv("RD_OPTION_RESERVA")

    missing = []
    if not file_name:
        missing.append("RD_FILE_PLANILHA")
    if not token:
        missing.append("RD_OPTION_NETBOXTOKEN")
    if not reserva:
        missing.append("RD_OPTION_RESERVA")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    status = "planned" if reserva == "reserved" else "active"

    return OnboardingConfig(
        file_name=file_name,
        token=token,
        reserva=reserva,
        base_url=BASE_URL,
        url_api=f"{BASE_URL}/api",
        status=status,
    )


def load_minimal_config() -> OnboardingConfig:
    """Load config requiring only the NetBox token.

    Used by scripts that don't need a spreadsheet or reserva status
    (e.g. run_activate.py, run_connections.py).
    """
    token = os.getenv("RD_OPTION_NETBOXTOKEN")
    if not token:
        raise ValueError("Missing required environment variable: RD_OPTION_NETBOXTOKEN")

    return OnboardingConfig(
        file_name="",
        token=token,
        reserva="",
        base_url=BASE_URL,
        url_api=f"{BASE_URL}/api",
        status="",
    )


# ---------------------------------------------------------------------------
# HTTP session with automatic retry
# ---------------------------------------------------------------------------
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
