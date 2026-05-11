import os
from dataclasses import dataclass
from pathlib import Path

from .config import DhcpConfig
from .exceptions import ConfigError


VALID_MODES = ("chassis", "individual")


@dataclass(frozen=True)
class DhcpInputs:
    mode: str
    onboarding_csv: str | None
    delivery_csv: str | None
    rack_name: str
    ru_position: str


def parse_inputs(config: DhcpConfig) -> DhcpInputs:
    """Read RD_OPTION_* / RD_FILE_* per-run inputs and return a validated DhcpInputs.

    Accumulates ALL validation errors before raising — operator sees every
    problem at once instead of fixing one and rerunning to see the next.

    Cross-validates against config: individual mode requires switch credentials
    that load_config() left as None when their env vars were absent.
    """
    mode = (os.getenv("RD_OPTION_MODE") or "").strip().lower()
    onboarding_csv = os.getenv("RD_FILE_ONBOARDING_CSV")
    delivery_csv = os.getenv("RD_FILE_DELIVERY_CSV")
    rack_name = (os.getenv("RD_OPTION_RACK_NAME") or "").strip()
    ru_position = (os.getenv("RD_OPTION_RU_POSITION") or "").strip()

    errors: list[str] = []

    if not mode:
        errors.append(
            f"RD_OPTION_MODE is required (one of: {', '.join(VALID_MODES)})"
        )
    elif mode not in VALID_MODES:
        errors.append(
            f"RD_OPTION_MODE must be one of {VALID_MODES}, got {mode!r}"
        )

    if not rack_name:
        errors.append("RD_OPTION_RACK_NAME is required")
    if not ru_position:
        errors.append("RD_OPTION_RU_POSITION is required")

    if mode == "chassis":
        if not onboarding_csv:
            errors.append("RD_FILE_ONBOARDING_CSV is required for chassis mode")
        elif not Path(onboarding_csv).exists():
            errors.append(f"Onboarding CSV not found: {onboarding_csv}")
    elif mode == "individual":
        if not delivery_csv:
            errors.append("RD_FILE_DELIVERY_CSV is required for individual mode")
        elif not Path(delivery_csv).exists():
            errors.append(f"Delivery CSV not found: {delivery_csv}")
        if not config.switch_username:
            errors.append("RD_OPTION_SWITCH_USERNAME is required for individual mode")
        if not config.switch_password:
            errors.append("RD_OPTION_SWITCH_PASSWORD is required for individual mode")

    if errors:
        raise ConfigError(
            "Invalid Rundeck inputs:\n  - " + "\n  - ".join(errors)
        )

    return DhcpInputs(
        mode=mode,
        onboarding_csv=onboarding_csv,
        delivery_csv=delivery_csv,
        rack_name=rack_name,
        ru_position=ru_position,
    )
