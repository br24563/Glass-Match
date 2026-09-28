"""refractiveindex.info (CC0) material pages -> GlassMatch normalized frames.

Why this exists
---------------
The manufacturer ``.agf`` catalogs cover glasses.  They do not cover the
transmissive crystals and semiconductors that UV, mid-IR and far-IR systems
are actually built from (CaF2, MgF2, sapphire, fused silica, ZnSe, Ge, Si,
CdTe ...), because those are sold as bulk crystals rather than as glass.
Those materials are catalogued by refractiveindex.info, a public-domain
(CC0 1.0) compilation of literature optical constants, so - unlike the
``.agf`` files - its data may be bundled and redistributed here.

Data types handled
------------------
``formula 1``
    Sellmeier with the upstream convention
    ``n^2-1 = SUM B_i*l^2/(l^2 - C_i^2)`` where the C coefficients are
    resonance **wavelengths in micrometres** and get squared.  Layout is
    ``[T, B1..Bn, C1..Cn]`` with n = (len-1)/2 terms.  Verified against the
    published Malitson (1963) CaF2 constants: squaring the C values gives
    0.00252643 / 0.01007833 / 1200.55597 and the formula returns
    n(587.6 nm) = 1.43385 against a published 1.43376.  This is easy to get
    wrong - the C values look like textbook Sellmeier C coefficients and are
    off by a square factor - so it is verified rather than assumed.

``tabulated n`` / ``tabulated nk`` / ``tabulated k``
    Wavelength/value tables, stored verbatim as spectral rows.

``tabulated n2``
    **Non-linear** refractive index n2 (~1e-20), not n squared.  Reading it
    as n^2 would be nonsense, so it is skipped with an explicit issue.

``formula 2`` / ``4`` / ``5`` / ``7``
    Not implemented.  Coefficients are preserved verbatim and labelled
    non-dispersable; guessing their equations without the upstream
    specification would be fabrication.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import yaml

from glassmatch.spectra import MAX_TERMS, sellmeier_n

# Standard lines GlassMatch reports n at, when a page's wavelength range
# actually covers them.  Micrometres.
REFERENCE_UM = (0.4861, 0.5876, 0.6563, 1.0, 2.0, 3.0, 4.0, 5.0,
                8.0, 10.0, 12.0)

SUPPORTED_FORMULAS = ("formula 1", "formula 2")
TABULATED_TYPES = {"tabulated n": "n", "tabulated nk": "nk", "tabulated k": "k"}
# Upstream uses two Sellmeier spellings that differ only in the units of C:
#   formula 1 - C is a resonance WAVELENGTH in um, so it is squared on use
#   formula 2 - C is already in um^2, used directly
# Both are interleaved [T, B1, C1, B2, C2, ...].  Getting this wrong returns a
# smooth curve for the wrong material, so the distinction is explicit here.
SQUARES_C = {"formula 1": True, "formula 2": False}
UNSUPPORTED = {
    "tabulated n2": "non-linear index n2, not n^2",
    "formula 4": "formula 4 equation not implemented",
    "formula 5": "formula 5 equation not implemented",
    "formula 7": "formula 7 equation not implemented",
}


def _floats(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        out = []
        for x in raw:
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                pass
        return out
    try:
        return [float(x) for x in str(raw).split()]
    except ValueError:
        return []


def _tabulated(block: dict) -> list:
    """(wavelength_um, col2, col3) rows from a tabulated block."""
    rows = []
    text = block.get("data")
    if not isinstance(text, str):
        return rows
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if len(vals) >= 2:
            rows.append((vals[0], vals[1],
                         vals[2] if len(vals) > 2 else None))
    return rows


def measurement_form(page_stem: str, comments: str) -> str:
    """Classify a page as 'bulk', 'film' or 'unknown'.

    refractiveindex.info catalogues deposited/coated films alongside bulk
    material, and a film's optical constants are NOT the material's. The
    published "2 nm Ge film" page reports n = 1.46 where bulk germanium is
    n ~ 4-5, because a nanometre film is dominated by its interfaces; used
    as bulk data it yields nonsense both for n(lambda) and for any absorption
    or transmission figure derived from k.

    The signal is textual - the page name and the COMMENTS block - because
    there is no reliable numerical one: a film of the right thickness and
    index looks exactly like a bulk sample in a single tabulated column.
    """
    text = f"{page_stem} {comments}".lower()
    # "2nm", "20nm-thick", "nanometre", "thin film", "deposited on"
    if re.search(r"\d+\s*-?\s*nm\b", text) or re.search(r"nano\s*-?\s*met", text):
        return "film"
    if "thin film" in text or "thin-film" in text or "-film" in page_stem.lower():
        return "film"
    if "deposited" in text or "coated" in text or "coating" in text:
        return "film"
    if "substrate" in text or "bulk" in text or "single crystal" in text:
        return "bulk"
    return "unknown"


def parse_ri_page(path: Path) -> dict | None:
    """One YAML page -> its citation, conditions and classified data blocks."""
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(doc, dict) or not doc.get("DATA"):
        return None
    blocks = {"formula": [], "n": [], "nk": [], "k": [], "skipped": []}
    for entry in doc["DATA"]:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type", "")).strip()
        if kind in SUPPORTED_FORMULAS:
            coeffs = _floats(entry.get("coefficients"))
            rng = _floats(entry.get("wavelength_range"))
            n = (len(coeffs) - 1) // 2 if coeffs else 0
            if coeffs and (len(coeffs) - 1) % 2 == 0 and 0 < n <= MAX_TERMS:
                blocks["formula"].append({"coefficients": coeffs,
                                          "range": rng[:2], "n_terms": n,
                                          "kind": kind})
            else:
                blocks["skipped"].append(
                    (kind, f"unsupported coefficient count ({len(coeffs)})"))
        elif kind in TABULATED_TYPES:
            rows = _tabulated(entry)
            if rows:
                blocks[TABULATED_TYPES[kind]].append(rows)
        else:
            blocks["skipped"].append(
                (kind, UNSUPPORTED.get(kind, "unrecognised data type")))
    comments = str(doc.get("COMMENTS") or "").strip()
    return {"references": str(doc.get("REFERENCES") or "").strip(),
            "comments": comments,
            "form": measurement_form(Path(path).stem, comments),
            "conditions": doc.get("CONDITIONS") or {},
            "blocks": blocks}


def n_from_rii_formula(coeffs: list, lam_um: float, n_terms: int | None = None,
                       square_c: bool = True) -> float:
    """Upstream formula 1 / formula 2 -> n.

    The layout is ``[T, B1, C1, B2, C2, ...]`` - interleaved pairs after a
    leading temperature term, n = (len-1)/2 terms.  ``formula 1`` stores C as a
    resonance **wavelength** in um and must be squared; ``formula 2`` already
    stores C in um^2.  Reading the list as grouped B's then C's silently pairs
    every B with the wrong C and returns a curve that is not the material's.
    """
    n = (len(coeffs) - 1) // 2 if n_terms is None else n_terms
    B = tuple(coeffs[1 + 2 * i] for i in range(n))
    raw = [coeffs[2 + 2 * i] for i in range(n)]
    C_um2 = tuple(c * c for c in raw) if square_c else tuple(raw)
    return sellmeier_n(lam_um, B, C_um2)


def _interp(wl: float, rows: list, col: int = 1):
    """Linear interpolation inside a table; (None, (lo, hi)) when outside."""
    pts = sorted((r[0], r[col]) for r in rows if r[col] is not None)
    if len(pts) < 2:
        return None, ((pts[0][0], pts[-1][0]) if pts else (None, None))
    rng = (pts[0][0], pts[-1][0])
    if wl < rng[0] or wl > rng[1]:
        return None, rng
    lo, hi = 0, len(pts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pts[mid][0] <= wl:
            lo = mid
        else:
            hi = mid
    (x0, y0), (x1, y1) = pts[lo], pts[hi]
    if x1 == x0:
        return y0, rng
    return y0 + (y1 - y0) * (wl - x0) / (x1 - x0), rng


def _citation(text: str) -> tuple:
    """(DOI url, short human citation) from a REFERENCES block."""
    doi = ""
    m = re.search(r"https?://doi\.org/(\S+?)[<\s\"']+", text)
    if m:
        doi = "https://doi.org/" + m.group(1).rstrip(".")
    first = ""
    for line in text.splitlines():
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and not line.startswith("http"):
            first = line
            break
    return doi, first


def _prop(gid, source_id, name, value, unit, wl_um, dtype, note) -> dict:
    if value is None or value != value:
        return None
    return {"glass_id": gid, "property": name, "value": value, "unit": unit,
            "reference_wavelength_nm": (round(wl_um * 1000, 4) if wl_um else ""),
            "data_type": dtype, "source_id": source_id, "notes": note}


def _page_formulas(blocks: dict, box: dict) -> list:
    """Formula pages -> sellmeier rows, plus n at each covered reference."""
    gid, source_id = box["gid"], box["src"]
    rows, props = [], []
    for f in blocks["formula"]:
        coeffs, nterms = f["coefficients"], f["n_terms"]
        kind = f.get("kind", "formula 1")
        square_c = SQUARES_C[kind]
        lo, hi = (list(f["range"]) + [None, None])[:2]
        c_note = ("its C coefficients are resonance wavelengths in um and are "
                  "squared on evaluation" if square_c else
                  "its C coefficients are already in um^2 and are used directly")
        row = {"glass_id": gid,
               "formula": (f"Sellmeier-1 ({nterms}-term, refractiveindex.info "
                           f"{kind})"),
               "wavelength_um": (f"{lo}-{hi}" if lo and hi else ""),
               "source_id": source_id, "n_terms": nterms,
               "notes": (f"refractiveindex.info {kind}; {c_note}. "
                         "Verify against the cited reference.")}
        for i in range(nterms):
            c = coeffs[2 + 2 * i]
            row[f"B{i+1}"] = coeffs[1 + 2 * i]
            row[f"C{i+1}_um2"] = c * c if square_c else c
        rows.append(row)
        if lo and hi:
            for nm, v, note in (
                    ("wl_min_um", lo, "Lowest wavelength the cited fit is valid over."),
                    ("wl_max_um", hi, "Highest wavelength the cited fit is valid over.")):
                r = _prop(gid, source_id, nm, v, "um", None, "literature", note)
                if r:
                    props.append(r)
        for wl in REFERENCE_UM:
            if lo and hi and not (lo <= wl <= hi):
                continue
            r = _prop(gid, source_id, "n_at_reference",
                      n_from_rii_formula(coeffs, wl, nterms, square_c), "", wl,
                      "calculated",
                      f"Evaluated from the refractiveindex.info {kind} "
                      f"{nterms}-term Sellmeier fit; not a tabulated value.")
            if r:
                props.append(r)
    return rows, props


def _page_spectral(blocks: dict, box: dict, form: str = "unknown") -> tuple:
    """Tabulated pages -> verbatim spectral n/k rows plus reference n."""
    gid, source_id = box["gid"], box["src"]
    spec, table = [], []
    for rows in blocks["nk"]:
        for wl, n, k in rows:
            spec.append({"glass_id": gid, "wavelength_um": wl, "n": n, "k": k,
                         "data_type": "literature (tabulated n,k)",
                         "measurement_form": form,
                         "source_id": source_id})
            table.append((wl, n, None))
    for rows in blocks["n"]:
        for wl, n, _k in rows:
            spec.append({"glass_id": gid, "wavelength_um": wl, "n": n, "k": None,
                         "data_type": "literature (tabulated n)",
                         "measurement_form": form,
                         "source_id": source_id})
            table.append((wl, n, None))
    for rows in blocks["k"]:
        for wl, k, _x in rows:
            spec.append({"glass_id": gid, "wavelength_um": wl, "n": None, "k": k,
                         "data_type": "literature (tabulated k)",
                         "measurement_form": form,
                         "source_id": source_id})
    return spec, table



def import_refractiveindex(root: Path, materials: dict,
                           access_date: str = "") -> dict:
    """Import every staged page under `root`.

    `materials` maps a chemical formula to (glass_id stem, display name,
    class).  Returns frames for glasses, properties, sellmeier, spectral n/k,
    sources, plus a list of human-readable issues.
    """
    root = Path(root)
    empty = pd.DataFrame()
    if not root.exists():
        return {"glasses": empty, "properties": empty, "sellmeier": empty,
                "spectral": empty, "sources": empty, "issues": []}

    glasses, props, sell, spec, srcs, issues = [], [], [], [], [], []
    for yml in sorted(root.glob("*/*.yml")):
        material = yml.parent.name
        if material not in materials:
            continue
        stem, display, mclass = materials[material]
        kind, page = (yml.stem.split("__", 1) if "__" in yml.stem
                      else ("", yml.stem))
        parsed = parse_ri_page(yml)
        tag = f"{material}/{page}"
        if parsed is None:
            issues.append(f"{tag}: no usable DATA block")
            continue
        b = parsed["blocks"]
        if not (b["formula"] or b["n"] or b["nk"] or b["k"]):
            issues.append(f"{tag}: every data block skipped ({b['skipped']})")
            continue

        key = f"{stem}-{page}".replace(" ", "").upper()
        gid = source_id = f"RII-{key}"
        doi, cite = _citation(parsed["references"])
        srcs.append({
            "source_id": source_id, "manufacturer": "refractiveindex.info",
            "source_name": f"{display}: {page} ({kind} data)",
            "source_url": (f"https://refractiveindex.info/?shelf=main"
                           f"&book={material}&page={page}"),
            "source_document": cite or f"refractiveindex.info page {page}",
            "publication_date": "", "access_date": access_date,
            "license": "CC0-1.0 (refractiveindex.info public domain)",
            "notes": (f"Optical constants for {display} via the "
                      f"refractiveindex.info database (public domain, CC0 1.0). "
                      f"Primary reference: {cite or 'see page'}"
                      + (f" DOI: {doi}" if doi else "")
                      + (f" | page note: {parsed['comments']}"
                         if parsed["comments"] else ""))})
        glasses.append({
            "glass_id": gid, "manufacturer_id": "RII", "glass_name": page,
            "manufacturer_code": page, "glass_family": display,
            "material_class": mclass, "status": "standard",
            "description": f"{display} ({material}). "
                           f"refractiveindex.info page '{page}'."})
        box = {"gid": gid, "src": source_id}
        sell_rows, form_props = _page_formulas(b, box)
        sell.extend(sell_rows)
        props.extend(form_props)
        spec_rows, table = _page_spectral(b, box, form=parsed.get("form", "unknown"))
        spec.extend(spec_rows)
        if table:
            lo, hi = _interp(0.0, table)[1]
            for nm, v, note in (
                    ("wl_min_um", lo, "Lowest tabulated wavelength."),
                    ("wl_max_um", hi, "Highest tabulated wavelength.")):
                r = _prop(gid, source_id, nm, v, "um", None, "literature", note)
                if r:
                    props.append(r)
            for wl in REFERENCE_UM:
                if lo and hi and not (lo <= wl <= hi):
                    continue
                val, _rng = _interp(wl, table)
                r = _prop(gid, source_id, "n_at_reference", val, "", wl,
                          "interpolated",
                          "Linear interpolation between tabulated samples near "
                          f"{wl} um from the cited reference.")
                if r:
                    props.append(r)
        for kindname, reason in b["skipped"]:
            issues.append(f"{tag}: skipped '{kindname}' ({reason}); "
                          "coefficients kept verbatim, never evaluated")
    return {"glasses": pd.DataFrame(glasses),
            "properties": pd.DataFrame(props),
            "sellmeier": pd.DataFrame(sell),
            "spectral": pd.DataFrame(spec),
            "sources": pd.DataFrame(srcs), "issues": issues}

    return doi, first

    B = coeffs[1:1 + n]
    C_um2 = [c * c for c in coeffs[1 + n:1 + 2 * n]]
    return sellmeier_n(lam_um, tuple(B), tuple(C_um2))
