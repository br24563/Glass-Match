"""Glass pairs: partial dispersion, achromat power split, apochromat and
athermal candidates.

Everything here is CALCULATED (first-order, thin lenses in contact) from the
stored catalog data; nothing is a manufacturer recommendation. Each output
frame carries a `basis` column/attr saying so, and the UI must show it.

Formulas (thin-lens doublet of total power phi, elements 1 and 2 in contact):

  achromat power split      phi1 =  phi * V1 / (V1 - V2)
                            phi2 = -phi * V2 / (V1 - V2)
  secondary spectrum        dF/f ~ (P1 - P2) / (V1 - V2)   (P = P_g,F)
  thermo-optic coefficient  gamma = (dn/dT) / (n_d - 1) - alpha
                            (relative power change per kelvin, 1e-6/K)
  doublet focal drift       (1/f) df/dT = -(phi1*gamma1 + phi2*gamma2) / phi
  residual vs the mount     drift - alpha_mount  (0 = athermal)

The pair search is vectorised over the upper triangle of the N x N glass
matrix, so ~2,000 glasses (about two million pairs) rank in well under a
second.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Fraunhofer lines (um).
LINE_G = 0.4358343
LINE_F = 0.4861327
LINE_D = 0.5875618
LINE_C = 0.6562725

# SCHOTT's normal line through K7 and F2: P_g,F = 0.6438 - 0.001682 V_d.
# Other makers draw theirs through different reference glasses, so a dPgF
# computed here is only comparable within this line - the manufacturer's own
# dPgF is shown alongside it, never replaced by it.
NORMAL_LINE = (0.6438, -0.001682)
NORMAL_LINE_LABEL = "normal line P_g,F = 0.6438 - 0.001682 V_d (SCHOTT, K7/F2)"

PGF_BASIS = "calculated (P_g,F from the verified dispersion fit)"
PAIR_BASIS = ("calculated (first-order thin lenses in contact) - a starting "
              "point for design, not a manufacturer recommendation")

SORT_KEYS = {
    "power": "sum_abs_power",
    "secondary": "abs_secondary",
    "apo": "neg_dv",
    "athermal": "abs_thermal_residual",
}


def normal_line_pgf(vd):
    """P_g,F on the normal line at Abbe number vd (scalar or array)."""
    a, b = NORMAL_LINE
    return a + b * np.asarray(vd, dtype=float)


def partial_dispersion(n_g: float, n_f: float, n_c: float) -> float:
    """P_g,F = (n_g - n_F) / (n_F - n_C)."""
    return (n_g - n_f) / (n_f - n_c)


def partial_dispersion_table(db, glass_ids=None) -> pd.DataFrame:
    """P_g,F for every glass with a verified fit covering g..C.

    Evaluated with the fit's own formula (n_from_row) and only inside the
    range the source states for it: a fit whose range stops short of the g
    line (435.8 nm) gets no P_g,F rather than an extrapolated one.
    """
    from glassmatch.spectra import n_from_row

    ids = db.glass_ids() if glass_ids is None else [str(g) for g in glass_ids]
    rows = []
    for gid in ids:
        coef = db.sellmeier_for(gid, sellmeier_only=True)
        if coef is None:
            continue
        lo, hi = db.dispersion_range(gid, coef)
        if lo is not None and hi is not None and not (lo <= LINE_G and LINE_C <= hi):
            continue
        ng, nf, nc = (n_from_row(coef, w) for w in (LINE_G, LINE_F, LINE_C))
        if not all(np.isfinite([ng, nf, nc])) or nf <= nc:
            continue
        rows.append({"glass_id": gid, "n_g": ng, "n_F": nf, "n_C": nc,
                     "pgf": partial_dispersion(ng, nf, nc),
                     "pgf_basis": PGF_BASIS})
    return pd.DataFrame(rows, columns=["glass_id", "n_g", "n_F", "n_C", "pgf",
                                       "pgf_basis"])


def glass_table(summary: pd.DataFrame, pgf: pd.DataFrame, db=None) -> pd.DataFrame:
    """One row per glass: the columns the glass map and pair finder use.

    `dpgf_calc` is P_g,F minus the normal line above (calculated);
    `dpgf_mfr` is the manufacturer's stored dPgF, against its own line.
    """
    t = summary[["glass_id", "glass", "manufacturer", "manufacturer_id",
                 "material_class", "status", "nd", "vd", "cte", "dn_dt"]].copy()
    t = t.merge(pgf[["glass_id", "pgf", "pgf_basis"]], on="glass_id", how="left")
    for c in ("nd", "vd", "cte", "dn_dt", "pgf"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t["dpgf_calc"] = t["pgf"] - normal_line_pgf(t["vd"])
    if db is not None:
        t["dpgf_mfr"] = [db.property_value(g, "dPgF") for g in t["glass_id"]]
        t["dpgf_mfr"] = pd.to_numeric(t["dpgf_mfr"], errors="coerce")
    else:
        t["dpgf_mfr"] = np.nan
    t["thermo_optic"] = thermo_optic_coefficient(t["dn_dt"], t["nd"], t["cte"])
    return t


def power_split(v1, v2, phi=1.0):
    """Thin-lens achromat element powers (phi1, phi2) for total power phi."""
    v1 = np.asarray(v1, dtype=float)
    v2 = np.asarray(v2, dtype=float)
    dv = v1 - v2
    with np.errstate(divide="ignore", invalid="ignore"):
        return phi * v1 / dv, -phi * v2 / dv


def secondary_spectrum(p1, p2, v1, v2):
    """Residual secondary spectrum of the achromat, (P1 - P2) / (V1 - V2).

    Proportional to the g-F focal shift as a fraction of focal length; zero
    for an apochromatic pair (equal P_g,F)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return (np.asarray(p1, float) - np.asarray(p2, float)) / (
            np.asarray(v1, float) - np.asarray(v2, float))


