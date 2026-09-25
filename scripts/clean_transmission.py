"""One-off migration: quarantine conflicting transmission samples.

Some raw .agf catalogs list the same wavelength twice with different
transmittance values - a data-entry artifact in some catalogs (``1E-6`` beside
a real 0.99 reading), a genuine disagreement in others. Both rows are kept in
the database today, and :func:`glassmatch.spectra.band_stats` excludes the
disputed wavelength at query time.

This script moves those rows out of ``transmission.csv`` into
``transmission_conflicts.csv`` so the audit trail lives in the repository
rather than in a runtime check. It never picks a winner: every distinct value
is preserved, and the file is rewritten only when something actually changes.

Usage:
    python scripts/clean_transmission.py [--dry-run]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glassmatch.validation import split_transmission_conflicts  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "normalized"
TRANS = DATA_DIR / "transmission.csv"
CONFLICTS = DATA_DIR / "transmission_conflicts.csv"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()

    if not TRANS.exists():
        print(f"error: {TRANS} not found")
        return 1
    t = pd.read_csv(TRANS)
    before = len(t)
    clean, conflicts, dropped = split_transmission_conflicts(t)

    print(f"transmission rows: {before}")
    print(f"conflicting keys : {len(conflicts)}")
    print(f"rows quarantined: {len(dropped)}")
    print(f"rows remaining   : {len(clean)}")
    if conflicts.empty:
        print("nothing to clean - already consistent")
        return 0

    print("\nby source:")
    for src, n in conflicts["source_ids"].value_counts().items():
        print(f"  {src}: {n}")
    print("\nlargest spreads:")
    worst = conflicts.reindex(conflicts["spread"].sort_values(ascending=False).index)
    for _, r in worst.head(10).iterrows():
        print(f"  {r['glass_id']:<24} {r['wavelength_um']:>6} um  "
              f"values={r['values']:<24} spread={r['spread']}")

    if args.dry_run:
        print("\n--dry-run: no files written")
        return 0

    clean.to_csv(TRANS, index=False)
    if CONFLICTS.exists():
        prior = pd.read_csv(CONFLICTS)
        conflicts = (pd.concat([prior, conflicts], ignore_index=True)
                     .drop_duplicates(subset=["glass_id", "wavelength_um",
                                              "thickness_mm"]))
    conflicts.to_csv(CONFLICTS, index=False)
    print(f"\nwrote {TRANS.name} ({len(clean)} rows)")
    print(f"wrote {CONFLICTS.name} ({len(conflicts)} keys, all values preserved)")
    print("These samples are excluded from band statistics. Review each key "
          "against its source catalog before restoring any value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
