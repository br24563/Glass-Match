"""Versioned data releases: data/normalized/MANIFEST.json.

A design that cites "GlassMatch" must be able to say *which* data it used.
The manifest gives the shipped database a version and pins every file to a
SHA-256, so a version string identifies exactly one set of numbers:

* ``data_version`` - ``YYYY.MM.DD`` of the last change to any data file. It
  changes only when a file's content changes; rebuilding an unchanged
  database keeps it.
* ``files`` - per CSV: SHA-256 of its bytes (line endings normalised to LF,
  as git stores them) and its row count.
* ``summary`` - the headline counts (materials, makers, verified fits).

``scripts/build_data_manifest.py`` writes it (both merge scripts call it);
``tests/test_manifest.py`` fails if a data file changed without it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

MANIFEST_NAME = "MANIFEST.json"


def _sha256(path: Path) -> str:
    # git stores these files with LF endings and a Windows checkout may
    # expand them to CRLF; hash the stored form so both agree.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _rows(path: Path) -> int:
    import pandas as pd
    return int(len(pd.read_csv(path)))


def file_entries(data_dir: Path) -> dict:
    return {p.name: {"sha256": _sha256(p), "rows": _rows(p)}
            for p in sorted(Path(data_dir).glob("*.csv"))}


def summary(data_dir: Path) -> dict:
    import pandas as pd
    from glassmatch.importers.agf import is_dispersable_formula
    d = Path(data_dir)
    g = pd.read_csv(d / "glasses.csv")
    s = pd.read_csv(d / "sellmeier.csv")
    ids = set(g["glass_id"])
    verified = set(s.loc[s["formula"].map(is_dispersable_formula), "glass_id"])
    return {"materials": int(len(g)),
            "manufacturers": int(g["manufacturer_id"].nunique()),
            "verified_dispersion_fits": len(verified & ids),
            "obsolete": int((g["status"] == "obsolete").sum()),
            "sources": int(len(pd.read_csv(d / "sources.csv")))}


def read_manifest(data_dir: Path) -> dict | None:
    p = Path(data_dir) / MANIFEST_NAME
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def stale_files(data_dir: Path) -> list:
    """Names of files whose content no longer matches the manifest (or that
    it does not list, or lists but are gone). Empty when consistent."""
    m = read_manifest(data_dir) or {"files": {}}
    now = {p.name: _sha256(p) for p in Path(data_dir).glob("*.csv")}
    listed = m.get("files", {})
    bad = [n for n, h in now.items() if listed.get(n, {}).get("sha256") != h]
    bad += [n for n in listed if n not in now]
    return sorted(bad)


def build_manifest(data_dir: Path, today: date | None = None) -> dict:
    """The manifest for data_dir; keeps the old version if nothing changed."""
    from glassmatch import __version__
    old = read_manifest(data_dir)
    files = file_entries(data_dir)
    unchanged = old is not None and {n: e["sha256"] for n, e in files.items()} == \
        {n: e["sha256"] for n, e in old.get("files", {}).items()}
    version = (old["data_version"] if unchanged
               else (today or date.today()).strftime("%Y.%m.%d"))
    return {"data_version": version, "package_version": __version__,
            "summary": summary(data_dir), "files": files}


def write_manifest(data_dir: Path, today: date | None = None) -> dict:
    m = build_manifest(data_dir, today)
    (Path(data_dir) / MANIFEST_NAME).write_text(
        json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    return m


def data_version(data_dir: Path | None = None) -> str:
    """The shipped data's version, or "unversioned" without a manifest."""
    if data_dir is None:
        from glassmatch.database import DEFAULT_DATA_DIR as data_dir
    m = read_manifest(data_dir)
    return m["data_version"] if m else "unversioned"
