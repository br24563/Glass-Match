"""Supply-risk flags: catalog facts that make a glass hard to buy.

Reasons, never a score. Each flag is a stated fact from the catalog, worded
in the terms its source defines:

* high    - obsolete (no longer produced); known only from a third-party
            mirror of unknown date (data tier "unverified_mirror").
* caution - inquiry / special / melt status (made on request or in
            campaigns); the lowest production frequency in the maker's own
            scale (CDGM "D": melted every 2+ years; HIKARI "D": least
            frequent); relative cost >= 10 times the maker's reference glass
            (the .agf / workbook figure, relative to N-BK7, S-BSL7, H-K9L ...
            as each maker defines it - not comparable across makers beyond
            that).

Things the data does not hold (hygroscopic crystals, export control, lead
time) are not guessed.
"""
from __future__ import annotations

import math

COST_CAUTION = 10.0
FREQUENCY_MEANING = {
    "CDGM": {"D": "melted every 2+ years (CDGM melt frequency D)"},
    "HIKARI": {"D": "least frequent production (HIKARI production frequency D)"},
}
STATUS_TEXT = {
    "obsolete": ("high", "no longer produced (catalog status: obsolete)"),
    "inquiry": ("caution", "available on request only (catalog status: inquiry)"),
    "special": ("caution", "special production (catalog status: special)"),
    "melt": ("caution", "melted to order (catalog status: melt)"),
}


def supply_flags(row) -> list:
    """[(level, text), ...] for one summary row (a dict or Series)."""
    get = row.get
    out = []
    st = str(get("status") or "")
    if st in STATUS_TEXT:
        out.append(STATUS_TEXT[st])
    if get("data_tier") == "unverified_mirror":
        out.append(("high", "known only from a third-party mirror of unknown "
                            "date - it may no longer be made, or made to "
                            "these numbers"))
    freq = str(get("production_frequency") or "").strip().upper()
    meaning = FREQUENCY_MEANING.get(str(get("manufacturer_id") or ""), {}).get(freq)
    if meaning:
        out.append(("caution", meaning))
    try:
        cost = float(get("relative_cost"))
    except (TypeError, ValueError):
        cost = math.nan
    if cost == cost and cost >= COST_CAUTION:
        out.append(("caution", f"relative cost {cost:g} x the maker's reference "
                               "glass"))
    return out


def supply_text(row) -> str:
    """Short one-cell summary: 'HIGH: ...; caution: ...', or ''."""
    flags = supply_flags(row)
    hi = [t for lv, t in flags if lv == "high"]
    ca = [t for lv, t in flags if lv == "caution"]
    parts = ([f"HIGH: {'; '.join(hi)}"] if hi else []) + \
            ([f"caution: {'; '.join(ca)}"] if ca else [])
    return " | ".join(parts)


def supply_column(summary) -> dict:
    """glass_id -> supply_text for every row of a summary frame."""
    return {r["glass_id"]: supply_text(r)
            for r in summary.to_dict(orient="records")}
