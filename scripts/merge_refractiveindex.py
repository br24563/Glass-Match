"""Merge refractiveindex.info crystal pages into the GlassMatch database.

    python scripts/merge_refractiveindex.py [--dry-run]

The staged YAML under data/spectral/refractiveindex_info/ is CC0, so unlike
the manufacturer .agf catalogs it is committed to the repository and the
normalized rows derived from it are redistributed with it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glassmatch.importers.refractiveindex_yaml import import_refractiveindex
from scripts.fetch_refractiveindex import MATERIALS   # noqa: E402

STAGED = ROOT / "data" / "spectral" / "refractiveindex_info"
NORM = ROOT / "data" / "normalized"


def _upsert(path: Path, new: pd.DataFrame, key, sort_by=None) -> None:
    """Replace rows sharing `key` with new ones, keeping everything else.

    `key` is one column name or a list of them.  It has to build a genuine
    row key: taking `set(frame[list_of_cols].astype(str))` iterates *column
    names*, not values, so the existing rows were never replaced and the file
    accumulated duplicates.
    """
    if new is None or new.empty:
        return
    cols = [key] if isinstance(key, str) else list(key)
    if path.exists() and path.stat().st_size:
        old = pd.read_csv(path, encoding="utf-8")
        if all(c in old.columns for c in cols):
            new_keys = set(map(tuple, new[cols].astype(str).to_numpy()))
            old = old[[k not in new_keys for k in
                       map(tuple, old[cols].astype(str).to_numpy())]]
        merged = pd.concat([old, new], ignore_index=True, sort=False)
    else:
        merged = new
    if sort_by:
        merged = merged.sort_values(sort_by).reset_index(drop=True)
    merged.to_csv(path, index=False, encoding="utf-8")
    print(f"  {path.name}: {len(merged)} rows")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be imported, change nothing")
    args = ap.parse_args()

    if not STAGED.exists():
        print(f"no staged data at {STAGED}\n"
              "run: python scripts/fetch_refractiveindex.py")
        return 1

    out = import_refractiveindex(STAGED, MATERIALS,
                                 access_date=date.today().isoformat())
    print(f"pages imported : {len(out['glasses'])}")
    print(f"properties     : {len(out['properties'])}")
    print(f"sellmeier rows : {len(out['sellmeier'])}")
    print(f"spectral rows  : {len(out['spectral'])}")
    print(f"sources        : {len(out['sources'])}")
    skipped = [i for i in out["issues"] if "skipped" in i]
    print(f"skipped blocks : {len(skipped)}")
    for line in out["issues"][:6]:
        print(f"    {line}")
    if len(out["issues"]) > 6:
        print(f"    ... and {len(out['issues']) - 6} more")
    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    notes = ("Public-domain (CC0 1.0) compilation of literature optical "
             "constants. Not a manufacturer: each row is one published "
             "measurement of one material, cited individually.")
    _upsert(NORM / "manufacturers.csv", pd.DataFrame([{
        "manufacturer_id": "RII", "name": "refractiveindex.info",
        "website": "https://refractiveindex.info", "notes": notes}]),
        "manufacturer_id", ["manufacturer_id"])
    _upsert(NORM / "glasses.csv", out["glasses"], "glass_id",
            ["manufacturer_id", "glass_id"])
    _upsert(NORM / "properties.csv", out["properties"],
            ["glass_id", "property", "reference_wavelength_nm"],
            ["glass_id", "property", "reference_wavelength_nm"])
    _upsert(NORM / "sellmeier.csv", out["sellmeier"], "glass_id", ["glass_id"])
    _upsert(NORM / "sources.csv", out["sources"], "source_id", ["source_id"])
    if out["spectral"] is not None and not out["spectral"].empty:
        path = NORM / "spectral_nk.csv"
        new_ids = set(out["spectral"].glass_id.astype(str))
        if path.exists() and path.stat().st_size:
            old = pd.read_csv(path, encoding="utf-8")
            keep = old[~old.glass_id.astype(str).isin(new_ids)]
        else:
            keep = out["spectral"].iloc[0:0]
        merged = pd.concat([keep, out["spectral"]], ignore_index=True,
                           sort=False)
        merged.to_csv(path, index=False, encoding="utf-8")
        print(f"  spectral_nk.csv: {len(merged)} rows")
    print("\nmerged into data/normalized/")
    return 0


if __name__ == "__main__":
    sys.exit(main())