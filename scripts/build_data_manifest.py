"""Write data/normalized/MANIFEST.json (data version, SHA-256 per file).

    python scripts/build_data_manifest.py          # write / refresh
    python scripts/build_data_manifest.py --check  # exit 1 if it is stale

Both merge scripts run this at the end. The data version changes only when a
file's content changes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glassmatch.manifest import stale_files, write_manifest  # noqa: E402

DATA = ROOT / "data" / "normalized"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        bad = stale_files(DATA)
        if bad:
            print("MANIFEST.json is stale for: " + ", ".join(bad))
            return 1
        print("MANIFEST.json matches the data")
        return 0
    m = write_manifest(DATA)
    print(f"data version {m['data_version']}: "
          + ", ".join(f"{k} {v}" for k, v in m["summary"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
