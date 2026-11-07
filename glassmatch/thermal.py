"""Refractive index at any temperature and air pressure: n(lambda, T, p).

Catalog indices are *relative*: measured against air at the catalog's
reference temperature T0 and normal pressure p0 = 101 325 Pa. A lens at
another temperature, or in vacuum, sees a different index. GlassMatch gets
it in three steps, every one stated in the result:

1. n_rel(lambda, T0) - the catalog index (db.n_at: the verified dispersion
   fit inside its stated range, or tabulated values; never extrapolated).
2. n_abs(lambda, T0) = n_rel * n_air(lambda, T0, p0), and the change of the
   absolute index from T0 to T from, in order of preference:
     a. the SCHOTT dn/dT model (the glass's Zemax TD record, constants
        D0 D1 D2 E0 E1 lambda_tk and T0), used only where SCHOTT states
        the model is valid: -100 ... +140 C and 0.365 ... 1.014 um;
     b. the maker's own measured dn/dT table (dn_dt_measured.csv), taken
        as constant inside each of the maker's temperature intervals and
        summed over them - only where the intervals cover T0 ... T without
        a gap, at a tabulated line or linearly between two.
3. n_rel(lambda, T, p) = n_abs(lambda, T) / n_air(lambda, T, p).

Air: n_air(lambda, 15 C, p0) - 1 = 1e-8 [6432.8 + 2949810 l^2/(146 l^2 - 1)
+ 25540 l^2/(41 l^2 - 1)] (l in um; Edlen 1953 as SCHOTT TIE-19 and Zemax
use it), scaled by (p/p0) / (1 + 3.4785e-3 (T - 15)). p = 0 is vacuum, where
relative and absolute indices are the same.

What is refused rather than guessed: temperatures no model or table covers
(cryogenic use below -100 C needs measured data GlassMatch does not hold),
wavelengths outside both the TD range and the tabulated lines, and an
absolute n(T) for a glass whose catalog does not state T0 (its dn/dT and
the index *change* between two temperatures are still given).
"""
from __future__ import annotations

import math

from glassmatch.spectra import delta_n_abs

P0 = 101325.0
TD_T_RANGE = (-100.0, 140.0)       # SCHOTT TIE-19: stated validity
TD_WL_RANGE_UM = (0.365, 1.014)
TD_KEYS = ("td_D0", "td_D1", "td_D2", "td_E0", "td_E1", "td_lambda_tk", "td_T0")
LINE_TOL_UM = 5e-4                 # a tabulated line within 0.5 nm


def air_index(wavelength_um: float, t_c: float = 15.0, p_pa: float = P0) -> float:
    """Index of dry air (Edlen 1953 as used by SCHOTT TIE-19 and Zemax)."""
    l2 = float(wavelength_um) ** 2
    n15 = 1e-8 * (6432.8 + 2949810.0 * l2 / (146.0 * l2 - 1.0)
                  + 25540.0 * l2 / (41.0 * l2 - 1.0))
    return 1.0 + n15 * (float(p_pa) / P0) / (1.0 + 3.4785e-3 * (float(t_c) - 15.0))


def td_record(db, glass_id: str):
    """(D0, D1, D2, E0, E1, lambda_tk, T0) from the glass's TD record, or None."""
    vals = [db.property_value(glass_id, k) for k in TD_KEYS]
    if any(v is None or v != v for v in vals):
        return None
    return tuple(vals)


def _td_valid(wl_um, *temps) -> str | None:
    """Why the TD model may not be used here, or None."""
    lo, hi = TD_T_RANGE
    if any(not (lo <= t <= hi) for t in temps):
        return (f"outside the dn/dT model's stated range {lo:g} ... {hi:g} C")
    wlo, whi = TD_WL_RANGE_UM
    if not (wlo - 1e-9 <= wl_um <= whi + 1e-9):
        return (f"{wl_um * 1000:g} nm is outside the dn/dT model's stated "
                f"range {wlo * 1000:g} ... {whi * 1000:g} nm")
    return None


