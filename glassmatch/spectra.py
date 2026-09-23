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
