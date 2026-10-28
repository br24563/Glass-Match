"""Export a selection of glasses as a Zemax OpticStudio .agf catalog.

The step between "shortlist" and "design": the file loads straight into
OpticStudio's glass catalog list. Only what GlassMatch has verified is
written, and it is written verbatim:

  NM <name> <formula> <glass code> <n_d> <V_d> 0 <status> 0
  ED <CTE -30/+70> <CTE 20/+300> <density> <dPgF> 0
  CD <coefficients, in the Zemax order of that formula>
  TD <D0> <D1> <D2> <E0> <E1> <lambda_tk> <T0>
  OD <relative cost> <CR> <FR> <SR> <AR> <PR>
  LD <wl_min_um> <wl_max_um>
  IT <wl_um> <internal transmittance> <thickness_mm>     (one per sample)

Rules, in order of importance:

  * A glass is exported only with a VERIFIED dispersion fit
    (``is_dispersable_formula``). Archived "Non-dispersable" coefficients
    are never written - a design program would evaluate them as a curve.
  * Numbers are the stored values, printed with ``repr`` so they parse back
    to the identical float. Nothing is refitted, rounded or rescaled; a
    missing ED/OD field is written as Zemax's own "not given" (0 / -1).
  * refractiveindex.info crystal pages use that database's formulas. One is
    exported only where a Zemax formula is the SAME expression (see
    ``rii_to_zemax``); the rest are skipped and reported, never approximated.
  * A CC header names GlassMatch, the export date and, for every glass, the
    source catalog(s) and their publication date.

The result is UTF-8 with CRLF line endings, the AGF conventions
``glassmatch.importers.agf`` reads.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from dataclasses import dataclass, field

import pandas as pd

from glassmatch.importers.agf import (C_LINE_UM, D_LINE_UM, F_LINE_UM, OD_PROPS,
                                      TD_PROPS, is_dispersable_formula)
from glassmatch.spectra import (SELLMEIER_POLES, coefficients_of, rii_formula_of,
                                rii_n, zemax_formula_of)

# Zemax NM status field: 0 standard, 1 preferred, 2 obsolete, 3 special, 4 melt.
_ZEMAX_STATUS = {"obsolete": 2}
# Zemax CD lines carry ten coefficients; shorter stored lists are padded with
# zeros, which every formula treats as "term absent".
_CD_WIDTH = 10
# Sellmeier pole count -> the Zemax formula that is exactly that sum.
_POLES_TO_ZEMAX = {n: f for f, n in SELLMEIER_POLES.items()}


@dataclass
class AgfExport:
    """An exported catalog plus what went into it and what was left out."""
    text: str
    exported: dict = field(default_factory=dict)   # Zemax name -> glass_id
    skipped: list = field(default_factory=list)    # (glass_id, reason)
    calculated_nd: dict = field(default_factory=dict)  # glass_id -> (n_d, V_d)

    def to_bytes(self) -> bytes:
        return self.text.encode("utf-8")


def _num(v) -> str:
    """A stored number in a form that parses back to the identical float."""
    return repr(float(v))


def _blank(v) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v)) or str(v).strip() == ""


def rii_to_zemax(rii_formula: int, coeffs: list) -> tuple:
    """(zemax_formula, cd_coefficients) for a refractiveindex.info fit, or
    (None, reason) when no Zemax formula is the same expression.

    Exact equivalents only - each mapping evaluates the same arithmetic as
    ``rii_n``, so n(lambda) is unchanged to the last bit:

      * RII 2 (n^2-1 = C1 + sum B l^2/(l^2-C)) with C1 = 0 and 1-5 poles is
        Zemax Sellmeier-1/-3/-5, coefficients verbatim.
      * RII 1 (the same with resonance WAVELENGTHS, C squared on evaluation)
        with C1 = 0 is the same formulas with C written as k*k - the value
        rii_n itself subtracts.
      * RII 7 (Herzberger) is Zemax Herzberger, coefficients verbatim.

    Everything else - a constant term with several poles, polynomial, Cauchy
    and the exotic forms - would need its coefficients re-expressed or
    refitted, so it is not exported.
    """
    c = [float(x) for x in coeffs]
    f = int(rii_formula)
    if f in (1, 2):
        if len(c) < 3 or len(c) % 2 == 0:
            return None, f"refractiveindex.info formula {f} with {len(c)} coefficients"
        const, pairs = c[0], [(c[i], c[i + 1]) for i in range(1, len(c), 2)]
        if const == 0.0:
            zf = _POLES_TO_ZEMAX.get(max(len(pairs), 3))
            if zf is None:
                return None, (f"refractiveindex.info formula {f} with "
                              f"{len(pairs)} poles (Zemax Sellmeier forms have "
                              "at most 5)")
            out = []
            for b, k in pairs:
                out += [b, k * k if f == 1 else k]
            return zf, out
        return None, (f"refractiveindex.info formula {f} with a constant term "
                      f"and {len(pairs)} poles has no identical Zemax formula")
    if f == 7:
        return 3, c
    return None, (f"refractiveindex.info formula {f} has no identical Zemax "
                  "formula")


def _zemax_name(raw: str) -> str:
    """One whitespace-free token, as the NM record requires."""
    return re.sub(r"\s+", "_", str(raw).strip()) or "UNNAMED"


def _source_line(sources: dict, source_id: str) -> str:
    src = sources.get(source_id)
    if src is None:
        return source_id
    doc = "" if _blank(src.get("source_document")) else str(src["source_document"])
    pub = "" if _blank(src.get("publication_date")) else str(src["publication_date"])
    acc = "" if _blank(src.get("access_date")) else str(src["access_date"])
    when = (f"published {pub}" if pub else "publication date not stated") + \
        (f", accessed {acc}" if acc else "")
    what = f"{doc}, " if doc and doc != source_id else ""
    return f"{source_id} ({what}{when})"


def _dispersion(db, gid: str) -> tuple:
    """(row, zemax_formula, cd_coeffs, reason) for a glass's verified fit."""
    rows = db._sellmeier_rows().get(str(gid)) or []
    row = next((r for r in rows if is_dispersable_formula(r.get("formula"))), None)
    if row is None:
        if rows:
            return None, None, None, ("archived (non-dispersable) fit - never "
                                      "exported")
        return None, None, None, "no dispersion fit"
    coeffs = coefficients_of(row)
    if not coeffs:
        return None, None, None, "verified fit has no stored coefficients"
    rf = rii_formula_of(row)
    if rf is not None:
        zf, out = rii_to_zemax(rf, coeffs)
        if zf is None:
            return None, None, None, out
        return row, zf, [_num(x) for x in out], ""
    zf = zemax_formula_of(row)
    if zf is None:
        return None, None, None, "verified fit names no formula"
    # Verbatim tokens: the stored string already is repr(float).
    return row, zf, str(row["coefficients"]).split(), ""


