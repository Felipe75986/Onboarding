import re

from .exceptions import MacCollectionError


_HEADER_SCAN_LIMIT = 20


def normalize(text) -> str:
    """Lowercase, replace newlines with spaces, collapse whitespace, strip.

    Used to compare CSV header cells across whitespace, case, and embedded
    newline variations. "MAC Netbox", "MAC\\nNetbox", and "mac netbox" all
    normalize to the same key.
    """
    s = str(text).replace("\n", " ").lower().strip()
    return re.sub(r"\s+", " ", s)


def _is_present(cell) -> bool:
    s = str(cell).strip()
    return bool(s) and s.lower() != "nan"


def find_header_row(df, anchor_aliases) -> int:
    """Scan the first 20 rows for a row containing any of the anchor headers.

    Returns the row index. Raises MacCollectionError when no row matches —
    the master template likely changed and the alias list needs an update.
    """
    anchors = {normalize(a) for a in anchor_aliases}
    scan = min(_HEADER_SCAN_LIMIT, len(df))
    for idx in range(scan):
        cells = {normalize(c) for c in df.iloc[idx] if _is_present(c)}
        if cells & anchors:
            return idx
    raise MacCollectionError(
        f"Header row not found in first {scan} rows. "
        f"Tried anchors: {sorted(anchors)}"
    )


def build_header_map(df, header_row: int) -> dict[str, int]:
    """Return {normalized_header: column_index} from the given row.

    Empty / 'nan' cells are skipped. If two cells normalize to the same
    key, the later one wins — caller can detect this by comparing the
    map size to the row width if it matters.
    """
    return {
        normalize(cell): col
        for col, cell in enumerate(df.iloc[header_row])
        if _is_present(cell)
    }


def find_column(headers: dict[str, int], *aliases: str) -> int:
    """Return column index for the first alias that matches a header.

    Raises MacCollectionError when no alias matches, listing aliases tried
    and headers available so the operator can update the alias list.
    """
    for alias in aliases:
        n = normalize(alias)
        if n in headers:
            return headers[n]
    raise MacCollectionError(
        f"Column not found. Tried: {list(aliases)}. "
        f"Available headers: {sorted(headers)}"
    )


def find_metadata(df, label_aliases, value_col_offset: int = 1) -> str:
    """Find a row whose column 0 matches a label, return cell at value_col_offset.

    Used for parsing labeled cells in rows above the device table — e.g.
    rows where column 0 is "Site" / "Cabinet" / "Platform" and the value
    sits at column 1 (or column 4, etc., depending on template layout).
    """
    aliases = {normalize(a) for a in label_aliases}
    scan = min(_HEADER_SCAN_LIMIT, len(df))
    label_found = False
    for idx in range(scan):
        cell = normalize(df.iloc[idx, 0])
        if cell in aliases:
            label_found = True
            value = str(df.iloc[idx, value_col_offset]).strip()
            if value and value.lower() != "nan":
                return value
    if label_found:
        raise MacCollectionError(
            f"Metadata label found but value is empty at column offset "
            f"{value_col_offset}. Tried labels: {sorted(aliases)}"
        )
    raise MacCollectionError(
        f"Metadata label not found in first {scan} rows. "
        f"Tried: {sorted(aliases)}"
    )
