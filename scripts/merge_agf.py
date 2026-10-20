"""Merge staged manufacturer catalogs into data/normalized (bulk files stay uncommitted).

Usage (from repo root):
    python scripts/merge_agf.py --all
    python scripts/merge_agf.py --only SCHOTT-AGF-2025-06 OHARA-AGF-2026-05-29

Reads every staged catalog - the manufacturers' own .agf files (and HIKARI's
Excel workbook) under data/staging/official, the SCHOTT and OHARA files, and
the third-party nzhagen/zemaxglass mirror under data/staging/github for makers
that publish nothing current - and merges them into data/normalized/*.csv
with dated source_ids. Re-running is idempotent: rows for the same source_id
are replaced, never duplicated.

Where a manufacturer's own catalog exists it replaces the mirror. Glasses that
only the mirror still lists (renamed or long-discontinued types) are kept, so
an old design can still be looked up, but are marked obsolete and labelled as
mirror data absent from the current catalog.

Transmission samples are merged unfiltered and then passed through
scripts/clean_transmission.py, which collapses identical duplicates and
quarantines conflicting ones into the audit ledgers; IR fits with no catalog
n_d are then re-checked by scripts/verify_ir_dispersion.py.
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from glassmatch.importers.agf import import_agf
from glassmatch.importers.hikari_xlsx import import_hikari_xlsx

STAGING = ROOT / "data" / "staging"
OFFICIAL = STAGING / "official"
LIMITED = "redistribution-limited; catalog file stays local, only normalized rows committed"
GITHUB_MIRROR = "https://github.com/nzhagen/zemaxglass/tree/master/src/ZemaxGlass/AGF_files"
MIRROR_LICENSE = "mirror-vintage-unknown; verify vs manufacturer catalog"
MIRROR_NOTE = "Third-party mirror via nzhagen/zemaxglass; vintage unknown."

# Manufacturers' own catalogs. `supersedes` names the mirror file(s) whose
# glasses this catalog replaces; `kind` selects the importer.
CATALOGS = [
    dict(sid="SCHOTT-AGF-2025-06", mfr="SCHOTT", kind="agf",
         path=ROOT / "data" / "manufacturers" / "SCHOTT"
         / "schott glasses preferred and special June-2025-B.AGF",
         url="https://www.schott.com/en-us/products/optical-glass-p1000267/downloads",
         published="2025-06", accessed="2026-09-21",
         note="SCHOTT June 2025 preferred/inquiry/AR catalog; parsed locally. "
              "Re-checked 2026-10-20: SCHOTT's current download is byte-identical."),
    dict(sid="OHARA-AGF-2026-05-29", mfr="OHARA", kind="agf",
         path=STAGING / "OHARA_260529.AGF",
         url="https://www.ohara-gmbh.com/fileadmin/Dialog_Downloads/Zemax/OHARA_260529.AGF",
         published="2026-05-29", accessed="2026-09-21",
         note="OHARA catalog 2026-05-29; UTF-16 read; 245 Sellmeier-1 + 188 "
              "Schott-formula rows."),
    dict(sid="HOYA-AGF-2026-07-07", mfr="HOYA", kind="agf",
         path=OFFICIAL / "hoya" / "HOYA20260707_include_obsolete.agf",
         url="https://www.hoya-opticalworld.com/english/datadownload/",
         published="2026-07-07", accessed="2026-10-20", supersedes=["hoya.agf"],
         note="HOYA Zemax catalog updated 2026-07-07, the edition that "
              "includes obsolete glasses (HOYA20260707_include_obsolete.agf)."),
    dict(sid="CDGM-AGF-2026-09", mfr="CDGM", kind="agf",
         path=OFFICIAL / "cdgm" / "CDGM-ZEMAX202609.AGF",
         url="https://www.cdgmgd.com/go.htm?k=ge_lei_xia_zai&url=downList",
         published="2026-09", accessed="2026-10-20", supersedes=["cdgm.agf"],
         note="CDGM Zemax catalog CDGM-ZEMAX202609.AGF from cdgmgd.com."),
    dict(sid="SUMITA-AGF-2026-08-26", mfr="SUMITA", kind="agf",
         path=OFFICIAL / "sumita" / "SUMITA_20260826.agf",
         url="https://www.sumita-opt.co.jp/en/download/",
         published="2026-08-26", accessed="2026-10-20", supersedes=["sumita.agf"],
         note="SUMITA Zemax catalog 2026-08-26, all glasses including "
              "discontinued ones."),
    dict(sid="HIKARI-XLSX-2025-06-01", mfr="HIKARI", kind="hikari_xlsx",
         path=OFFICIAL / "hikari" / "HIKARI_ALL_Catalog_Data.xlsx",
         url="https://www.hikari-g.co.jp/optical_glass/catalog/",
         published="2025-06-01", accessed="2026-10-20",
         supersedes=["hikari.agf"],
         note="HIKARI All Catalog Data workbook, catalog 2025-06-01: the "
              "current HIKARI line (HIKARI publishes no Zemax file)."),
    # Nikon's own distribution of the HIKARI line plus Nikon's synthetic
    # silica / CaF2 (NIFS, NICF). Glasses in the 2025 HIKARI workbook come
    # from there; everything else here is HIKARI stock no longer catalogued.
    dict(sid="NIKON-HIKARI-AGF-2019-11", mfr="HIKARI", kind="agf",
         path=OFFICIAL / "nikon" / "NIKON-HIKARI_201911.AGF",
         url="https://www.nikon.com/business/components/downloads/",
         published="2019-11", accessed="2026-10-20",
         supersedes=["nikon.agf", "hikari.agf"],
         nikon_own=r"^(NIFS|NICF)", after="HIKARI-XLSX-2025-06-01",
         note="Nikon Zemax data NIKON-HIKARI_201911.AGF (last updated Nov "
              "2019): HIKARI glasses absent from the 2025 HIKARI catalog, "
              "and Nikon's NIFS/NICF materials."),
]

# Makers with no current public catalog: the mirror stays their only source.
GITHUB_FILES = [
    ("corning.agf", "CORNING"), ("lzos.agf", "LZOS"),
    ("infrared.agf", "INFRARED"), ("lightpath.agf", "LIGHTPATH"),
    ("rpo.agf", "RPO"), ("umicore.agf", "UMICORE"), ("zeon.agf", "ZEON"),
    ("arton.agf", "ARTON"), ("topas.agf", "TOPAS"), ("archer.agf", "ARCHER"),
]
# Mirror files a manufacturer catalog has replaced, and their maker.
SUPERSEDED_MIRRORS = {"hoya.agf": "HOYA", "cdgm.agf": "CDGM",
                      "sumita.agf": "SUMITA", "nikon.agf": "NIKON",
                      "hikari.agf": "HIKARI"}

# Catalog lines that are not oxide glass despite their maker's default:
# CDGM's HWS series are chalcogenide IR glasses with no visible-band n_d.
CLASS_OVERRIDES = [("CDGM", r"^HWS", "chalcogenide")]

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
MANUFACTURER_NOTES = {
    "HIKARI": ("HIKARI Glass Co., Ltd. (Nikon group). Current line from the "
               "2025-06-01 catalog workbook; discontinued types from Nikon's "
               "2019 Zemax data.", "https://www.hikari-g.co.jp/"),
    "NIKON": ("Nikon Corporation optical materials (NIFS synthetic silica, "
              "NICF calcium fluoride), from Nikon's 2019 Zemax data.",
              "https://www.nikon.com/business/components/"),
}
# Official sites, where the manufacturers table carried a wrong or mirror URL.
WEBSITES = {"SUMITA": "https://www.sumita-opt.co.jp/en/",
            "HOYA": "https://www.hoya-opticalworld.com/english/",
            "CDGM": "https://www.cdgmgd.com/",
            "OHARA": "https://www.ohara-gmbh.com/"}
XREF_RELATION = "similar glass (manufacturer cross-reference)"


def _load_csv(path: Path, columns: list) -> pd.DataFrame:
    if path.exists():
        # round_trip: the default parser can move the last digit of a float,
        # so rows this merge never touches would otherwise churn on rewrite.
        return pd.read_csv(path, float_precision="round_trip")
    return pd.DataFrame(columns=columns)


def _all_names(path) -> list:
    """Every NM glass name in an .agf, before any filtering."""
    from glassmatch.importers.agf import read_agf_file
    return [ln.split()[1] for ln in read_agf_file(path).splitlines()
            if ln.startswith("NM ") and len(ln.split()) > 1]


def _rename_ids(frames, pattern, old, new):
    """Move glasses whose name matches `pattern` from maker `old` to `new`."""
    g = frames[0]
    hit = g["glass_name"].astype(str).str.match(pattern)
    mapping = {gid: f"{new}-{gid[len(old) + 1:]}" for gid in g.loc[hit, "glass_id"]}
    g.loc[hit, "manufacturer_id"] = new
    for f in frames:
        if not f.empty and "glass_id" in f.columns:
            f["glass_id"] = f["glass_id"].replace(mapping)
    return mapping


def _mark(g, mask, note):
    g.loc[mask, "status"] = "obsolete"
    g.loc[mask, "description"] = g.loc[mask, "description"].astype(str) + " " + note
    return int(mask.sum())


def _import(job, current_names):
    """Run one catalog job -> (glasses, props, sell, trans, issues, xrefs)."""
    if job["kind"] == "hikari_xlsx":
        g, p, s, t, xrefs, iss = import_hikari_xlsx(job["path"], job["sid"],
                                                     job["mfr"])
        return g, p, s, t, iss, xrefs
    mclass = MATERIAL_CLASS.get(job["mfr"], "oxide_glass")
    g, p, s, t, iss = import_agf(job["path"], job["mfr"], job["sid"], mclass,
                                 quarantine=False)
    frames = [g, p, s, t]
    if job.get("after"):
        # Glasses the newer catalog already supplies are taken from there.
        keep_names = set(current_names.get(job["after"], set()))
        drop = set(g.loc[g["glass_name"].isin(keep_names), "glass_id"])
        frames = [f[~f["glass_id"].isin(drop)].copy() if not f.empty else f
                  for f in frames]
        g = frames[0]
        n = _mark(g, (g["status"] != "obsolete"),
                  f"Not in the current catalog ({job['after']}); last listed "
                  f"in {job['sid']}.")
        print(f"  {job['sid']}: {len(drop)} glasses taken from {job['after']}, "
              f"{n} more marked obsolete (absent from it)")
    if job.get("nikon_own"):
        moved = _rename_ids(frames, job["nikon_own"], job["mfr"], "NIKON")
        print(f"  {job['sid']}: {len(moved)} Nikon-made materials kept under NIKON")
    return (*frames, iss, [])


def _legacy_from_mirror(fname, mfr, official_names):
    """Glasses only the superseded mirror lists: kept, but marked obsolete."""
    path = STAGING / "github" / fname
    if not path.exists():
        return None
    sid = f"{mfr}-AGF-NZHAGEN-MIRROR"
    g, p, s, t, iss = import_agf(path, mfr, sid,
                                 MATERIAL_CLASS.get(mfr, "oxide_glass"),
                                 quarantine=False)
    if g.empty:
        return None
    keep = set(g.loc[~g["glass_name"].isin(official_names), "glass_id"])
    frames = [f[f["glass_id"].isin(keep)].copy() if not f.empty else f
              for f in (g, p, s, t)]
    if frames[0].empty:
        return None
    _mark(frames[0], frames[0]["glass_id"].notna(),
          f"Not in {mfr}'s current catalog; data from a third-party mirror of "
          "unknown vintage - verify before use.")
    return sid, frames


def _replace(tables, sid, new_frames, purge_ids=()):
    glasses, props, sell, trans = tables
    for frame in (props, sell, trans):
        if not frame.empty and "source_id" in frame.columns:
            frame.drop(frame[frame["source_id"] == sid].index, inplace=True)
    ids = set(purge_ids)
    if not new_frames[0].empty:
        ids |= set(new_frames[0]["glass_id"])
    for frame in (glasses, props, sell, trans):
        if not frame.empty and "glass_id" in frame.columns:
            frame.drop(frame[frame["glass_id"].isin(ids)].index, inplace=True)
    out = []
    for old, new in zip((glasses, props, sell, trans), new_frames):
        out.append(pd.concat([old, new], ignore_index=True) if not new.empty
                   else old)
    return out


def _source_row(sid, mfr, url, doc, published, accessed, lic, note):
    return {"source_id": sid, "manufacturer": mfr,
            "source_name": f"{mfr} catalog ({sid})", "source_url": url,
            "source_document": doc, "publication_date": published,
            "access_date": accessed, "license": lic, "notes": note}


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
                     ["glass_id", "formula", "zemax_formula", "coefficients",
                      "wavelength_um", "B1", "B2", "B3", "C1_um2", "C2_um2",
                      "C3_um2", "source_id", "notes"])
    trans = _load_csv(norm / "transmission.csv",
                      ["glass_id", "wavelength_um", "transmission",
                       "thickness_mm", "data_type", "source_id", "notes"])
    sources = _load_csv(norm / "sources.csv",
                        ["source_id", "manufacturer", "source_name",
                         "source_url", "source_document", "publication_date",
                         "access_date", "license", "notes"])
    mfrs = _load_csv(norm / "manufacturers.csv",
                     ["manufacturer_id", "name", "website", "notes"])
    equiv = _load_csv(norm / "equivalents.csv",
                      ["glass_id_a", "glass_id_b", "relation", "source_id",
                       "notes"])

    jobs = [j for j in CATALOGS if Path(j["path"]).exists()]
    mirrors = [(f, m) for f, m in GITHUB_FILES
               if (STAGING / "github" / f).exists()]
    if args.only:
        jobs = [j for j in jobs if j["sid"] in args.only]
        mirrors = [(f, m) for f, m in mirrors
                   if f"{m}-AGF-NZHAGEN-MIRROR" in args.only]
    if not jobs and not mirrors:
        print("No staged catalogs found. Nothing to merge.")
        return

    tables = [glasses, props, sell, trans]
    new_sources, xref_rows = [], []
    current_names: dict = {}
    superseded: dict = {}
    for job in jobs:
        g2, p2, s2, t2, iss, xrefs = _import(job, current_names)
        current_names[job["sid"]] = set(g2["glass_name"]) if not g2.empty else set()
        for mfr, pattern, mclass in CLASS_OVERRIDES:
            if job["mfr"] == mfr and not g2.empty:
                hit = g2["glass_name"].astype(str).str.match(pattern)
                g2.loc[hit, "material_class"] = mclass
        # Every name this catalog covers - including those it defers to the
        # newer catalog named in `after` - retires the mirror's copy.
        covered = current_names[job["sid"]] | current_names.get(
            job.get("after", ""), set())
        if job.get("after"):
            covered |= set(_all_names(job["path"]))
        for f in job.get("supersedes", []):
            superseded.setdefault(f, set()).update(covered)
        n_arch = int((~s2["formula"].astype(str).str.startswith(
            "Non-dispersable")).sum()) if not s2.empty else 0
        print(f"{job['sid']}: {len(g2)} glasses, {len(p2)} props, {len(s2)} "
              f"dispersion rows ({n_arch} verified), {len(t2)} trans, "
              f"{len(iss)} issues")
        tables = _replace(tables, job["sid"], [g2, p2, s2, t2])
        new_sources.append(_source_row(job["sid"], job["mfr"], job["url"],
                                       Path(job["path"]).name, job["published"],
                                       job["accessed"], LIMITED, job["note"]))
        for gid, maker, name in xrefs:
            xref_rows.append((gid, maker, name, job["sid"]))

    # Superseded mirrors: remove their rows, keep only mirror-only glasses.
    if not args.only:
        for fname, mfr in SUPERSEDED_MIRRORS.items():
            sid = f"{mfr}-AGF-NZHAGEN-MIRROR"
            g0 = tables[0]
            old_ids = set()
            for frame in tables[1:]:
                if not frame.empty:
                    old_ids |= set(frame.loc[frame["source_id"] == sid, "glass_id"])
            old_ids |= set(g0.loc[g0["description"].astype(str).str.contains(
                re.escape(f"Imported from {sid}."), na=False), "glass_id"])
            legacy = _legacy_from_mirror(fname, mfr, superseded.get(fname, set()))
            frames = legacy[1] if legacy else [pd.DataFrame()] * 4
            tables = _replace(tables, sid, frames, purge_ids=old_ids)
            kept = len(frames[0])
            print(f"{sid}: superseded - {len(old_ids)} mirror glasses removed, "
                  f"{kept} mirror-only glasses kept as obsolete")
            sources = sources[sources["source_id"] != sid]
            if kept:
                new_sources.append(_source_row(
                    sid, mfr, GITHUB_MIRROR, sid, "", "2026-09-21",
                    MIRROR_LICENSE,
                    MIRROR_NOTE + " Superseded by the manufacturer's own "
                    "catalog; only glasses it no longer lists are kept."))
    for fname, mfr in mirrors:
        sid = f"{mfr}-AGF-NZHAGEN-MIRROR"
        g2, p2, s2, t2, iss = import_agf(STAGING / "github" / fname, mfr, sid,
                                         MATERIAL_CLASS.get(mfr, "oxide_glass"),
                                         quarantine=False)
        print(f"{sid}: {len(g2)} glasses (mirror, vintage unknown)")
        tables = _replace(tables, sid, [g2, p2, s2, t2])
        new_sources.append(_source_row(sid, mfr, GITHUB_MIRROR, sid, "",
                                       "2026-09-21", MIRROR_LICENSE, MIRROR_NOTE))

    glasses, props, sell, trans = tables
    for row in new_sources:
        sources = sources[sources["source_id"] != row["source_id"]]
    sources = pd.concat([sources, pd.DataFrame(new_sources)], ignore_index=True)
    used = set(props["source_id"]) | set(sell["source_id"]) | set(trans["source_id"])
    if not equiv.empty:
        used |= set(equiv["source_id"])
    dangling = [s for s in sources["source_id"]
                if str(s).endswith("-AGF-NZHAGEN-MIRROR") and s not in used]
    sources = sources[~sources["source_id"].isin(dangling)]

    # Manufacturer cross-references (HIKARI's "similar glass type" columns),
    # kept only where both glasses exist. Replaced wholesale per source.
    if xref_rows:
        ids = set(glasses["glass_id"])
        srcs = {s for *_, s in xref_rows}
        equiv = equiv[~equiv["source_id"].isin(srcs)]
        rows = []
        for gid, maker, name, sid in xref_rows:
            other = f"{maker}-{name}".upper().replace(" ", "_")
            if gid in ids and other in ids:
                rows.append({"glass_id_a": gid, "glass_id_b": other,
                             "relation": XREF_RELATION, "source_id": sid,
                             "notes": "Listed by the manufacturer as a similar "
                                      "glass type; verify melt data before "
                                      "substitution."})
        print(f"cross-references: {len(rows)} of {len(xref_rows)} resolved to "
              "glasses in the database")
        equiv = pd.concat([equiv, pd.DataFrame(rows)], ignore_index=True)

    present = set(glasses["manufacturer_id"])
    for mfr in sorted(present - set(mfrs["manufacturer_id"])):
        mfrs = pd.concat([mfrs, pd.DataFrame([{
            "manufacturer_id": mfr, "name": MANUFACTURER_NAMES.get(mfr, mfr),
            "website": "", "notes": ""}])], ignore_index=True)
    for mfr, (note, site) in MANUFACTURER_NOTES.items():
        mfrs.loc[mfrs["manufacturer_id"] == mfr, ["notes", "website"]] = [note, site]
    for mfr, site in WEBSITES.items():
        mfrs.loc[mfrs["manufacturer_id"] == mfr, "website"] = site
    mfrs = mfrs[mfrs["manufacturer_id"].isin(present | {"RII"})]

    # The committed files are kept sorted so a re-merge diffs as the data
    # that changed, not as every row of every re-imported catalog moving.
    glasses = glasses.sort_values("glass_id", kind="stable")
    trans = trans.sort_values("glass_id", kind="stable")
    props = props.sort_values(["glass_id", "property"], kind="stable")
    sell = sell.sort_values("glass_id", kind="stable")
    for col in ("zemax_formula", "rii_formula"):
        if col in sell.columns:
            sell[col] = pd.to_numeric(sell[col], errors="coerce").astype("Int64")
    sources = sources.sort_values("source_id", kind="stable")
    mfrs = mfrs.sort_values("manufacturer_id", kind="stable")
    equiv = equiv.sort_values(["glass_id_a", "glass_id_b"], kind="stable")
    glasses.to_csv(norm / "glasses.csv", index=False)
    props.to_csv(norm / "properties.csv", index=False)
    sell.to_csv(norm / "sellmeier.csv", index=False)
    trans.to_csv(norm / "transmission.csv", index=False)
    sources.to_csv(norm / "sources.csv", index=False)
    mfrs.to_csv(norm / "manufacturers.csv", index=False)
    equiv.to_csv(norm / "equivalents.csv", index=False)
    print(f"Merged {len(jobs)} catalog(s) and {len(mirrors)} mirror file(s) "
          "into data/normalized.")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "clean_transmission.py")],
                   check=True)
    # IR rows with a placeholder n_d can only be verified against the
    # refractiveindex.info reference pages; re-apply that check.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_ir_dispersion.py")],
                   check=True)


if __name__ == "__main__":
    main()
