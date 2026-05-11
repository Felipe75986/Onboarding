import sys
from pathlib import Path

# FileLogger lives in Onboarding_Automation — add to path before importing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ONBOARDING_DIR = _REPO_ROOT / "Onboarding_Automation"
if str(_ONBOARDING_DIR) not in sys.path:
    sys.path.insert(0, str(_ONBOARDING_DIR))

from file_logger import FileLogger  # noqa: E402

from dhcp_provisioning.config import load_config
from dhcp_provisioning.exceptions import DhcpError
from dhcp_provisioning.inputs import parse_inputs
from dhcp_provisioning import orchestrator


def main() -> None:
    try:
        config = load_config()
        inputs = parse_inputs(config)
    except DhcpError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    logger = FileLogger(
        logs_dir=Path("logs"),
        process_name="dhcp_provisioning",
        username="system",
    )

    logger.info(
        "Starting DHCP provisioning",
        mode=inputs.mode,
        rack=inputs.rack_name,
        ru=inputs.ru_position,
    )

    try:
        orchestrator.run(config, inputs, logger)
    except DhcpError as exc:
        logger.error("DHCP provisioning failed", error=str(exc))
        sys.exit(1)

    logger.info("DHCP provisioning complete")


if __name__ == "__main__":
    main()
