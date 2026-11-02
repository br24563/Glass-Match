"""Figures derived from stored data - every one CALCULATED, never catalog.

Optical designers sort on more than n_d and V_d. Everything here is computed
from data GlassMatch already holds, under the same rules as the rest:

* dispersion figures use only verified fits, evaluated only inside the range
  the source states (``db.dispersion_range``) - a figure that would need an
  extrapolated index is missing, not guessed;
* transmission figures interpolate only between listed samples, after
  converting them to the requested thickness (Beer-Lambert);
* every output column is labelled calculated by the caller.

Line wavelengths (um): d 0.5875618, e 0.546074, F 0.4861327, C 0.6562725,
F' 0.4799914, C' 0.6438469, g 0.4358343, t 1.01398.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from glassmatch.spectra import n_from_row, scale_internal_transmittance

D, E, F, C = 0.5875618, 0.546074, 0.4861327, 0.6562725
F1, C1, G, T = 0.4799914, 0.6438469, 0.4358343, 1.01398
LASER_LINES_NM = (355, 532, 1064, 1550)
C_LIGHT = 299_792_458.0

# Column -> (label, unit) for every derived figure, for the UI and exports.
LABELS = {
    "ne": ("n_e (calculated)", ""),
    "ve": ("V_e (calculated)", ""),
    "pgf": ("P_g,F (calculated)", ""),
    "pct": ("P_C,t (calculated)", ""),
    "dpgf_calc": ("ΔP_g,F vs normal line (calculated)", ""),
    "n_at": ("n at λ (calculated)", ""),
    "dn_dlambda": ("dn/dλ at λ (calculated)", "1/um"),
    "group_index": ("group index at λ (calculated)", ""),
    "gvd": ("GVD at λ (calculated)", "fs²/mm"),
    "uv_edge_int80_calc": ("λ at 80 % internal T (calculated)", "nm"),
    "uv_edge_int5_calc": ("λ at 5 % internal T (calculated)", "nm"),
    **{f"t_{nm}": (f"internal T at {nm} nm (calculated)", "%")
       for nm in LASER_LINES_NM},
    "athermal_gamma": ("athermal γ = (dn/dT)/(n−1) − α (calculated)", "1e-6/K"),
    "thermal_shock_fom": ("thermal-shock FOM k(1−ν)/(αE) (calculated)",
                          "(W/m)/MPa"),
    "specific_stiffness": ("specific stiffness E/ρ (calculated)", "GPa·cm³/g"),
}


def _n(fit, lo, hi, wl):
    """n at wl from a verified fit, NaN outside its stated range."""
    if lo is not None and hi is not None and not (lo - 1e-9 <= wl <= hi + 1e-9):
        return float("nan")
    v = n_from_row(fit, wl)
    return v if v == v else float("nan")


def _fits(db, ids=None):
    """(glass_id, fit row, lo, hi) for every verified fit."""
    from glassmatch.importers.agf import is_dispersable_formula
    ids = db.glasses["glass_id"].astype(str) if ids is None else ids
    for gid in ids:
        fit = db.sellmeier_for(gid, sellmeier_only=True)
        if fit is None or not is_dispersable_formula(fit.get("formula")):
            continue
        lo, hi = db.dispersion_range(gid, fit)
        yield gid, fit, lo, hi


def optical_figures(db) -> pd.DataFrame:
    """n_e, V_e, P_g,F, P_C,t and dP_g,F (vs the normal line
    P_g,F = 0.6438 - 0.001682 V_d, as SCHOTT defines it) per glass."""
    rows = []
    for gid, fit, lo, hi in _fits(db):
        n = {k: _n(fit, lo, hi, w) for k, w in
             (("d", D), ("e", E), ("F", F), ("C", C), ("F1", F1), ("C1", C1),
              ("g", G), ("t", T))}
        fc = n["F"] - n["C"]
        vd = (n["d"] - 1) / fc if fc else float("nan")
        pgf = (n["g"] - n["F"]) / fc if fc else float("nan")
        rows.append({
            "glass_id": gid, "ne": n["e"],
            "ve": ((n["e"] - 1) / (n["F1"] - n["C1"])
                   if n["F1"] != n["C1"] else float("nan")),
            "pgf": pgf,
            "pct": (n["C"] - n["t"]) / fc if fc else float("nan"),
            "dpgf_calc": pgf - (0.6438 - 0.001682 * vd)})
    return pd.DataFrame(rows).set_index("glass_id") if rows else pd.DataFrame()


def at_wavelength(db, wavelength_nm: float, ids=None) -> pd.DataFrame:
    """n, dn/dlambda, group index and GVD at one wavelength per glass.

    Derivatives are central differences with a 1 nm step, so they too stay
    inside the fit's range (the point itself must be >= 1 nm inside it).
    GVD = lambda^3 / (2 pi c^2) * d2n/dlambda2, reported in fs^2/mm.
    """
    lam = float(wavelength_nm) / 1000.0
    h = 1e-3
    rows = []
    for gid, fit, lo, hi in _fits(db, ids):
        n0, nm, np_ = (_n(fit, lo, hi, lam), _n(fit, lo, hi, lam - h),
                       _n(fit, lo, hi, lam + h))
        if not all(map(math.isfinite, (n0, nm, np_))):
            continue
        d1 = (np_ - nm) / (2 * h)                       # 1/um
        d2 = (np_ - 2 * n0 + nm) / (h * h)              # 1/um^2
        lam_m = lam * 1e-6
        gvd = lam_m ** 3 / (2 * math.pi * C_LIGHT ** 2) * d2 * 1e12   # s^2/m
        rows.append({"glass_id": gid, "n_at": n0, "dn_dlambda": d1,
                     "group_index": n0 - lam * d1, "gvd": gvd * 1e27})
    return pd.DataFrame(rows).set_index("glass_id") if rows else pd.DataFrame()


def _edge(wl, t, level):
    """Shortest wavelength where T rises through `level`, by linear
    interpolation between the bracketing samples; None when the samples
    never cross it or already start above it (no extrapolation)."""
    for i in range(1, len(wl)):
        if t[i - 1] < level <= t[i]:
            w0, w1, t0, t1 = wl[i - 1], wl[i], t[i - 1], t[i]
            return w0 + (level - t0) * (w1 - w0) / (t1 - t0)
    return None


def transmission_figures(t_groups: dict, thickness_mm: float) -> pd.DataFrame:
    """Internal-transmittance figures at one sample thickness per glass:
    the UV edge (lambda at 80 % and 5 %) and T at common laser lines."""
    rows = []
    for gid, tdf in t_groups.items():
        if tdf is None or len(tdf) < 2:
            continue
        scaled = np.asarray(scale_internal_transmittance(
            tdf["transmission"], tdf["thickness_mm"], thickness_mm), float)
        wl = tdf["wavelength_um"].to_numpy(float) * 1000.0
        ok = np.isfinite(scaled) & np.isfinite(wl)
        if ok.sum() < 2:
            continue
        order = np.argsort(wl[ok])
        wl, t = wl[ok][order], scaled[ok][order]
        # Duplicated wavelengths (conflicts are already quarantined) keep the
        # first sample so the interpolation is well defined.
        wl, first = np.unique(wl, return_index=True)
        t = t[first]
        row = {"glass_id": gid,
               "uv_edge_int80_calc": _edge(wl, t, 0.80),
               "uv_edge_int5_calc": _edge(wl, t, 0.05)}
        for nm in LASER_LINES_NM:
            row[f"t_{nm}"] = (float(np.interp(nm, wl, t)) * 100.0
                              if wl[0] <= nm <= wl[-1] else None)
        rows.append(row)
    return pd.DataFrame(rows).set_index("glass_id") if rows else pd.DataFrame()


def thermo_mechanical(summary: pd.DataFrame) -> pd.DataFrame:
    """Per-glass figures from stored scalar properties (summary_frame
    columns): athermal gamma, thermal-shock FOM and specific stiffness.

    * gamma = (dn/dT)/(n_d - 1) - alpha, in 1e-6/K: a thin lens in air has
      (1/f) df/dT = -gamma, so gamma = 0 is an athermal singlet.
    * k (1 - nu) / (alpha E), in (W/m) per MPa of fracture strength - the
      thermal-shock parameter R' = sigma_f k (1 - nu)/(alpha E) without the
      strength, which few catalogs give.
    * E / rho in GPa cm^3/g.
    """
    s = summary.set_index("glass_id")
    num = lambda c: pd.to_numeric(s[c], errors="coerce") if c in s else np.nan  # noqa: E731
    nd, dndt, cte = num("nd"), num("dn_dt"), num("cte")
    k, nu, e, rho = num("k_thermal"), num("poisson"), num("young"), num("density")
    out = pd.DataFrame(index=s.index)
    out["athermal_gamma"] = dndt / (nd - 1) - cte
    # alpha in 1/K = cte * 1e-6; E in Pa = young * 1e9; per MPa -> x 1e6
    out["thermal_shock_fom"] = k * (1 - nu) / (cte * 1e-6 * e * 1e9) * 1e6
    out["specific_stiffness"] = e / rho
    return out.replace([np.inf, -np.inf], np.nan)
