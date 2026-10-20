"""Verify IR catalog dispersion fits that have no catalog n_d to check against.

    python scripts/verify_ir_dispersion.py [--dry-run]

Runs after scripts/merge_agf.py and scripts/merge_refractiveindex.py (both
call it), because it needs the catalog rows and the refractiveindex.info
reference pages in data/normalized. For each catalog glass in
glassmatch.reference_check.REFERENCES it compares the fit with that
material's named room-temperature reference and, only on a pass, relabels the
archived row as a verified fit, recording the comparison in its notes. A fail
leaves the row archived and says why. Re-running is idempotent.
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
