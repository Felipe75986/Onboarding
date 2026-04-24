import os
import sys
from dataclasses import dataclass


@dataclass
class OpsInput:
    site: str
    ticket: str


def read_inputs():
    site = os.environ.get("RD_OPTION_SITE", "").strip()
    ticket = os.environ.get("RD_OPTION_TICKET", "").strip()

    missing = []
    if not site:
        missing.append("RD_OPTION_SITE")
    if not ticket:
        missing.append("RD_OPTION_TICKET")
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    return OpsInput(site=site, ticket=ticket)