# ---------------------------------------------------------------------------
# Measured tables

def _table(db, glass_id: str) -> dict:
    """basis -> wavelength_um -> sorted [(t_lo, t_hi, dn_dt 1e-6/K, ref, sid)],
    built per glass on first use."""
    gid = str(glass_id)
    cache = db.__dict__.setdefault("_dndt_tables", {})
    if gid in cache:
        return cache[gid]
    m = db.dn_dt_measured
    if "_dndt_rows" not in db.__dict__:
        db.__dict__["_dndt_rows"] = ({} if m is None or m.empty else
                                     m.groupby("glass_id").indices)
    rows = db.__dict__["_dndt_rows"].get(gid)
    out = {}
    if rows is not None:
        sub = m.iloc[rows]
        for r in sub.itertuples(index=False):
            out.setdefault(r.basis, {}).setdefault(float(r.wavelength_um), []).append(
                (float(r.t_lo_c), float(r.t_hi_c), float(r.dn_dt),
                 bool(r.reference_only), str(r.source_id)))
        for by_wl in out.values():
            for v in by_wl.values():
                v.sort()
    cache[gid] = out
    return out


def _integrate(intervals, ta: float, tb: float):
    """Index change (1e-6) from ta to tb over piecewise-constant intervals,
    or None unless they cover [min, max] without a gap."""
    lo, hi = min(ta, tb), max(ta, tb)
    total, reached, used = 0.0, lo, []
    for t_lo, t_hi, v, ref, sid in intervals:
        if t_hi <= reached or t_lo >= hi:
            continue
        if t_lo > reached + 1e-9:
            return None
        seg = min(t_hi, hi) - reached
        total += v * seg
        used.append((t_lo, t_hi, ref, sid))
        reached += seg
        if reached >= hi - 1e-9:
            break
    if reached < hi - 1e-9:
        return None
    return (total if tb >= ta else -total), used


def measured_delta(db, glass_id: str, wavelength_um: float, ta: float,
                   tb: float, basis: str):
    """Index change (absolute units) from ta to tb from the maker's measured
    table in `basis`, with a description - or (None, reason)."""
    tabs = _table(db, glass_id).get(basis)
    if not tabs:
        return None, f"no measured {basis} dn/dT table"
    wls = sorted(tabs)
    near = [w for w in wls if abs(w - wavelength_um) <= LINE_TOL_UM]
    if near:
        got = _integrate(tabs[near[0]], ta, tb)
        if got is None:
            return None, (f"the measured intervals at {near[0] * 1000:.1f} nm "
                          f"do not cover {min(ta, tb):g} ... {max(ta, tb):g} C")
        d, used = got
        how = f"tabulated at {near[0] * 1000:.1f} nm"
    else:
        below = [w for w in wls if w < wavelength_um]
        above = [w for w in wls if w > wavelength_um]
        if not below or not above:
            return None, (f"{wavelength_um * 1000:g} nm is outside the measured "
                          f"lines {wls[0] * 1000:.1f} ... {wls[-1] * 1000:.1f} nm")
        w1, w2 = below[-1], above[0]
        g1, g2 = _integrate(tabs[w1], ta, tb), _integrate(tabs[w2], ta, tb)
        if g1 is None or g2 is None:
            return None, (f"the measured intervals do not cover "
                          f"{min(ta, tb):g} ... {max(ta, tb):g} C")
        f = (wavelength_um - w1) / (w2 - w1)
        d = g1[0] + f * (g2[0] - g1[0])
        used = g1[1] + g2[1]
        how = (f"interpolated between {w1 * 1000:.1f} and {w2 * 1000:.1f} nm")
    srcs = sorted({u[3] for u in used})
    note = (f"measured {basis} dn/dT ({', '.join(srcs)}), {how}, constant "
            f"within each of the maker's intervals")
    if any(u[2] for u in used):
        note += "; includes values the maker marks as reference only"
    return d * 1e-6, note


