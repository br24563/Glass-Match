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
