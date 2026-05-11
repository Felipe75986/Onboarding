from dataclasses import dataclass

import pandas as pd

from .column_resolver import (
    build_header_map,
    find_column,
    find_header_row,
    find_metadata,
)
from .exceptions import MacCollectionError


# Anchor headers used to locate the row that holds the column labels.
# At least one anchor must appear in the row for find_header_row to accept it.
ANCHORS_ONBOARDING_HEADER = ("Deployment name", "Server Name")
ANCHORS_DELIVERY_HEADER = ("IPMI (White)", "IPMI Cable")

# Aliases per logical column. First alias to match a header wins.
# Add an alias here when the master template renames a column instead of
# chasing positional changes through the codebase.
ALIAS_SERVER_NAME = (
    "Deployment name",
    "Server Name",
    "Hostname",
)
ALIAS_MAC = (
    "MAC Address BMC",
    "MAC Netbox",
    "BMC MAC",
    "MAC eno1",
    "MAC ADDRESS",
    "MAC",
)
ALIAS_IPMI_IP_ONBOARDING = (
    "IPMI/24",
    "Static IPMI IP",
    "IPMI IP",
    "IP IPMI",
    "IPMI",
)
ALIAS_DELIVERY_SERVER = (
    "Server",
    "Server Name",
    "Hostname",
)
ALIAS_IPMI_SECTION = (
    "IPMI (White)",
    "IPMI Cable",
    "IPMI section",
)
ALIAS_IPMI_IP_DELIVERY = (
    "IPMI IP",
    "IP IPMI",
    "IPMI Address",
)
ALIAS_WHITE_CABLE = (
    "White Cable",
    "IPMI Cable",
    "IPMI",
)


@dataclass(frozen=True)
class MacIpRow:
    """Per-device MAC + IPMI IP for direct DHCP entry generation (chassis mode)."""
    server_name: str
    mac: str
    ip: str


@dataclass(frozen=True)
class SwitchRef:
    """A switch reference: NetBox label + which RU it occupies."""
    label: str
    ru: str


@dataclass(frozen=True)
class DeliveryEntry:
    """Per-device IPMI cabling: which switch + port, expected IPMI IP.

    Used by individual mode where MAC is unknown until the switch is queried
    by port.
    """
    server_name: str
    switch: SwitchRef
    port: str
    ip: str


def _read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, header=None, dtype=str, keep_default_na=False)


def _cell(df: pd.DataFrame, row: int, col: int) -> str:
    value = str(df.iloc[row, col]).strip()
    return "" if value.lower() == "nan" else value


def parse_onboarding_csv(path: str) -> list[MacIpRow]:
    """Parse the Onboarding CSV (chassis mode).

    Returns one MacIpRow per device that has BOTH a MAC and an IPMI IP
    populated. Skips rows missing either — the operator hasn't filled that
    device yet, and there is nothing useful for DHCP without both fields.

    May return an empty list when no device row is fully populated; the
    orchestrator decides how to handle that (typical response is to fail
    fast and suggest individual mode).
    """
    df = _read_csv(path)
    header_row = find_header_row(df, ANCHORS_ONBOARDING_HEADER)
    headers = build_header_map(df, header_row)

    name_col = find_column(headers, *ALIAS_SERVER_NAME)
    mac_col = find_column(headers, *ALIAS_MAC)
    ip_col = find_column(headers, *ALIAS_IPMI_IP_ONBOARDING)

    rows: list[MacIpRow] = []
    for i in range(header_row + 1, len(df)):
        name = _cell(df, i, name_col)
        if not name:
            continue
        mac = _cell(df, i, mac_col)
        ip = _cell(df, i, ip_col)
        if not mac or not ip:
            continue
        rows.append(MacIpRow(server_name=name, mac=mac, ip=ip))

    return rows


def parse_delivery_csv(path: str) -> list[DeliveryEntry]:
    """Parse the Delivery CSV (individual mode).

    Reads the IPMI switch reference (NetBox label + RU) from the cable-color
    metadata block at the top of the sheet, then iterates the device rows
    below the section-header row to extract each server's IPMI switch port
    and target IP.

    MAC is intentionally not extracted — individual mode discovers each MAC
    by querying the resolved switch on the resolved port at runtime.
    """
    df = _read_csv(path)

    switch_label = find_metadata(df, ALIAS_WHITE_CABLE, value_col_offset=3)
    switch_ru = find_metadata(df, ALIAS_WHITE_CABLE, value_col_offset=2)

    section_row = find_header_row(df, ANCHORS_DELIVERY_HEADER)
    headers = build_header_map(df, section_row)

    server_col = find_column(headers, *ALIAS_DELIVERY_SERVER)
    ipmi_section_col = find_column(headers, *ALIAS_IPMI_SECTION)
    ip_col = find_column(headers, *ALIAS_IPMI_IP_DELIVERY)

    # Sub-header row sits at section_row + 1. Under the IPMI (White) section,
    # the layout is fixed by the master template: [+0] = "Switch RU",
    # [+1] = "Port". Per-row "Switch RU" cells are typically empty after the
    # first row (operator only fills the cable-color block at the top), so
    # the canonical IPMI switch reference comes from there, not per-row.
    port_col = ipmi_section_col + 1

    entries: list[DeliveryEntry] = []
    for i in range(section_row + 2, len(df)):
        server = _cell(df, i, server_col)
        if not server:
            continue
        port = _cell(df, i, port_col)
        ip = _cell(df, i, ip_col)
        if not port or not ip:
            continue
        entries.append(DeliveryEntry(
            server_name=server,
            switch=SwitchRef(label=switch_label, ru=switch_ru),
            port=port,
            ip=ip,
        ))

    if not entries:
        raise MacCollectionError(
            f"No delivery rows found in {path}. Expected at least one server "
            f"row with both port and IPMI IP populated after row {section_row}."
        )

    return entries
