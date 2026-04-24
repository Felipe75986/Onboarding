import os
import sys
from dataclasses import dataclass


@dataclass
class OpsInput:
    site: str
    rack: str
    platform: str
    ticket: str
    chassis_name: str
    chassis_type: str
    chassis_ru: str
    procurement_ticket: str


_FIELD_TO_ENV = {
    "site": "RD_OPTION_SITE",
    "rack": "RD_OPTION_RACK",
    "platform": "RD_OPTION_PLATFORM",
    "ticket": "RD_OPTION_TICKET",
    "chassis_name": "RD_OPTION_CHASSIS_NAME",
    "chassis_type": "RD_OPTION_CHASSIS_TYPE",
    "chassis_ru": "RD_OPTION_CHASSIS_RU",
    "procurement_ticket": "RD_OPTION_PROCUREMENT_TICKET",
}


def read_inputs():
    values = {}
    missing = []
    for field, env_var in _FIELD_TO_ENV.items():
        value = os.environ.get(env_var, "").strip()
        if not value:
            missing.append(env_var)
        values[field] = value
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")
    return OpsInput(**values)