def _pad(tokens: list) -> list:
    return tokens + ["0.0"] * max(0, _CD_WIDTH - len(tokens))


def export_agf(db, glass_ids, today: _dt.date | None = None) -> AgfExport:
    """Write the given glasses (in order, duplicates ignored) as .agf text."""
    today = today or _dt.date.today()
    pv = db.property_value
    ids = list(dict.fromkeys(str(g) for g in glass_ids))
    # Lookups are built once: a whole-database export is ~2,700 glasses and
    # ~70,000 transmission samples, too many for per-glass DataFrame filters.
    glasses = {str(r["glass_id"]): r for r in db.glasses.to_dict(orient="records")}
    sources = ({str(r["source_id"]): r for r in db.sources.to_dict(orient="records")}
               if not db.sources.empty else {})
    trans = db.transmission
    t_by = {}
    if not trans.empty:
        trans = trans[trans["glass_id"].astype(str).isin(ids)]
        if "data_type" in trans.columns:
            trans = trans[trans["data_type"] == "manufacturer"]
        for g, w, tv, th, src in zip(trans["glass_id"].astype(str),
                                     trans["wavelength_um"], trans["transmission"],
                                     trans["thickness_mm"], trans["source_id"]):
            t_by.setdefault(g, []).append((w, tv, th, src))
    props = db.properties[db.properties["glass_id"].isin(ids)] \
        if not db.properties.empty else db.properties
    p_src = (props.dropna(subset=["source_id"]).groupby("glass_id")["source_id"]
             .agg(lambda x: list(dict.fromkeys(map(str, x)))).to_dict()
             if not props.empty else {})

    result = AgfExport(text="")
    blocks, prov = [], []
    planned = []
    for gid in ids:
        g = glasses.get(gid)
        if g is None:
            result.skipped.append((gid, "not in the database"))
            continue
        row, zf, cd, why = _dispersion(db, gid)
        if row is None:
            result.skipped.append((gid, why))
            continue
        base = gid[4:] if gid.startswith("RII-") else str(g["glass_name"])
        planned.append((gid, g, row, zf, cd, _zemax_name(base)))

    # Names must be unique in one catalog: a name shared by two selected
    # glasses (one glass in two makers' files) falls back to the glass_id.
    counts = pd.Series([p[5].upper() for p in planned]).value_counts() \
        if planned else pd.Series(dtype=int)
    for gid, g, row, zf, cd, name in planned:
        if counts.get(name.upper(), 0) > 1:
            name = _zemax_name(gid)
        nd, vd = pv(gid, "refractive_index_nd"), pv(gid, "abbe_number_vd")
        lo, hi = pv(gid, "wl_min_um"), pv(gid, "wl_max_um")
        if nd is None and rii_formula_of(row) is not None:
            # Crystal pages carry no catalog n_d. Zemax needs one in NM, so it
            # is evaluated from the same fit - only inside the fit's range,
            # else Zemax's own placeholder (1.0 / 0) is written.
            coeffs, rf = coefficients_of(row), rii_formula_of(row)
            def inside(w):
                return lo is None or hi is None or lo <= w <= hi
            if inside(D_LINE_UM):
                nd = rii_n(rf, coeffs, D_LINE_UM)
                if inside(F_LINE_UM) and inside(C_LINE_UM):
                    nf, nc = rii_n(rf, coeffs, F_LINE_UM), rii_n(rf, coeffs, C_LINE_UM)
                    vd = (nd - 1.0) / (nf - nc) if nf != nc else None
                if nd is not None and math.isfinite(nd):
                    result.calculated_nd[gid] = (nd, vd)
                else:
                    nd = vd = None
        # The glass code is a label ("517642.251"), so its stored text is
        # written as is; anything non-numeric is Zemax's 0 ("none").
        code = db._property_index().get((gid, "glass_code"))
        code = str(code).strip() if code is not None else ""
        try:
            float(code)
        except ValueError:
            code = "0"
        status = _ZEMAX_STATUS.get(str(g.get("status") or ""), 0)
        lines = [f"NM {name} {zf} {code} "
                 f"{_num(nd) if nd is not None else '1.0'} "
                 f"{_num(vd) if vd is not None else '0.0'} 0 {status} 0"]
        ed = [pv(gid, p) for p in ("cte", "cte_20_300", "density", "dPgF")]
        if any(v is not None for v in ed):
            lines.append("ED " + " ".join(_num(v) if v is not None else "0.0"
                                          for v in ed) + " 0")
        lines.append("CD " + " ".join(_pad(cd)))
        td = [pv(gid, p) for p, _ in TD_PROPS]
        if all(v is not None for v in td):
            lines.append("TD " + " ".join(_num(v) for v in td))
        od = [pv(gid, p) for p in OD_PROPS]
        if any(v is not None for v in od):
            lines.append("OD " + " ".join(_num(v) if v is not None else "-1"
                                          for v in od))
        if lo is not None and hi is not None:
            lines.append(f"LD {_num(lo)} {_num(hi)}")
        for w, tv, th, _src in t_by.get(gid, []):
            lines.append(f"IT {_num(w)} {_num(tv)} {_num(th)}")
        blocks.extend(lines)
        result.exported[name] = gid

        used = [str(row.get("source_id"))]
        used += p_src.get(gid, [])
        used += [str(t[3]) for t in t_by.get(gid, [])]
        used = [s for s in dict.fromkeys(used) if s and s != "nan"]
        note = "; ".join(_source_line(sources, s) for s in used)
        if gid in result.calculated_nd:
            note += "; n_d/V_d evaluated from the fit (no catalog value)"
        elif nd is None:
            note += ("; no catalog n_d (Zemax placeholder 1.0), fit checked "
                     "by GlassMatch against an independent measurement")
        prov.append(f"CC   {name}: {note}")

    header = [
        f"CC GlassMatch export, {today.isoformat()}: {len(result.exported)} "
        "glass(es), Zemax OpticStudio glass catalog (.agf).",
        "CC Manufacturer data for your own design work. Values are the source "
        "catalogs' own, written verbatim; only verified dispersion fits are "
        "included.",
        "CC Source catalog per glass:",
    ] + prov
    result.text = "\r\n".join(header + blocks) + "\r\n"
    return result