def thermo_optic_coefficient(dn_dt, nd, cte):
    """gamma = dn/dT / (n_d - 1) - alpha, in 1e-6/K when dn/dT and alpha are.

    The fractional change in a thin lens's power per kelvin. Uses absolute
    dn/dT; for a lens in air the relative value differs by well under
    0.1e-6/K for most glasses."""
    dn_dt = np.asarray(dn_dt, dtype=float)
    nd = np.asarray(nd, dtype=float)
    cte = np.asarray(cte, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return dn_dt / (nd - 1.0) - cte


def thermal_focal_drift(phi1, phi2, gamma1, gamma2, phi=1.0):
    """(1/f) df/dT of the doublet, same units as gamma."""
    return -(np.asarray(phi1) * gamma1 + np.asarray(phi2) * gamma2) / phi


def find_pairs(table: pd.DataFrame, *, sort_by: str = "power", top: int = 200,
               min_dv: float = 10.0, mount_cte: float | None = None,
               apo_dp_max: float = 0.003, apo_min_dv: float = 20.0
               ) -> pd.DataFrame:
    """Rank glass pairs for a cemented/contact achromatic doublet.

    `table` is a glass_table() frame (already filtered to the glasses in
    scope). Element 1 is always the higher-V_d glass (the crown). Pairs with
    V1 - V2 < `min_dv` are dropped: their element powers diverge.

    sort_by:
      "power"     smallest |phi1| + |phi2|  (gentlest curvatures)
      "secondary" smallest |(P1 - P2) / (V1 - V2)|
      "apo"       pairs with |P1 - P2| <= apo_dp_max and V1 - V2 >= apo_min_dv,
                  largest V1 - V2 first (apochromat candidates: equal P_g,F
                  removes the secondary spectrum, large dV keeps the element
                  powers low)
      "athermal"  smallest |focal drift - mount CTE| (needs mount_cte)

    Powers are in units of the total power phi (phi = 1).
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {sorted(SORT_KEYS)}")
    if sort_by == "athermal" and mount_cte is None:
        raise ValueError("athermal ranking needs mount_cte")
    t = table[np.isfinite(table["vd"].to_numpy(float))].reset_index(drop=True)
    n = len(t)
    cols = ["crown", "crown_maker", "flint", "flint_maker", "V1", "V2",
            "phi1", "phi2", "sum_abs_power", "P1", "P2", "dP",
            "secondary_spectrum", "gamma1", "gamma2", "focal_drift",
            "thermal_residual", "crown_id", "flint_id"]
    if n < 2:
        out = pd.DataFrame(columns=cols)
        out.attrs.update(basis=PAIR_BASIS, n_pairs=0)
        return out

    vd = t["vd"].to_numpy(float)
    pgf = t["pgf"].to_numpy(float)
    gam = t["thermo_optic"].to_numpy(float)

    i, j = np.triu_indices(n, k=1)
    swap = vd[i] < vd[j]
    a = np.where(swap, j, i)          # crown (higher V)
    b = np.where(swap, i, j)          # flint
    v1, v2 = vd[a], vd[b]
    keep = (v1 - v2) >= min_dv
    a, b, v1, v2 = a[keep], b[keep], v1[keep], v2[keep]
    n_pairs = int(len(a))

    phi1, phi2 = power_split(v1, v2)
    metric = {"sum_abs_power": np.abs(phi1) + np.abs(phi2)}
    p1, p2 = pgf[a], pgf[b]
    dp = p1 - p2
    ss = secondary_spectrum(p1, p2, v1, v2)
    metric["abs_secondary"] = np.abs(ss)
    metric["neg_dv"] = -(v1 - v2)
    drift = thermal_focal_drift(phi1, phi2, gam[a], gam[b])
    resid = drift - (mount_cte if mount_cte is not None else np.nan)
    metric["abs_thermal_residual"] = np.abs(resid)

    key = metric[SORT_KEYS[sort_by]].copy()
    valid = np.isfinite(key)
    if sort_by == "apo":
        valid &= (np.abs(dp) <= apo_dp_max) & ((v1 - v2) >= apo_min_dv)
    idx = np.flatnonzero(valid)
    if len(idx) > top:
        idx = idx[np.argpartition(key[idx], top - 1)[:top]]
    idx = idx[np.lexsort((metric["sum_abs_power"][idx], key[idx]))]

    out = pd.DataFrame({
        "crown": t["glass"].to_numpy()[a[idx]],
        "crown_maker": t["manufacturer"].to_numpy()[a[idx]],
        "flint": t["glass"].to_numpy()[b[idx]],
        "flint_maker": t["manufacturer"].to_numpy()[b[idx]],
        "V1": v1[idx], "V2": v2[idx],
        "phi1": phi1[idx], "phi2": phi2[idx],
        "sum_abs_power": metric["sum_abs_power"][idx],
        "P1": p1[idx], "P2": p2[idx], "dP": dp[idx],
        "secondary_spectrum": ss[idx],
        "gamma1": gam[a[idx]], "gamma2": gam[b[idx]],
        "focal_drift": drift[idx],
        "thermal_residual": resid[idx],
        "crown_id": t["glass_id"].to_numpy()[a[idx]],
        "flint_id": t["glass_id"].to_numpy()[b[idx]],
    }, columns=cols)
    out["basis"] = PAIR_BASIS
    out.attrs.update(basis=PAIR_BASIS, n_pairs=n_pairs,
                     n_ranked=int(valid.sum()))
    return out