CHECK_TOL = 0.5e-6        # model vs measured table, mean dn/dT, 1/K


def _check(db, gid, wl, ta, tb, model: dict, notes):
    """Note where the maker's own measured table disagrees with the TD model
    over the same span by more than CHECK_TOL (in mean dn/dT). model:
    basis -> the model's index change over ta ... tb in that basis."""
    if tb == ta:
        return
    for basis, model_delta in model.items():
        d, _ = measured_delta(db, gid, wl, ta, tb, basis)
        if d is None:
            continue
        diff = (d - model_delta) / (tb - ta)
        if abs(diff) > CHECK_TOL:
            notes.append(f"the maker's measured {basis} dn/dT differs from "
                         f"the model by {diff * 1e6:+.2f}e-6/K over "
                         f"{min(ta, tb):g} ... {max(ta, tb):g} C here")
        return


def _join(a: str, b: str) -> str:
    return a if a == b else f"{a}; {b}"


# ---------------------------------------------------------------------------
# Measured temperature series (crystals)

def temperature_series(db, glass_id: str) -> list:
    """[(T_c, glass_id), ...] sorted by temperature: the literature pages of
    one author's measurement of one crystal (and one ray) at several stated
    temperatures - e.g. Si (Li) at 100 ... 750 K, CaF2 (Bosomworth) at 5 ...
    300 K. Empty when the glass is not a page of such a series, or the
    series is a thin film. Pages are grouped by material family, author and
    ray as their display names state them."""
    import re

    from glassmatch.band import _film_ids, measurement_temperature_c
    cache = db.__dict__.get("_t_series")
    if cache is None:
        groups = {}
        g = db.glasses[db.glasses["manufacturer_id"] == "RII"]
        films = _film_ids(db)
        for gid, name, fam in zip(g["glass_id"].astype(str), g["glass_name"].astype(str),
                                  g["glass_family"].astype(str)):
            t = measurement_temperature_c(name)
            m = re.match(r".+? \((.+?)(?:, ([oe])-ray)?, [\d.]+ (?:K|°C)\)$", name)
            if t is None or m is None or gid in films:
                continue
            groups.setdefault((fam, m.group(1), m.group(2)), []).append((t, gid))
        cache = {}
        for pages in groups.values():
            if len(pages) >= 2:
                pages = sorted(pages)
                for _, gid in pages:
                    cache[gid] = pages
        db.__dict__["_t_series"] = cache
    return cache.get(str(glass_id), [])


def series_index(db, glass_id: str, wavelength_nm: float, t_c: float):
    """n at (lambda, T) from a measured temperature series: linear in T
    between the two bracketing measured temperatures, at a measured
    temperature exactly. -> (n, note) or (None, reason). Never beyond the
    coldest or warmest page."""
    pages = temperature_series(db, glass_id)
    if not pages:
        return None, "not part of a measured temperature series"
    ts = [t for t, _ in pages]
    if not (ts[0] - 1e-9 <= t_c <= ts[-1] + 1e-9):
        return None, (f"the measured series spans {ts[0]:g} ... {ts[-1]:g} C "
                      "(not extrapolated)")
    for i in range(len(pages) - 1):
        if pages[i][0] - 1e-9 <= t_c <= pages[i + 1][0] + 1e-9:
            (t1, g1), (t2, g2) = pages[i], pages[i + 1]
            break
    n1, _ = db.n_at(g1, wavelength_nm)
    n2, _ = db.n_at(g2, wavelength_nm)
    if n1 is None or n2 is None:
        missing = g1 if n1 is None else g2
        return None, f"{missing} gives no index at {wavelength_nm:g} nm"
    f = 0.0 if t2 == t1 else (t_c - t1) / (t2 - t1)
    n = n1 + f * (n2 - n1)
    if abs(t_c - t1) < 1e-9 or abs(t_c - t2) < 1e-9:
        how = f"measured at {t_c:g} C ({g1 if abs(t_c - t1) < 1e-9 else g2})"
    else:
        how = (f"interpolated linearly between the measurements at {t1:g} C "
               f"({g1}) and {t2:g} C ({g2})")
    return n, (f"measured temperature series, {how}; index as the source "
               "publishes it (cryostat measurements are normally in vacuum - "
               "the air/vacuum basis is not converted)")


