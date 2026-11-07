"""Dispersion figures for any band: n, V and P from a wavelength triad.

The Abbe number V_d = (n_d - 1)/(n_F - n_C) is a visible-light figure. A
designer working in the SWIR, MWIR or LWIR needs the same idea at their own
wavelengths. For a triad (short, mid, long):

    V_band = (n_mid - 1) / (n_short - n_long)
    P_band = (n_mid - n_long) / (n_short - n_long)

V_band ranks dispersion (high = low dispersion) and P_band is the partial
dispersion that sets the secondary spectrum of an achromat in that band,
(P1 - P2)/(V1 - V2), exactly as P_g,F does in the visible.

Every index comes from db.n_at: a verified dispersion fit inside the range its
source states, or tabulated literature n interpolated inside the table. A
material that cannot give all three indices that way is left out, never
extrapolated. The figures are CALCULATED. The triad presets are conventions
(MWIR 3/4/5 um and LWIR 8/10/12 um are the usual ones); any triad can be used.
"""
from __future__ import annotations

import pandas as pd

PRESETS = {
    "Visible (F, d, C)": (486.1327, 587.5618, 656.2725),
    "NIR (0.70 / 0.85 / 1.00 um)": (700.0, 850.0, 1000.0),
    "SWIR (0.9 / 1.3 / 1.7 um)": (900.0, 1300.0, 1700.0),
    "MWIR (3 / 4 / 5 um)": (3000.0, 4000.0, 5000.0),
    "LWIR (8 / 10 / 12 um)": (8000.0, 10000.0, 12000.0),
}
COLUMNS = ["glass_id", "n_short", "n_mid", "n_long", "v_band", "p_band",
           "n_basis"]


def triad_label(triad) -> str:
    return "/".join(f"{w / 1000:g}" for w in triad) + " um"


# A tabulated n printed to d decimals resolves 10^-d. In the IR a band's
# n_short - n_long can be a few 1e-3 (silicon over 8-12 um), so V and P built
# from a 4-decimal table would be mostly rounding: P came out as exactly 5/12
# for one silicon page. They are given only when the difference spans at
# least this many steps of the table's precision (P then good to ~1 %).
MIN_STEPS = 100
# ... and at least this much in absolute terms: IR literature n is rarely
# better than ~1e-4, whatever number of digits a table prints.
MIN_DIFF = 1e-4


def _table_step(db, glass_id: str) -> float:
    """Smallest step a material's tabulated n resolves (10^-decimals)."""
    cache = db.__dict__.setdefault("_n_table_step", {})
    if glass_id not in cache:
        df = db.spectral_nk_for(glass_id)
        step = 1.0
        if df is not None:
            vals = [float(v) for v in df["n"].dropna()]
            for d in range(0, 10):
                if all(abs(round(v, d) - v) < 1e-12 for v in vals):
                    step = 10.0 ** -d
                    break
            else:
                step = 1e-10
        cache[glass_id] = step
    return cache[glass_id]


def _film_ids(db) -> set:
    ids = db.__dict__.get("_film_ids")
    if ids is None:
        nk = db.spectral_nk
        ids = (set(nk.loc[nk["measurement_form"] == "film", "glass_id"].astype(str))
               if not nk.empty and "measurement_form" in nk.columns else set())
        db.__dict__["_film_ids"] = ids
    return ids


def band_figures(db, glass_id: str, triad) -> dict | None:
    """n at the three wavelengths, V_band and P_band for one material, or
    None when: any index would need extrapolation; the material is a thin
    film; n <= 1 or n is not normally dispersive across the triad (an
    absorption band); or tabulated n is too coarse or too close to resolve
    the band's dispersion (MIN_STEPS, MIN_DIFF)."""
    if glass_id in _film_ids(db):
        return None                       # a film's constants are not the bulk's
    ns, kinds = [], set()
    for wl in triad:
        v, kind = db.n_at(glass_id, float(wl))
        if v is None:
            return None
        ns.append(float(v))
        kinds.add(str(kind))
    s, m, lo = ns
    if s == lo:
        return None
    if lo <= 1.0:
        # n < 1 inside a strong absorption (reststrahlen) band: not a
        # transmitting material there.
        return None
    if not (s > m > lo):
        # Not normally dispersive across the triad: an absorption feature in
        # the band, or noise - V and P would mean nothing.
        return None
    if "interpolated" in kinds and (
            s - lo < MIN_STEPS * _table_step(db, glass_id) or s - lo < MIN_DIFF):
        return None
    return {"glass_id": glass_id, "n_short": s, "n_mid": m, "n_long": lo,
            "v_band": (m - 1.0) / (s - lo), "p_band": (m - lo) / (s - lo),
            "n_basis": ", ".join(sorted(kinds))}


def band_table(db, triad, ids=None) -> pd.DataFrame:
    """band_figures for every material (or `ids`) that can give them.
    Cached with the database's derived-data cache when read from disk."""
    from glassmatch import cache
    triad = tuple(float(w) for w in triad)
    if not (triad[0] < triad[1] < triad[2]):
        raise ValueError("the triad must be short < mid < long")

    def build():
        rows = [r for g in (ids if ids is not None
                            else db.glasses["glass_id"].astype(str))
                if (r := band_figures(db, g, triad)) is not None]
        return pd.DataFrame(rows, columns=COLUMNS)
    if ids is not None:
        return build()
    cdir = db.cache_dir() if hasattr(db, "cache_dir") else None
    name = "band_" + "_".join(f"{w:g}" for w in triad)
    return cache.frame(cdir, name, build)


def band_glass_table(gtable: pd.DataFrame, bt: pd.DataFrame) -> pd.DataFrame:
    """A glass_table (pairs.glass_table) with V_d / P_g,F replaced by the
    band's V and P, so the glass map and pair finder work in that band.
    Only materials with band figures remain; their thermal columns are
    dropped, because dn/dT is not known at IR wavelengths for most of
    them."""
    import numpy as np
    t = gtable.drop(columns=[c for c in ("vd", "pgf", "nd", "dpgf_calc", "dpgf_mfr")
                             if c in gtable.columns])
    t = t.merge(bt[["glass_id", "n_mid", "v_band", "p_band", "n_basis"]],
                on="glass_id", how="inner")
    for c in ("thermo_optic", "thermo_optic_air", "thermo_optic_vacuum"):
        t[c] = np.nan
    t["dpgf_calc"] = np.nan
    t["dpgf_mfr"] = np.nan
    return t.rename(columns={"v_band": "vd", "p_band": "pgf", "n_mid": "nd"})


ROOM_C = (15.0, 30.0)


def measurement_temperature_c(name: str):
    """Measurement temperature (C) a crystal page's display name states
    ('Si (Li, 100 K)' -> -173.15), or None when it states none."""
    import re
    m = re.search(r"(\d+(?:\.\d+)?) (K|°C)(?=[,)])", str(name))
    if not m:
        return None
    v = float(m.group(1))
    return v - 273.15 if m.group(2) == "K" else v


def material_keys(db) -> dict:
    """glass_id -> material: literature pages of one crystal (different
    authors, temperatures, rays) share their material; every other glass is
    its own material."""
    g = db.glasses
    return {gid: (f"RII:{fam}" if mid == "RII" else gid)
            for gid, mid, fam in zip(g["glass_id"].astype(str),
                                     g["manufacturer_id"].astype(str),
                                     g["glass_family"].astype(str))}


def at_room_temperature(name: str) -> bool:
    t = measurement_temperature_c(name)
    return t is None or ROOM_C[0] <= t <= ROOM_C[1]
