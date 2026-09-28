"""Sellmeier dispersion + Fresnel transmission estimates. Calculated data only."""
from __future__ import annotations
import math
import pandas as pd

# Zemax CD records carry at most 5 interleaved (B, C) pairs; B4/B5 and C4/C5
# were previously dropped, which silently truncated genuine 4- and 5-term
# fits (e.g. NIKON NIFS-V) into a wrong 3-term curve.
MAX_TERMS = 5

B_COLS = [f"B{i}" for i in range(1, MAX_TERMS + 1)]
C_COLS = [f"C{i}_um2" for i in range(1, MAX_TERMS + 1)]


def sellmeier_n(wavelength_um: float, B: tuple, C: tuple) -> float:
    l2 = wavelength_um ** 2
    n2 = 1.0 + sum(b * l2 / (l2 - c) for b, c in zip(B, C))
    return math.sqrt(n2) if n2 > 0 else float("nan")


def active_pairs(values) -> list:
    """Interleaved (B1, C1, B2, C2, ...) -> the (B, C) pairs actually used.

    A pair where both members are zero is catalog padding, not a term, so it
    is dropped.  Anything else is kept so it can be judged, not discarded.
    """
    v = [float(x) for x in values]
    return [(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)
            if v[i] != 0.0 or v[i + 1] != 0.0]


def classify_dispersion(values) -> tuple:
    """Return (n_terms, note) describing a raw CD coefficient list.

    Deliberately does NOT decide dispersability.  An early revision rejected any
    term with B <= 0 or C <= 0, reasoning that Sellmeier resonance terms are
    positive.  That is wrong: OHARA ships genuine 3-term fits with a negative
    C (S-BSL7 has C2 = -1.18e-2 um^2) that reproduce n(d) to 1e-5, and that rule
    silently stripped dispersion from real workhorse glasses (S-BSL7, S-FPL51,
    S-LAL, S-PHM, and the whole IR/polymer set).  The only test that reliably
    separates a usable fit from a series/polynomial CD row is whether it
    reproduces the catalog n(d), so that stays the sole gate; the sign pattern
    is reported as an observation, not a verdict.
    """
    pairs = active_pairs(values)
    if not pairs:
        return 0, "no non-zero coefficients"
    neg = [i for i, (b, c) in enumerate(pairs, 1) if b <= 0.0 or c <= 0.0]
    if not neg:
        return len(pairs), ""
    return len(pairs), (f"term(s) {','.join(map(str, neg))} carry a non-positive "
                        "B or C (permitted in multi-pole fits; the n(d) check "
                        "is authoritative)")


def pairs_from_row(row: dict) -> list:
    """(B, C) pairs from a sellmeier.csv row, dropping unpopulated terms."""
    out = []
    for bc, cc in zip(B_COLS, C_COLS):
        b, c = row.get(bc), row.get(cc)
        if b is None or c is None or pd.isna(b) or pd.isna(c):
            continue
        b, c = float(b), float(c)
        if b == 0.0 and c == 0.0:
            continue
        out.append((b, c))
    return out


def n_from_row(row: dict, wavelength_um: float) -> float:
    pairs = pairs_from_row(row)
    if not pairs:
        return float("nan")
    return sellmeier_n(wavelength_um, tuple(b for b, _ in pairs),
                       tuple(c for _, c in pairs))


def dispersion_curve(coeffs: dict, wl_um: list) -> pd.DataFrame:
    pairs = pairs_from_row(coeffs)
    B = tuple(b for b, _ in pairs)
    C = tuple(c for _, c in pairs)
    rows = [{"wavelength_um": w, "n": sellmeier_n(w, B, C),
             "data_type": "calculated",
             "note": f"Evaluated from {len(pairs)}-term Sellmeier "
                     f"coefficients; not a manufacturer table."}
            for w in wl_um]
    return pd.DataFrame(rows)


def fresnel_transmission(n: float) -> float:
    """Uncoated two-surface transmittance estimate T=(1-R)^2, R=((n-1)/(n+1))^2."""
    if n is None or n <= 1.0:
        return float("nan")
    R = ((n - 1.0) / (n + 1.0)) ** 2
    return (1.0 - R) ** 2