# ---------------------------------------------------------------------------
# Public API

def index_at(db, glass_id: str, wavelength_nm: float, t_c: float,
             p_pa: float = P0, absolute: bool = False) -> dict:
    """n at (lambda, T, p). Returns a dict with 'n' (None when it cannot be
    given without extrapolating), 'reason', 'basis', 'method', 't0_c',
    'n_catalog' and 'notes'."""
    gid = str(glass_id)
    wl = float(wavelength_nm) / 1000.0
    t_c, p_pa = float(t_c), float(p_pa)
    out = {"glass_id": gid, "wavelength_nm": float(wavelength_nm),
           "temperature_c": t_c, "pressure_pa": p_pa,
           "basis": ("absolute (vacuum)" if absolute else
                     f"relative to air at {t_c:g} C, {p_pa:g} Pa"),
           "n": None, "reason": None, "method": None, "t0_c": None,
           "n_catalog": None, "notes": []}
    if temperature_series(db, gid):
        # A crystal measured at several temperatures answers from its own
        # measurements - the only data GlassMatch has for cryogenic use.
        n, note = series_index(db, gid, float(wavelength_nm), t_c)
        out["basis"] = "as published by the source (measured series)"
        out["t0_c"] = None
        if n is None:
            out["reason"] = note
            return out
        out["n"], out["method"] = n, note
        out["n_catalog"], _ = db.n_at(gid, float(wavelength_nm))
        if p_pa != P0 or absolute:
            out["notes"].append("pressure / absolute options do not apply to a "
                                "published series; the index is as published")
        return out
    n0, kind = db.n_at(gid, float(wavelength_nm))
    if n0 is None:
        out["reason"] = "no catalog index at this wavelength (not extrapolated)"
        return out
    out["n_catalog"], out["catalog_kind"] = n0, kind
    td = td_record(db, gid)
    t0 = td[6] if td else None
    out["t0_c"] = t0
    if t0 is None:
        out["reason"] = ("the source does not state the reference temperature "
                         "of its index (no TD record), so n at another "
                         "temperature cannot be anchored; see dn_dt()")
        return out
    n_air0 = air_index(wl, t0, P0)
    n_abs0 = n0 * n_air0
    why_not_td = _td_valid(wl, t_c, t0)
    if why_not_td is None:
        dn = delta_n_abs(td, n0, wl, t_c)
        n_abs = n_abs0 + dn
        out["method"] = "SCHOTT dn/dT model (TD record)"
        _check(db, gid, wl, t0, t_c,
               {"absolute": dn,
                "relative": n_abs / air_index(wl, t_c, P0) - n0},
               out["notes"])
    else:
        n_abs = None
        d, note = measured_delta(db, gid, wl, t0, t_c, "absolute")
        if d is not None:
            n_abs = n_abs0 + d
        else:
            d, note2 = measured_delta(db, gid, wl, t0, t_c, "relative")
            if d is not None:      # relative at p0 -> absolute via air at T
                n_abs = (n0 + d) * air_index(wl, t_c, P0)
                note = note2
            else:
                note = _join(note, note2)
        if n_abs is None:
            out["reason"] = f"TD model: {why_not_td}; measured: {note}"
            return out
        out["method"] = note
        out["notes"].append(f"TD model not used: {why_not_td}")
    if math.isnan(n_abs):
        out["reason"] = "the dn/dT model is not evaluable here"
        return out
    out["n"] = n_abs if absolute else n_abs / air_index(wl, t_c, p_pa)
    return out


