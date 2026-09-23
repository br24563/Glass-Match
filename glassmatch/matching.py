"""Transparent weighted matching. All scores in 0..1 (x100 for %)."""
from __future__ import annotations
import math
import pandas as pd

WEIGHT_KEYS = ["nd", "vd", "transmission", "density", "cte"]

DEFAULT_WEIGHTS = {"nd": 30.0, "vd": 20.0, "transmission": 30.0, "density": 10.0, "cte": 10.0}


def normalize_weights(weights: dict) -> dict:
    total = sum(max(0.0, float(weights.get(k, 0.0))) for k in WEIGHT_KEYS)
    if total <= 0:
        n = len(WEIGHT_KEYS)
        return {k: 1.0 / n for k in WEIGHT_KEYS}
    return {k: max(0.0, float(weights.get(k, 0.0))) / total for k in WEIGHT_KEYS}


def _band_score(value, lo, hi) -> tuple[float, str]:
    """1.0 inside band; linear falloff outside; None -> (None, 'missing')."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None, "missing"
    if lo is None and hi is None:
        return 1.0, "no-requirement"
    lo = -math.inf if lo is None else float(lo)
    hi = math.inf if hi is None else float(hi)
    v = float(value)
    if lo <= v <= hi:
        return 1.0, "met"
    lo = -math.inf if lo is None else float(lo)
    hi = math.inf if hi is None else float(hi)
    v = float(value)
    if lo <= v <= hi:
        return 1.0, "met"
    width = max(hi - lo, 1e-9)
    if v < lo:
        return max(0.0, 1.0 - (lo - v) / (0.5 * width + abs(lo) * 0.05 + 1e-9)), "below"
    return max(0.0, 1.0 - (v - hi) / (0.5 * width + abs(hi) * 0.05 + 1e-9)), "above"


def score_glass(props: dict, requirements: dict, weights: dict,
                transmission_fn=None, require_data: bool = False) -> dict:
    """Score one glass. props: nd/vd/density/cte/transmission values (or None)."""
    w = normalize_weights(weights)
    req = requirements
    out, flags, missing = {}, {}, []
    s, _ = _band_score(props.get("nd"), req.get("nd_min"), req.get("nd_max"))
    out["nd"], flags["nd"] = s, "missing" if s is None else ("met" if s == 1.0 else "partial")
    s, _ = _band_score(props.get("vd"), req.get("vd_min"), req.get("vd_max"))
    out["vd"], flags["vd"] = s, "missing" if s is None else ("met" if s == 1.0 else "partial")
    s, _ = _band_score(props.get("density"), req.get("density_min"), req.get("density_max"))
    out["density"], flags["density"] = s, "missing" if s is None else ("met" if s == 1.0 else "partial")
    s, _ = _band_score(props.get("cte"), req.get("cte_min"), req.get("cte_max"))
    out["cte"], flags["cte"] = s, "missing" if s is None else ("met" if s == 1.0 else "partial")
    tval = props.get("transmission")
    tmin = req.get("transmission_min")
    if tval is None or (isinstance(tval, float) and math.isnan(tval)):
        out["transmission"], flags["transmission"] = None, "missing"
    elif tmin is None:
        out["transmission"], flags["transmission"] = 1.0, "no-requirement"
    else:
        t = float(tval)
        out["transmission"] = 1.0 if t >= float(tmin) else max(0.0, t / float(tmin))
        flags["transmission"] = "met" if t >= float(tmin) else "partial"
    for k, v in out.items():
        if v is None:
            missing.append(k)
    if require_data and missing:
        out["overall"] = 0.0
    else:
        num = sum(w[k] * (out[k] if out[k] is not None else 0.0) for k in WEIGHT_KEYS)
        den = sum(w[k] for k in WEIGHT_KEYS if out[k] is not None) or 1.0
        coverage = sum(w[k] for k in WEIGHT_KEYS if out[k] is not None)
        out["overall"] = (num / den) * (0.5 + 0.5 * coverage)
    out["flags"] = flags
    out["missing"] = missing
    out["completeness"] = 1.0 - len(missing) / len(WEIGHT_KEYS)
    return out


def match_glasses(summary: pd.DataFrame, requirements: dict, weights: dict,
                  transmissions: dict | None = None,
                  require_data: bool = False) -> pd.DataFrame:
    rows = []
    transmissions = transmissions or {}
    for _, r in summary.iterrows():
        gid = str(r["glass_id"])
        props = {"nd": r.get("nd"), "vd": r.get("vd"), "density": r.get("density"),
                 "cte": r.get("cte"), "transmission": transmissions.get(gid)}
        sc = score_glass(props, requirements, weights, require_data=require_data)
        rows.append({"glass_id": gid, "glass": r.get("glass"),
                     "manufacturer": r.get("manufacturer"),
                     "manufacturer_id": r.get("manufacturer_id"),
                     "family": r.get("family"), "nd": r.get("nd"), "vd": r.get("vd"),
                     "density": r.get("density"), "cte": r.get("cte"),
                     "compatibility": round(float(sc["overall"]) * 100, 1),
                     "completeness": round(float(sc["completeness"]) * 100, 1),
                     "missing": ", ".join(sc["missing"]) if sc["missing"] else "complete",
                     **{f"score_{k}": (None if sc[k] is None else round(float(sc[k]) * 100, 1))
                        for k in WEIGHT_KEYS}})
    out = pd.DataFrame(rows)
    return out.sort_values("compatibility", ascending=False).reset_index(drop=True)

