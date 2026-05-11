from .config import DhcpConfig, create_session
from .csv_parser import MacIpRow, parse_delivery_csv, parse_onboarding_csv
from .dhcp_apply import apply_to_server
from .dhcp_writer import generate_entries
from .exceptions import MacCollectionError
from .inputs import DhcpInputs
from .netbox_lookup import get_switch_info
from .switch_client import collect_macs_for_port


def run(config: DhcpConfig, inputs: DhcpInputs, logger) -> None:
    """Top-level orchestrator: parse CSVs, collect MACs, write and apply DHCP config.

    Raises DhcpApplyError or MacCollectionError on failure so the entrypoint
    can catch, log, and exit(1) without a traceback visible to operators.
    """
    if inputs.mode == "chassis":
        rows = _run_chassis(inputs, logger)
    else:
        rows = _run_individual(config, inputs, logger)

    logger.info("Generating DHCP entries", count=len(rows))
    content = generate_entries(rows, rack=inputs.rack_name, ru=inputs.ru_position)

    if not content.strip():
        raise MacCollectionError("No DHCP entries generated — nothing to apply.")

    logger.info("Applying DHCP config", host=config.dhcp_server_host)
    _, message = apply_to_server(
        content,
        host=config.dhcp_server_host,
        user=config.dhcp_server_user,
        password=config.dhcp_server_password,
    )
    logger.info("DHCP config applied", message=message)


def _run_chassis(inputs: DhcpInputs, logger) -> list[MacIpRow]:
    logger.info("Mode: chassis — reading MACs from onboarding CSV")
    rows = parse_onboarding_csv(inputs.onboarding_csv)
    if not rows:
        raise MacCollectionError(
            "Onboarding CSV returned no rows with both MAC and IPMI IP populated. "
            "Fill the MAC column in the sheet or switch to individual mode."
        )
    logger.info("Chassis rows parsed", count=len(rows))
    return rows


def _run_individual(config: DhcpConfig, inputs: DhcpInputs, logger) -> list[MacIpRow]:
    logger.info("Mode: individual — discovering MACs via switch SSH")
    session = create_session()
    entries = parse_delivery_csv(inputs.delivery_csv)

    # Resolve each unique switch label once.
    unique_labels = {e.switch.label for e in entries}
    switch_infos = {}
    for label in unique_labels:
        logger.info("Looking up switch in NetBox", label=label)
        switch_infos[label] = get_switch_info(
            session,
            token=config.netbox_token,
            url_api=config.netbox_url_api,
            label=label,
        )

    rows: list[MacIpRow] = []
    for entry in entries:
        info = switch_infos[entry.switch.label]
        logger.info(
            "Collecting MAC",
            server=entry.server_name,
            switch=info.host,
            port=entry.port,
        )
        macs = collect_macs_for_port(
            host=info.host,
            device_os=info.device_os,
            port=entry.port,
            username=config.switch_username,
            password=config.switch_password,
            secret=config.switch_secret,
        )
        rows.append(MacIpRow(server_name=entry.server_name, mac=macs[0], ip=entry.ip))

    logger.info("Individual mode complete", count=len(rows))
    return rows
