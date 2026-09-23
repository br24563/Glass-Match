"""Merge staged .agf imports into data/normalized (bulk catalogs stay uncommitted).

Usage (from repo root):
    python scripts/merge_agf.py --all
    python scripts/merge_agf.py --only SCHOTT-AGF-2025-06 OHARA-AGF-2026-05-29

Reads every staged .agf under data/staging (+ the SCHOTT file under
data/manufacturers/SCHOTT), parses via glassmatch.importers.agf, and merges
into data/normalized/*.csv with dated source_ids. Re-running is idempotent:
rows for the same source_id are replaced, never duplicated.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from glassmatch.importers.agf import import_agf

# file, manufacturer, source_id, download URL, license, notes
SOURCES = [
    ("schott glasses preferred and special June-2025-B.AGF", "SCHOTT",
     "SCHOTT-AGF-2025-06",
     "https://www.schott.com/en-us/products/optical-glass-p1000267/downloads",
     "redistribution-limited; .agf stays local, only normalized rows committed",
     "SCHOTT June 2025 preferred/inquiry/AR catalog; parsed locally."),
    ("OHARA_260529.AGF", "OHARA", "OHARA-AGF-2026-05-29",
     "https://www.ohara-gmbh.com/fileadmin/Dialog_Downloads/Zemax/OHARA_260529.AGF",
     "redistribution-limited; .agf stays local, only normalized rows committed",
     "OHARA catalog 2026-05-29; UTF-16 read; Herzberger-style rows flagged non-Sellmeier."),
]

# (file, manufacturer, source_id) — third-party mirror, vintage unknown
GITHUB_MIRROR = "https://github.com/nzhagen/zemaxglass/tree/master/src/ZemaxGlass/AGF_files"
GITHUB_FILES = [
    ("cdgm.agf", "CDGM"), ("corning.agf", "CORNING"), ("hikari.agf", "HIKARI"),
    ("hoya.agf", "HOYA"), ("lzos.agf", "LZOS"), ("nikon.agf", "NIKON"),
    ("sumita.agf", "SUMITA"), ("infrared.agf", "INFRARED"),
    ("lightpath.agf", "LIGHTPATH"), ("rpo.agf", "RPO"),
    ("umicore.agf", "UMICORE"), ("zeon.agf", "ZEON"),
    ("arton.agf", "ARTON"), ("topas.agf", "TOPAS"), ("archer.agf", "ARCHER"),
]

MATERIAL_CLASS = {"ZEON": "polymer", "ARTON": "polymer", "TOPAS": "polymer",
                  "ARCHER": "polymer", "INFRARED": "chalcogenide",
                  "LIGHTPATH": "chalcogenide", "UMICORE": "chalcogenide",
                  "RPO": "moldable"}

MANUFACTURER_NAMES = {
    "CORNING": "Corning Incorporated", "NIKON": "Nikon Corporation",
    "INFRARED": "Infrared glass (generic)", "LIGHTPATH": "LightPath Technologies",
    "RPO": "Rochester Precision Optics", "UMICORE": "Umicore",
    "ZEON": "Zeon Corporation", "ARTON": "JSR Arton", "TOPAS": "TOPAS COC",
    "ARCHER": "Archer OpTx", "LZOS": "LZOS / Shvabe", "HIKARI": "HIKARI Glass",
}


def _load_csv(path: Path, columns: list) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=columns)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", nargs="*", default=[])
    args = ap.parse_args()

    norm = ROOT / "data" / "normalized"
    glasses = _load_csv(norm / "glasses.csv",
                        ["glass_id", "manufacturer_id", "glass_name",
                         "manufacturer_code", "glass_family", "material_class",
                         "status", "description"])
    props = _load_csv(norm / "properties.csv",
                      ["glass_id", "property", "value", "unit",
                       "reference_wavelength_nm", "data_type", "source_id", "notes"])
    sell = _load_csv(norm / "sellmeier.csv",
                     ["glass_id", "formula", "wavelength_um", "B1", "B2", "B3",
                      "C1_um2", "C2_um2", "C3_um2", "source_id", "notes"])
    trans = _load_csv(norm / "transmission.csv",
                      ["glass_id", "wavelength_um", "transmission",
                       "thickness_mm", "data_type", "source_id", "notes"])
    sources = _load_csv(norm / "sources.csv",
                        ["source_id", "manufacturer", "source_name",
                         "source_url", "source_document", "publication_date",
                         "access_date", "license", "notes"])
    mfrs = _load_csv(norm.parent / "normalized" / "manufacturers.csv",
                     ["manufacturer_id", "name", "website", "notes"])

    jobs: list = []
    schott_dir = ROOT / "data" / "manufacturers" / "SCHOTT"
    ohara_staging = ROOT / "data" / "staging" / "OHARA_260529.AGF"
    for fname, mfr, sid, url, lic, note in SOURCES:
        cand = schott_dir / fname if mfr == "SCHOTT" else ohara_staging
        if cand.exists():
            jobs.append((cand, mfr, sid, url, lic, note))
    gh_dir = ROOT / "data" / "staging" / "github"
    for fname, mfr in GITHUB_FILES:
        cand = gh_dir / fname
        if cand.exists():
            sid = f"{mfr}-AGF-NZHAGEN-MIRROR"
            jobs.append((cand, mfr, sid, GITHUB_MIRROR,
                         "mirror-vintage-unknown; verify vs manufacturer catalog",
                         "Third-party mirror via nzhagen/zemaxglass; vintage unknown."))
    if args.only:
        jobs = [j for j in jobs if j[2] in args.only]
    if not jobs:
        print("No staged .agf files found. Nothing to merge.")
        return

    for path, mfr, sid, url, lic, note in jobs:
        mclass = MATERIAL_CLASS.get(mfr, "oxide_glass")
        g2, p2, s2, t2, iss = import_agf(path, mfr, sid, mclass)
        print(f"{sid}: {len(g2)} glasses, {len(p2)} props, {len(s2)} sell, "
              f"{len(t2)} trans, {len(iss)} issues "
              f"({len([i for i in iss if 'Sellmeier' in str(i.get('issue'))])} non-Sellmeier)")
        # Idempotent: drop prior rows from this source_id first.
        for frame, col in ((props, "source_id"), (sell, "source_id"), (trans, "source_id")):
            if not frame.empty and col in frame.columns:
                frame.drop(frame[frame[col] == sid].index, inplace=True)
        old_ids = set(g2["glass_id"]) if not g2.empty else set()
        for frame in (glasses, props, sell, trans):
            if not frame.empty and "glass_id" in frame.columns:
                frame.drop(frame[frame["glass_id"].isin(old_ids)].index, inplace=True)
        glasses = pd.concat([glasses, g2], ignore_index=True) if not g2.empty else glasses
        props = pd.concat([props, p2], ignore_index=True) if not p2.empty else props
        sell = pd.concat([sell, s2], ignore_index=True) if not s2.empty else sell
        trans = pd.concat([trans, t2], ignore_index=True) if not t2.empty else trans
        # Update this glass's canonical rows: merged source wins for nd/vd/etc.
        if not sources.empty:
            sources = sources[sources["source_id"] != sid]
        sources = pd.concat([sources, pd.DataFrame([{
            "source_id": sid, "manufacturer": mfr,
            "source_name": f"{mfr} Zemax catalog ({sid})",
            "source_url": url, "source_document": sid,
            "publication_date": "", "access_date": "2026-09-21",
            "license": lic, "notes": note}])], ignore_index=True)
        if mfr not in set(mfrs["manufacturer_id"]):
            mfrs = pd.concat([mfrs, pd.DataFrame([{
                "manufacturer_id": mfr,
                "name": MANUFACTURER_NAMES.get(mfr, mfr),
                "website": url, "notes": note}])], ignore_index=True)

    glasses.to_csv(norm / "glasses.csv", index=False)
    props.to_csv(norm / "properties.csv", index=False)
    sell.to_csv(norm / "sellmeier.csv", index=False)
    trans.to_csv(norm / "transmission.csv", index=False)
    sources.to_csv(norm / "sources.csv", index=False)
    mfrs.to_csv(norm / "manufacturers.csv", index=False)
    print(f"Merged {len(jobs)} source(s) into data/normalized.")


if __name__ == "__main__":
    main()

