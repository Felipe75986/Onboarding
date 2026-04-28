from __future__ import annotations


HEADER_ROW_INDEX = 7

EXPECTED_HEADERS = {
    0: "Deployment name",
    1: "Server Name",
    2: "Cluster",
    3: "Device Type",
    4: "RU",
    5: "SERIAL",
    10: "IPMI /24",
    11: "IPv4 /31",
    13: "IPv6 /64",
    15: "Vlan Segmentação",
    16: "Vlan Group",
}


def _normalize(text) -> str:
    return " ".join(str(text).split())


def _col_letter(col: int) -> str:
    letters = ""
    n = col
    while True:
        letters = chr(ord("A") + n % 26) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return letters


def validate_shape(df) -> list[str]:
    errors: list[str] = []

    min_rows_needed = HEADER_ROW_INDEX + 2
    if len(df) < min_rows_needed:
        errors.append(
            f"CSV has {len(df)} rows, expected at least {min_rows_needed} "
            "(metadata + headers + at least one device row)"
        )
        return errors

    min_cols_needed = max(EXPECTED_HEADERS.keys()) + 1
    if df.shape[1] < min_cols_needed:
        errors.append(
            f"CSV has {df.shape[1]} columns, expected at least {min_cols_needed}"
        )
        return errors

    for col, expected in EXPECTED_HEADERS.items():
        actual = _normalize(df.iloc[HEADER_ROW_INDEX, col])
        expected_norm = _normalize(expected)
        if actual != expected_norm:
            errors.append(
                f"Column {_col_letter(col)} (row 8): expected header "
                f"{expected_norm!r}, got {actual!r}"
            )

    return errors
