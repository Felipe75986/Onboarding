import os
import sys
from pathlib import Path

from file_logger import FileLogger
from netbox_onboarding.config import load_minimal_config, create_session
from netbox_onboarding.client import NetboxClient
from netbox_onboarding.activate import activate_from_manifest


def main() -> None:
    """Activate all objects in a manifest from planned to active."""
    # -- Manifest path -----------------------------------------------------
    manifest_path = os.getenv("RD_FILE_MANIFEST")
    if not manifest_path:
        if len(sys.argv) > 1:
            manifest_path = sys.argv[1]
        else:
            print("Usage: python run_activate.py <manifest_json_path>")
            print("  Or set the RD_FILE_MANIFEST environment variable.")
            sys.exit(1)

    if not Path(manifest_path).exists():
        print(f"Manifest file not found: {manifest_path}")
        sys.exit(1)

    # -- Setup -------------------------------------------------------------
    config = load_minimal_config()
    session = create_session()
    logger = FileLogger(
        logs_dir=Path("logs"),
        process_name="netbox_activate",
        username="system",
    )

    logger.info("Starting activation script", manifest=manifest_path)
    client = NetboxClient(config, session, logger)

    # -- Activate ----------------------------------------------------------
    succeeded, failed_count, errors = activate_from_manifest(
        client, manifest_path, logger,
    )

    # -- Summary -----------------------------------------------------------
    logger.info(
        "Activation finished",
        succeeded=succeeded,
        failed=failed_count,
    )

    if errors:
        for desc, err in errors.items():
            logger.error("Activation error", object=desc, error=err)
        sys.exit(1)


if __name__ == "__main__":
    main()
