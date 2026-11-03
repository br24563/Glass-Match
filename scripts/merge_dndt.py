"""Import the manufacturers' measured dn/dT tables -> dn_dt_measured.csv.

    python scripts/merge_dndt.py

Reads the data workbooks staged for scripts/merge_agf.py (SCHOTT, OHARA,
HOYA, CDGM, HIKARI; see glassmatch/importers/dndt_xlsx.py), matches each
workbook glass to the stored glass of the same maker and name, and writes
one row per (glass, wavelength, temperature interval, relative/absolute).
Run after merge_agf.py; rebuilds MANIFEST.json.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glassmatch.importers.dndt_xlsx import import_dndt_xlsx, name_key  # noqa: E402
from scripts.merge_agf import CATALOGS, PROPERTY_SOURCES  # noqa: E402

NORM = ROOT / "data" / "normalized"
OUT = NORM / "dn_dt_measured.csv"


def _jobs():
    hikari = [j for j in CATALOGS if j.get("kind") == "hikari_xlsx"]
    return ([(j["mfr"], j["sid"], j["path"]) for j in PROPERTY_SOURCES]
            + [(j["mfr"], j["sid"], j["path"]) for j in hikari])


def _names(glasses: pd.DataFrame, maker: str) -> dict:
    """name key -> glass_id; where a maker lists a name twice (HIKARI's
    -MOLD variants), the glass whose id is MAKER-NAME wins."""
    g = glasses[glasses["manufacturer_id"] == maker]
    out = {}
    for gid, name in zip(g["glass_id"], g["glass_name"]):
        k = name_key(name)
        if k not in out or gid.upper() == f"{maker}-{name}".upper().replace(" ", "_"):
            out[k] = gid
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import warnings
    warnings.filterwarnings("ignore", module="openpyxl")
    glasses = pd.read_csv(NORM / "glasses.csv", dtype=str, keep_default_na=False)
    rows = []
    for maker, sid, path in _jobs():
        if not Path(path).exists():
            print(f"skip {sid}: {path} not staged")
            continue
        got, rep = import_dndt_xlsx(path, maker, sid, _names(glasses, maker))
        rows += got
        print(f"{sid}: {len(got)} values, {rep['glasses']} glass rows, "
              f"columns {rep['columns']}, {len(rep['unmatched'])} unmatched"
              + (f", {rep['implausible']} implausible" if rep["implausible"] else ""))
        if rep["unmatched"]:
            print("   unmatched:", ", ".join(rep["unmatched"][:20]))
    df = pd.DataFrame(rows)
    # A glass in two workbooks of one maker (OHARA S and special-order)
    # keeps the first; the order above is the maker's own precedence.
    df = df.drop_duplicates(["glass_id", "wavelength_um", "t_lo_c", "t_hi_c",
                             "basis"], keep="first")
    df = df.sort_values(["glass_id", "basis", "wavelength_um", "t_lo_c"])
    df.to_csv(OUT, index=False, lineterminator="\n")
    print(f"wrote {len(df)} rows for {df['glass_id'].nunique()} glasses")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_data_manifest.py")],
                   check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
