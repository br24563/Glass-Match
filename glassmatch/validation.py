"""Validation: flags impossible/questionable records, never silently fixes."""
from __future__ import annotations
import pandas as pd

RULES = {
    "refractive_index_nd": (1.3, 2.5),
    "abbe_number_vd": (10.0, 120.0),
    "density": (1.5, 8.0),
    "cte": (0.0, 30.0),
    "transmission": (0.0, 100.0),
    "wl_min_um": (0.05, 50.0),
    "wl_max_um": (0.05, 50.0),
    "dPgF": (-0.1, 0.1),
    "glass_code": (20000.0, 999999.999),
}


def validate_property_frame(props: pd.DataFrame) -> list:
    issues = []
    if props.empty:
        return issues
    for i, r in props.iterrows():
        p, v = str(r.get("property", "")), r.get("value")
        try:
            f = float(v)
        except (TypeError, ValueError):
            issues.append({"row": i, "glass_id": r.get("glass_id"),
                           "issue": "non-numeric value", "value": v})
            continue
        if p in RULES:
            lo, hi = RULES[p]
            if not (lo <= f <= hi):
                issues.append({"row": i, "glass_id": r.get("glass_id"),
                               "issue": f"{p}={f} outside [{lo},{hi}]", "value": f})
        if not str(r.get("glass_id", "")):
            issues.append({"row": i, "issue": "missing glass_id", "value": v})
        if not str(r.get("source_id", "")):
            issues.append({"row": i, "glass_id": r.get("glass_id"),
                           "issue": "missing source_id", "value": v})
    dup = props.duplicated(subset=["glass_id", "property", "source_id"], keep=False)
    for i in props[dup].index.tolist():
        issues.append({"row": i, "glass_id": props.loc[i, "glass_id"],
                       "issue": "duplicate record", "value": props.loc[i, "value"]})
    return issues


def validate_glass_frame(glasses: pd.DataFrame) -> list:
    issues = []
    if glasses.empty:
        return issues
    for gid in glasses[glasses.duplicated("glass_id", keep=False)]["glass_id"].tolist():
        issues.append({"glass_id": gid, "issue": "duplicate glass_id"})
    for i, r in glasses.iterrows():
        if not str(r.get("manufacturer_id", "")):
            issues.append({"row": i, "glass_id": r.get("glass_id"),
                           "issue": "missing manufacturer_id"})
    return issues


TRANSMISSION_KEY = ["glass_id", "wavelength_um", "thickness_mm"]

CONFLICT_COLUMNS = ["glass_id", "wavelength_um", "thickness_mm", "n_values",
                    "values", "spread", "source_ids", "data_types",
                    "status", "reason", "action"]


def find_transmission_conflicts(t: pd.DataFrame,
                                value_col: str = "transmission",
                                rtol: float = 1e-9) -> pd.DataFrame:
    """Samples where one (glass, wavelength, thickness) key has >1 distinct value.

    Raw manufacturer catalogs contain these: some are data-entry artifacts (a
    stray ``1E-6`` next to a real 0.99 reading), others are genuine
    disagreements between two catalog sections. GlassMatch does not guess which
    value is right, so every row of a conflicting key is reported here and the
    caller decides what to do with it. The importer quarantines them; the
    migration script moves them to ``transmission_conflicts.csv``.

    Returns one row per conflicting key, with every distinct value preserved.
    """
    if t is None or t.empty or not set(TRANSMISSION_KEY).issubset(t.columns):
        return pd.DataFrame(columns=CONFLICT_COLUMNS)
    vals = pd.to_numeric(t[value_col], errors="coerce")
    work = t.assign(_v=vals)
    grouped = work.groupby(TRANSMISSION_KEY, dropna=False)["_v"]
    # Rename before reset_index: the count would otherwise inherit "_v" and
    # collide with the value column when the keys frame is merged back in.
    n_distinct = grouped.nunique().rename("_n_distinct").reset_index()
    keys = n_distinct[n_distinct["_n_distinct"] > 1].drop(columns="_n_distinct")
    if keys.empty:
        return pd.DataFrame(columns=CONFLICT_COLUMNS)
    hit = work.merge(keys, on=TRANSMISSION_KEY, how="inner")
    rows = []
    for key_vals, grp in hit.groupby(TRANSMISSION_KEY, dropna=False, sort=False):
        glass_id, wl, thick = key_vals
        distinct = sorted({float(v) for v in grp["_v"] if pd.notna(v)})
        spread = (max(distinct) - min(distinct)) if len(distinct) > 1 else 0.0
        rows.append({
            "glass_id": glass_id,
            "wavelength_um": wl,
            "thickness_mm": thick,
            "n_values": len(distinct),
            "values": "; ".join(f"{v:g}" for v in distinct),
            "spread": round(spread, 6),
            "source_ids": "; ".join(sorted({str(s) for s in grp["source_id"]
                                            if pd.notna(s)})),
            "data_types": "; ".join(sorted({str(s) for s in grp["data_type"]
                                            if pd.notna(s)})),
            "status": "quarantined",
            "reason": "duplicate samples disagree at the same wavelength; "
                      "GlassMatch does not choose a winner",
            "action": "excluded from band statistics; both values preserved here "
                      "for maintainer review against the source catalog",
        })
    return pd.DataFrame(rows, columns=CONFLICT_COLUMNS)


