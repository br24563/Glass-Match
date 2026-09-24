"""Validation: flags impossible/questionable records, never silently fixes."""
from __future__ import annotations
import pandas as pd

RULES = {
    "refractive_index_nd": (1.3, 2.5),
    "abbe_number_vd": (10.0, 120.0),
    "density": (1.5, 8.0),
    "cte": (0.0, 30.0),
    "transmission": (0.0, 100.0),
    "wl_min_um": (0.1, 20.0),
    "wl_max_um": (0.1, 20.0),
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
