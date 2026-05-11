from .csv_parser import MacIpRow


def format_mac(mac: str) -> str:
    """Normalize a MAC address to DHCP colon notation (XX:XX:XX:XX:XX:XX).

    Accepts Cisco dot ("905a.0818.5214"), colon ("90:5a:08:18:52:14"),
    dash ("90-5a-08-18-52-14"), or plain hex ("905a08185214").
    """
    clean = mac.replace(".", "").replace(":", "").replace("-", "").upper()
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))


def generate_entries(rows: list[MacIpRow], rack: str, ru: str) -> str:
    """Build a dhcpd.conf host block for each device in rows.

    rack and ru are used to construct deterministic hostnames
    (e.g. rack=B12 ru=06-07 → "host B12_06-07_1 { ... }").
    """
    clean_rack = rack.replace(" ", "_").replace("~", "-")
    clean_ru = ru.replace(" ", "_").replace("~", "-")

    blocks: list[str] = []
    for idx, row in enumerate(rows, 1):
        mac_dhcp = format_mac(row.mac)
        block = (
            f"host {clean_rack}_{clean_ru}_{idx} {{\n"
            f"    hardware ethernet {mac_dhcp};\n"
            f"    fixed-address {row.ip};\n"
            f"}}"
        )
        blocks.append(block)

    return "\n\n".join(blocks)