def split_transmission_conflicts(t: pd.DataFrame,
                                 value_col: str = "transmission"):
    """(clean, conflicts, conflict_rows) - quarantine every row of a
    conflicting key. The clean frame keeps undisputed samples only; nothing is
    deleted silently because all displaced rows are returned and recorded."""
    conflicts = find_transmission_conflicts(t, value_col)
    if conflicts.empty:
        return t, conflicts, t.iloc[0:0]
    # Tuple-key membership is index-safe: a merge/indicator round-trip loses the
    # link back to the original rows whenever the frame has a non-unique index.
    bad = {tuple(k) for k in conflicts[TRANSMISSION_KEY].itertuples(index=False, name=None)}
    mask = pd.Series(
        [tuple(k) in bad for k in t[TRANSMISSION_KEY].itertuples(index=False, name=None)],
        index=t.index)
    return t[~mask].copy(), conflicts, t[mask].copy()


def validate_transmission_frame(t: pd.DataFrame) -> list:
    """transmission.csv stores a 0-1 fraction per wavelength sample.
    Vectorized — runs over all samples in milliseconds, not minutes."""
    issues = []
    if t.empty:
        return issues
    tv = pd.to_numeric(t["transmission"], errors="coerce")
    wv = pd.to_numeric(t["wavelength_um"], errors="coerce")
    for i in t.index[tv.isna() & t["transmission"].notna()]:
        issues.append({"row": i, "glass_id": t.at[i, "glass_id"],
                       "issue": "non-numeric transmission",
                       "value": t.at[i, "transmission"]})
    for i in t.index[wv.isna() & t["wavelength_um"].notna()]:
        issues.append({"row": i, "glass_id": t.at[i, "glass_id"],
                       "issue": "non-numeric wavelength",
                       "value": t.at[i, "wavelength_um"]})
    for i in t.index[tv.notna() & ((tv < 0.0) | (tv > 1.0))]:
        issues.append({"row": i, "glass_id": t.at[i, "glass_id"],
                       "issue": f"transmission {tv[i]} outside 0-1 fraction",
                       "value": tv[i]})
    for i in t.index[wv.notna() & ((wv < 0.05) | (wv > 50.0))]:
        issues.append({"row": i, "glass_id": t.at[i, "glass_id"],
                       "issue": f"wavelength {wv[i]} um outside 0.05-50",
                       "value": wv[i]})
    src_missing = t["source_id"].isna() | (t["source_id"].astype(str).str.strip() == "")
    for i in t.index[src_missing]:
        issues.append({"row": i, "glass_id": t.at[i, "glass_id"],
                       "issue": "missing source_id",
                       "value": t.at[i, "transmission"]})
    dup = t.index[t.duplicated(subset=["glass_id", "wavelength_um"], keep=False)]
    for i in dup:
        issues.append({"row": i, "glass_id": t.at[i, "glass_id"],
                       "issue": "duplicate glass_id + wavelength sample",
                       "value": t.at[i, "transmission"]})
    return issues


def orphan_source_ids(glasses: pd.DataFrame, properties: pd.DataFrame,
                      sources: pd.DataFrame) -> list:
    """source_ids referenced by data but absent from sources.csv."""
    known = set(sources.get("source_id", pd.Series(dtype=str)).astype(str)) if not sources.empty else set()
    used = set()
    for frame in (glasses, properties):
        if frame is not None and not frame.empty and "source_id" in frame.columns:
            used |= {str(s) for s in frame["source_id"].dropna().unique() if str(s)}
    return sorted(used - known)
