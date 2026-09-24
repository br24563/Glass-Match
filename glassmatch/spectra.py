"""Sellmeier dispersion + Fresnel transmission estimates. Calculated data only."""
from __future__ import annotations
import math
import pandas as pd


def sellmeier_n(wavelength_um: float, B: tuple, C: tuple) -> float:
    l2 = wavelength_um ** 2
    n2 = 1.0 + sum(b * l2 / (l2 - c) for b, c in zip(B, C))
    return math.sqrt(n2) if n2 > 0 else float("nan")


def dispersion_curve(coeffs: dict, wl_um: list) -> pd.DataFrame:
    B = (float(coeffs["B1"]), float(coeffs["B2"]), float(coeffs["B3"]))
    C = (float(coeffs["C1_um2"]), float(coeffs["C2_um2"]), float(coeffs["C3_um2"]))
    rows = [{"wavelength_um": w, "n": sellmeier_n(w, B, C),
             "data_type": "calculated",
             "note": "Evaluated from Sellmeier coefficients; not a manufacturer table."}
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
    return {"value_pct": val * 100.0, "label": label,
            "n_points": int(len(wl_b)), "coverage": coverage}
