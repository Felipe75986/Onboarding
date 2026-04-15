import os
import sys
from pathlib import Path

from file_logger import FileLogger
from netbox_onboarding.config import load_minimal_config, create_session
from netbox_onboarding.client import NetboxClient
from netbox_onboarding.connections import parse_delivery_csv, create_cables


def main() -> None:
    """Create cable connections in NetBox from a Delivery CSV."""
    # -- File path ---------------------------------------------------------
    file_path = os.getenv("RD_FILE_DELIVERY")
    if not file_path:
        if len(sys.argv) > 1:
            file_path = sys.argv[1]
        else:
            print("Usage: python run_connections.py <delivery_csv_path>")
            print("  Or set the RD_FILE_DELIVERY environment variable.")
            sys.exit(1)

    # -- Setup -------------------------------------------------------------
    config = load_minimal_config()
    session = create_session()
    logger = FileLogger(
        logs_dir=Path("logs"),
        process_name="netbox_connections",
        username="system",
    )

    logger.info("Starting cable connections", file=file_path)
    client = NetboxClient(config, session, logger)

    # -- Parse & create ----------------------------------------------------
    delivery = parse_delivery_csv(file_path, logger)
    succeeded, failed = create_cables(client, delivery, logger)

    # -- Summary -----------------------------------------------------------
    logger.info(
        "Connections finished",
        succeeded=len(succeeded),
        failed=len(failed),
    )

    if failed:
        logger.error("Failed cables summary", cables=list(failed.keys()))
        sys.exit(1)


if __name__ == "__main__":
    main()
