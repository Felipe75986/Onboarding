import os
import sys
from dataclasses import dataclass, field


@dataclass
class OpsInput:
    site: str
    rack: str
    cabinet: str
    platform: str
    ticket: str
    procurement_ticket: str
    mode: str
    server_count: int
    cluster: str
    device_type: str
    chassis_name: str = ""
    chassis_type: str = ""
    chassis_ru: str = ""
    positions: list = field(default_factory=list)


def _env(var):
    return os.environ.get(var, "").strip()


_COMMON_REQUIRED = {
    "site": "RD_OPTION_SITE",
    "rack": "RD_OPTION_RACK",
    "cabinet": "RD_OPTION_CABINET",
    "platform": "RD_OPTION_PLATFORM",
    "ticket": "RD_OPTION_TICKET",
    "procurement_ticket": "RD_OPTION_PROCUREMENT_TICKET",
    "mode": "RD_OPTION_MODE",
    "cluster": "RD_OPTION_CLUSTER",
    "device_type": "RD_OPTION_DEVICE_TYPE",
}


def read_inputs():
    values = {}
    missing = []
    for field_name, env_var in _COMMON_REQUIRED.items():
        v = _env(env_var)
        if not v:
            missing.append(env_var)
        values[field_name] = v

    raw_count = _env("RD_OPTION_SERVER_COUNT")
    if not raw_count:
        missing.append("RD_OPTION_SERVER_COUNT")

    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    if values["mode"] not in ("chassis", "individual"):
        sys.exit(
            f"RD_OPTION_MODE must be 'chassis' or 'individual', got: {values['mode']!r}"
        )

    try:
        server_count = int(raw_count)
    except ValueError:
        sys.exit(f"RD_OPTION_SERVER_COUNT must be an integer, got: {raw_count!r}")
    if server_count <= 0:
        sys.exit(f"RD_OPTION_SERVER_COUNT must be > 0, got: {server_count}")
    values["server_count"] = server_count

    if values["mode"] == "chassis":
        chassis_missing = []
        for field_name, env_var in (
            ("chassis_name", "RD_OPTION_CHASSIS_NAME"),
            ("chassis_type", "RD_OPTION_CHASSIS_TYPE"),
            ("chassis_ru", "RD_OPTION_CHASSIS_RU"),
        ):
            v = _env(env_var)
            if not v:
                chassis_missing.append(env_var)
            values[field_name] = v
        if chassis_missing:
            sys.exit(
                f"Missing env vars required for mode=chassis: {', '.join(chassis_missing)}"
            )
        values["positions"] = []
    else:
        values["chassis_name"] = ""
        values["chassis_type"] = ""
        values["chassis_ru"] = ""
        raw_positions = _env("RD_OPTION_POSITIONS")
        if not raw_positions:
            sys.exit(
                "Missing env var required for mode=individual: RD_OPTION_POSITIONS"
            )
        positions = [p.strip() for p in raw_positions.split(",") if p.strip()]
        if len(positions) != server_count:
            sys.exit(
                f"RD_OPTION_POSITIONS has {len(positions)} entries, "
                f"but RD_OPTION_SERVER_COUNT={server_count}. They must match."
            )
        values["positions"] = positions

    return OpsInput(**values)
