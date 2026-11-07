"""Verify IR catalog dispersion fits that have no catalog n_d to check against.

    python scripts/verify_ir_dispersion.py [--dry-run]

Runs after scripts/merge_agf.py and scripts/merge_refractiveindex.py (both
call it), because it needs the catalog rows and the refractiveindex.info
reference pages in data/normalized. For each catalog glass in
glassmatch.reference_check.REFERENCES it compares the fit with that
material's named room-temperature reference and, only on a pass, relabels the
archived row as a verified fit, recording the comparison in its notes. A fail
leaves the row archived and says why. Re-running is idempotent.

Second check, the maker's own numbers: CDGM's data workbook tabulates n at
2-14 um for its HWS chalcogenide glasses (sheet "infrared glass", four
decimals). A HWS fit that reproduces every tabulated value inside its .agf LD
range within MAKER_TOL is verified, valid over the tabulated span only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glassmatch.database import GlassDatabase  # noqa: E402
from glassmatch.importers.agf import verified_label  # noqa: E402
from glassmatch.reference_check import (MIN_COVERAGE, REFERENCES,  # noqa: E402
                                        TOLERANCE, compare_to_reference,
                                        verdict)
from glassmatch.spectra import ZEMAX_FORMULAS  # noqa: E402

NORM = ROOT / "data" / "normalized"
MARK = " Reference check:"
MAKER_MARK = " Maker table check:"
MAKER_TOL = 2e-4          # four printed decimals + fit residual
MAKER_MIN_SAMPLES = 5


def maker_ir_tables() -> dict:
    """glass name -> [(wavelength_um, n)] from CDGM's "infrared glass" sheet
    (staged workbook; {} when it is not staged)."""
    import re

    import openpyxl
    from scripts.merge_agf import PROPERTY_SOURCES
    job = next((j for j in PROPERTY_SOURCES if j["mfr"] == "CDGM"), None)
    if job is None or not Path(job["path"]).exists():
        return {}
    wb = openpyxl.load_workbook(job["path"], read_only=True, data_only=True)
    if "infrared glass" not in wb.sheetnames:
        return {}
    rows = list(wb["infrared glass"].iter_rows(values_only=True))
    head = rows[0]
    cols = {}
    for j, h in enumerate(head):
        m = re.fullmatch(r"n(\d+(?:\.\d+)?)μm", str(h or "").strip())
        if m:
            cols[j] = float(m.group(1))
    out = {}
    for r in rows[1:]:
        name = r[0]
        if not isinstance(name, str) or not name.strip():
            continue
        pts = [(wl, float(r[j])) for j, wl in cols.items()
               if j < len(r) and isinstance(r[j], (int, float))]
        if pts:
            out[name.strip()] = sorted(pts)
    return out, job["sid"]


def verify_against_maker(sell, db) -> int:
    """Verify archived CDGM HWS fits against CDGM's tabulated IR indices."""
    from glassmatch.spectra import coefficients_of, zemax_n
    got = maker_ir_tables()
    if not got:
        print("  maker IR tables: CDGM workbook not staged - skipped")
        return 0
    tables, sid = got
    changed = 0
    for name, pts in tables.items():
        gid = f"CDGM-{name}".upper().replace(" ", "_")
        hit = sell.index[sell["glass_id"] == gid]
        if len(hit) != 1:
            continue
        i = hit[0]
        formula = sell.at[i, "zemax_formula"]
        if formula != formula or str(sell.at[i, "formula"]).startswith(
                ("Sellmeier", "Herzberger", "Schott", "Conrady")) and \
                MAKER_MARK not in str(sell.at[i, "notes"]):
            continue                      # verified another way already
        formula = int(formula)
        coeffs = coefficients_of(sell.loc[i].to_dict())
        lo_ld = db.property_value(gid, "wl_min_um")
        hi_ld = db.property_value(gid, "wl_max_um")
        inside = [(w, n) for w, n in pts
                  if (lo_ld is None or w >= lo_ld - 1e-9)
                  and (hi_ld is None or w <= hi_ld + 1e-9)]
        diffs = [abs(zemax_n(formula, coeffs, w) - n) for w, n in inside]
        notes = str(sell.at[i, "notes"]).split(MAKER_MARK)[0].split(MARK)[0]
        if len(inside) < MAKER_MIN_SAMPLES or not diffs or any(d != d for d in diffs):
            detail = (f"{len(inside)} of CDGM's tabulated IR indices fall inside "
                      f"the fit's LD range ({MAKER_MIN_SAMPLES} needed)")
            ok = False
        else:
            mx = max(diffs)
            lo, hi = inside[0][0], inside[-1][0]
            detail = (f"max |n - n_CDGM| = {mx:.5f} at {len(inside)} tabulated "
                      f"wavelengths {lo:g}-{hi:g} um ({sid}, sheet 'infrared "
                      f"glass'); tolerance {MAKER_TOL}")
            ok = mx <= MAKER_TOL
        if ok:
            label = verified_label(formula, None)
            note = (f"{MAKER_MARK} catalog gives no n(d), so the fit was verified "
                    f"against the maker's own tabulated IR indices: {detail}. "
                    f"Valid over the tabulated span {lo:g}-{hi:g} um only.")
            rng = f"{lo:g}-{hi:g}"
        else:
            fname = ZEMAX_FORMULAS.get(formula, f"formula {formula}")
            label = (f"Non-dispersable ({fname} CD with no catalog n(d); failed "
                     "the maker table check) - archived, never evaluated")
            note = f"{MAKER_MARK} FAILED - {detail}."
            rng = ""
        print(f"  {gid}: {'verified' if ok else 'archived'} - {detail}")
        if (sell.at[i, "formula"] != label or str(sell.at[i, "notes"]) != notes + note
                or str(sell.at[i, "wavelength_um"] or "") != rng):
            sell.at[i, "formula"] = label
            sell.at[i, "notes"] = notes + note
            sell.at[i, "wavelength_um"] = rng
            changed += 1
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    path = NORM / "sellmeier.csv"
    sell = pd.read_csv(path, float_precision="round_trip")
    db = GlassDatabase.load(NORM)
    changed = 0
    for gid, ref in REFERENCES.items():
        hit = sell.index[sell["glass_id"] == gid]
        if len(hit) != 1 or db.sellmeier_for(ref, sellmeier_only=False) is None \
                and db.spectral_nk_for(ref) is None:
            print(f"  {gid}: skipped (catalog row or reference {ref} missing)")
            continue
        i = hit[0]
        formula = sell.at[i, "zemax_formula"]
        if formula != formula:
            print(f"  {gid}: skipped (no Zemax formula recorded)")
            continue
        formula = int(formula)
        cmp = compare_to_reference(db, gid, ref)
        ok = verdict(cmp)
        notes = str(sell.at[i, "notes"]).split(MARK)[0]
        if cmp is None or cmp["max_dn"] is None:
            detail = f"{ref} has no data inside this fit's range"
        else:
            detail = (f"max |n - n_ref| = {cmp['max_dn']:.4f} against {ref} "
                      f"(room-temperature bulk, refractiveindex.info) over "
                      f"{cmp['lo']:.2f}-{cmp['hi']:.2f} um, {cmp['n']} samples, "
                      f"{cmp['coverage']:.0%} of the stated range; tolerance "
                      f"{TOLERANCE}, minimum coverage {MIN_COVERAGE:.0%}")
        fname = ZEMAX_FORMULAS.get(formula, f"formula {formula}")
        if ok:
            terms = sell.at[i, "n_terms"] if "n_terms" in sell.columns else None
            terms = int(terms) if terms == terms and terms is not None else None
            if terms is None and formula in (2, 6, 11):
                from glassmatch.spectra import active_pairs, coefficients_of
                terms = len(active_pairs(coefficients_of(sell.loc[i].to_dict())))
                sell.at[i, "n_terms"] = terms
            label = verified_label(formula, terms)
            note = (f"{MARK} catalog gives no n(d) (Zemax placeholder), so the "
                    f"fit was verified against an independent measurement "
                    f"instead: {detail}.")
        else:
            label = (f"Non-dispersable ({fname} CD with no catalog n(d); "
                     f"failed reference check against {ref}) - archived, never "
                     "evaluated")
            note = f"{MARK} FAILED - {detail}."
        print(f"  {gid}: {'verified' if ok else 'archived'} - {detail}")
        if sell.at[i, "formula"] != label or str(sell.at[i, "notes"]) != notes + note:
            sell.at[i, "formula"] = label
            sell.at[i, "notes"] = notes + note
            changed += 1
    changed += verify_against_maker(sell, db)
    if args.dry_run:
        print(f"--dry-run: {changed} row(s) would change")
        return 0
    if changed:
        if "zemax_formula" in sell.columns:
            sell["zemax_formula"] = pd.to_numeric(
                sell["zemax_formula"], errors="coerce").astype("Int64")
        if "rii_formula" in sell.columns:
            sell["rii_formula"] = pd.to_numeric(
                sell["rii_formula"], errors="coerce").astype("Int64")
        sell.to_csv(path, index=False)
    print(f"verify_ir_dispersion: {changed} row(s) updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
