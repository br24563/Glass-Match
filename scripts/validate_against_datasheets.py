"""Cross-check every verified dispersion fit against the makers' datasheets.

    python scripts/validate_against_datasheets.py

Reads the manufacturer Excel workbooks staged for scripts/merge_agf.py
(PROPERTY_SOURCES), compares the database's fit for each glass with the
catalog index the workbook tabulates at every spectral line, and writes:

* docs/validation/datasheet_crosscheck.csv - one row per glass: lines
  checked, max and rms |n_fit - n_catalog|, the worst line. Residuals only;
  no manufacturer values.
* docs/VALIDATION.md - the summary, regenerated between its markers.
* data/validation/reference_indices.csv - a small, fixed sample of catalog
  index values (a few glasses per workbook, plus each workbook's worst case)
  that tests/test_datasheet_validation.py checks in CI, where the workbooks
  themselves are not available.

The workbooks are redistribution-limited and stay in the gitignored
data/staging/; re-run this after any merge.
"""
from __future__ import annotations

import sys
import warnings
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from glassmatch.database import load_default_database  # noqa: E402
from glassmatch.datasheet_check import (AGREE_TOL, crosscheck,  # noqa: E402
                                        read_index_tables)
from glassmatch.importers.maker_xlsx import name_key  # noqa: E402
from scripts.merge_agf import PROPERTY_SOURCES  # noqa: E402

REPORT = ROOT / "docs" / "validation" / "datasheet_crosscheck.csv"
SUMMARY = ROOT / "docs" / "VALIDATION.md"
SAMPLE = ROOT / "data" / "validation" / "reference_indices.csv"
BEGIN, END = "<!-- crosscheck:begin -->", "<!-- crosscheck:end -->"
PER_WORKBOOK = 8


def main() -> int:
    warnings.filterwarnings("ignore", module="openpyxl")
    db = load_default_database()
    props, glasses = db.properties, db.glasses
    reports, sample = [], []
    for job in PROPERTY_SOURCES:
        if not Path(job["path"]).exists():
            print(f"{job['sid']}: workbook not staged, skipped")
            continue
        tables = read_index_tables(job["path"], job["layout"])
        ids = set(props.loc[props["source_id"] == job["agf"], "glass_id"])
        g = glasses[glasses["glass_id"].isin(ids)]
        names = {name_key(n): gid for n, gid in zip(g["glass_name"],
                                                     g["glass_id"])}
        rep = crosscheck(db, tables, names, job["sid"], job["mfr"])
        if rep.empty:
            continue
        reports.append(rep)
        print(f"{job['sid']}: {len(rep)} glasses, {int(rep['agrees'].sum())} "
              f"within {AGREE_TOL:g}, worst {rep['max_abs_dn'].max():.2e}")
        # Fixed sample: evenly spaced by glass_id, plus the worst case.
        ordered = rep.sort_values("glass_id").reset_index(drop=True)
        step = max(1, len(ordered) // PER_WORKBOOK)
        picks = set(ordered["glass_id"].iloc[::step][:PER_WORKBOOK])
        picks.add(rep.loc[rep["max_abs_dn"].idxmax(), "glass_id"])
        inv = {gid: key for key, gid in names.items()}
        for gid in sorted(picks):
            lo_hi = rep.loc[rep["glass_id"] == gid, "range_um"].iloc[0]
            lo, hi = (float(x) for x in lo_hi.split("-"))
            for wl, n in sorted(tables[inv[gid]].items()):
                if lo - 1e-6 <= wl <= hi + 1e-6:
                    sample.append({"glass_id": gid, "wavelength_um": wl,
                                   "n_catalog": n, "source_id": job["sid"]})
    if not reports:
        print("no workbooks staged - nothing written")
        return 1
    rep = pd.concat(reports, ignore_index=True).sort_values(
        ["maker", "glass_id", "datasheet"])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    rep.to_csv(REPORT, index=False, float_format="%.3g")
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(sample).to_csv(SAMPLE, index=False)
    _write_summary(rep)
    print(f"wrote {REPORT.relative_to(ROOT)}, {SAMPLE.relative_to(ROOT)} "
          f"({len(sample)} values), {SUMMARY.relative_to(ROOT)}")
    return 0


def _write_summary(rep: pd.DataFrame) -> None:
    by = rep.groupby("datasheet").agg(
        maker=("maker", "first"), glasses=("glass_id", "count"),
        lines=("lines_checked", "median"), agree=("agrees", "sum"),
        median=("max_abs_dn", "median"), worst=("max_abs_dn", "max"))
    lines = [BEGIN, "",
             f"Generated {date.today().isoformat()} by "
             "`scripts/validate_against_datasheets.py`.", "",
             "| Datasheet | Maker | Glasses | Lines per glass | "
             f"Within {AGREE_TOL:g} | Median max \\|Δn\\| | Worst \\|Δn\\| |",
             "|---|---|---|---|---|---|---|"]
    for sid, r in by.iterrows():
        lines.append(f"| {sid} | {r['maker']} | {r['glasses']} | "
                     f"{r['lines']:.0f} | {int(r['agree'])} | "
                     f"{r['median']:.1e} | {r['worst']:.1e} |")
    tot = rep["agrees"].sum()
    lines += ["", f"**{len(rep):,} glass/datasheet pairs, {int(tot):,} "
              f"({tot / len(rep):.1%}) within {AGREE_TOL:g} at every line; "
              f"worst {rep['max_abs_dn'].max():.1e}.**", "", END]
    text = SUMMARY.read_text(encoding="utf-8") if SUMMARY.exists() else ""
    block = "\n".join(lines)
    if BEGIN in text and END in text:
        text = text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]
    else:
        text = text + "\n" + block + "\n"
    SUMMARY.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