# ---------------------------------------------------------------------------
# Manufacturer transmission rows (transmission.csv): 0-1 fraction per sample.
# Band statistics for the three requirement modes. Pure functions: no db.

def band_stats(tdf, lo_um: float, hi_um: float, mode: str = "Average",
               min_coverage: float = 0.90) -> dict | None:
    """Summarize manufacturer transmission samples inside [lo_um, hi_um].

    mode:
      "Average"       - mean of samples in band (any coverage).
      "Minimum"       - lowest sample in band (any coverage).
      "Entire range"  - lowest sample, but ONLY if samples span >= min_coverage
                        of the band; otherwise None (cannot verify the claim).

    Returns dict with value_pct (0-100), label, n_points, coverage — or None
    when there is no usable manufacturer data for this mode. Never fabricates.

    Conflicting duplicate samples at one wavelength (found in some raw .agf
    files) are excluded wholesale — no winner is picked — and the exclusion
    is disclosed in the label.
    """
    if tdf is None or len(tdf) == 0 or hi_um <= lo_um:
        return None
    wl = tdf["wavelength_um"].to_numpy(dtype=float)
    tv = tdf["transmission"].to_numpy(dtype=float)
    import numpy as np
    ok = np.isfinite(wl) & np.isfinite(tv) & (wl >= lo_um) & (wl <= hi_um)
    wl_b, tv_b = wl[ok], tv[ok]
    if len(wl_b) == 0:
        return {"value_pct": None, "reason": "no-samples-in-band",
                "n_points": 0, "coverage": 0.0,
                "label": "manufacturer rows exist but none inside the band"}
    span = hi_um - lo_um
    # Conflicting duplicate samples at the same wavelength (present in some
    # raw .agf files): GlassMatch does not pick a winner. All rows at a
    # disputed wavelength are excluded from the statistic and the exclusion
    # is disclosed in the label (they remain flagged in Data Quality).
    conflict_n = 0
    if len(wl_b) > 1:
        vals_by_wl: dict = {}
        for w, v in zip(wl_b, tv_b):
            vals_by_wl.setdefault(round(float(w), 9), []).append(float(v))
        conflict_wls = {w for w, vs in vals_by_wl.items()
                        if len(vs) > 1 and (max(vs) - min(vs)) > 1e-12}
        if conflict_wls:
            keep = np.array([round(float(w), 9) not in conflict_wls for w in wl_b])
            conflict_n = int((~keep).sum())
            wl_b, tv_b = wl_b[keep], tv_b[keep]
            if len(wl_b) == 0:
                return {"value_pct": None, "reason": "all-samples-conflict",
                        "n_points": 0, "coverage": 0.0,
                        "label": "every in-band sample is a conflicting duplicate "
                                 "(see Data Quality report)"}
    coverage = float((wl_b.max() - wl_b.min()) / span) if len(wl_b) > 1 else 0.0
    if mode == "Entire range" and coverage < min_coverage:
        # cannot honestly claim the entire band meets t_min
        return {"value_pct": None, "reason": "insufficient-coverage",
                "n_points": int(len(wl_b)), "coverage": coverage,
                "label": f"manufacturer coverage {coverage:.0%} of band "
                         f"(<{min_coverage:.0%} required for Entire range)"}
    if mode == "Minimum":
        val = float(tv_b.min())
        how = "minimum sample in band"
    elif mode == "Entire range":
        val = float(tv_b.min())
        how = "minimum (entire-range check)"
    else:
        val = float(tv_b.mean())
        how = "mean of samples in band"
    thickness = None
    if "thickness_mm" in tdf.columns and len(tdf):
        thickness = tdf["thickness_mm"].dropna().iloc[0]
    label = f"manufacturer ({how}; {len(wl_b)} samples"
    if thickness == thickness and thickness is not None:
        label += f"; {thickness:g} mm as listed"
    label += "; internal transmittance)"
    if conflict_n:
        label += (f"; {conflict_n} conflicting duplicate sample(s) excluded "
                  "from the statistic (see Data Quality)")
    return {"value_pct": val * 100.0, "label": label,
            "n_points": int(len(wl_b)), "coverage": coverage}