def dn_dt(db, glass_id: str, wavelength_nm: float, t1_c: float, t2_c: float,
          absolute: bool = True) -> dict:
    """Mean dn/dT (1e-6/K) over [t1, t2], absolute or relative to air at
    normal pressure. Needs no reference temperature, so it is given for
    glasses with measured tables but no TD record too."""
    gid = str(glass_id)
    wl = float(wavelength_nm) / 1000.0
    t1, t2 = float(t1_c), float(t2_c)
    basis = "absolute" if absolute else "relative"
    out = {"glass_id": gid, "wavelength_nm": float(wavelength_nm),
           "t1_c": t1, "t2_c": t2, "basis": basis, "dn_dt": None,
           "method": None, "reason": None, "notes": []}
    if t2 == t1:
        out["reason"] = "t1 and t2 must differ"
        return out
    if temperature_series(db, gid):
        a, why_a = series_index(db, gid, float(wavelength_nm), t1)
        b, why_b = series_index(db, gid, float(wavelength_nm), t2)
        if a is None or b is None:
            out["reason"] = why_a if a is None else why_b
            return out
        out["dn_dt"] = (b - a) / (t2 - t1) * 1e6
        out["method"] = ("measured temperature series (piecewise linear in T); "
                         "index basis as published")
        out["basis"] = "as published"
        return out
    n0, _ = db.n_at(gid, float(wavelength_nm))
    td = td_record(db, gid)
    why_not_td = "no TD record" if td is None else _td_valid(wl, t1, t2)
    if why_not_td is None and n0 is not None:
        def n_at_t(t, b):
            n_abs = n0 * air_index(wl, td[6], P0) + delta_n_abs(td, n0, wl, t)
            return n_abs if b == "absolute" else n_abs / air_index(wl, t, P0)
        model = {b: n_at_t(t2, b) - n_at_t(t1, b) for b in (basis, "relative"
                                                            if absolute else "absolute")}
        out["dn_dt"] = model[basis] / (t2 - t1) * 1e6
        out["method"] = "SCHOTT dn/dT model (TD record)"
        _check(db, gid, wl, t1, t2, model, out["notes"])
        return out
    d, note = measured_delta(db, gid, wl, t1, t2, basis)
    if d is None and n0 is not None:
        # The other basis, converted: n_abs = n_rel * n_air(T, p0).
        other = "relative" if absolute else "absolute"
        d2, note2 = measured_delta(db, gid, wl, t1, t2, other)
        if d2 is not None:
            a1, a2 = air_index(wl, t1, P0), air_index(wl, t2, P0)
            if absolute:   # rel -> abs
                d = (n0 + d2) * a2 - n0 * a1
            else:          # abs -> rel
                d = (n0 * a1 + d2) / a2 - n0
            note = f"{note2}, converted to {basis} with the air model"
        else:
            note = _join(note, note2)
    if d is None:
        out["reason"] = (f"TD model: {why_not_td}; measured: {note}"
                         if why_not_td else note)
        return out
    out["dn_dt"] = d / (t2 - t1) * 1e6
    out["method"] = note
    return out


def relative_dndt(dndt_abs, n, wavelength_um: float = 0.5875618,
                  t1_c: float = 20.0, t2_c: float = 40.0):
    """Relative dn/dT (1e-6/K, against air at normal pressure) from absolute
    dn/dT over the same interval: n_rel = n_abs / n_air at each temperature.

    For a lens in air the relative value is the one that matters, and it is
    larger than the absolute one by about n * |dn_air/dT| ~ 1.4e-6/K at the
    d line - not negligible next to the dn/dT of many glasses. Works on
    scalars or arrays; n is the catalog (relative) index."""
    import numpy as np
    dndt_abs = np.asarray(dndt_abs, dtype=float)
    n = np.asarray(n, dtype=float)
    a1 = air_index(wavelength_um, t1_c, P0)
    a2 = air_index(wavelength_um, t2_c, P0)
    dt = t2_c - t1_c
    out = ((n * a1 + dndt_abs * 1e-6 * dt) / a2 - n) / dt * 1e6
    return out if out.ndim else float(out)
