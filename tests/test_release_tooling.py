"""Tests: availability status, the data manifest, the command line, packaging,
and start-up performance."""
import json
import shutil
import time
import tomllib
from pathlib import Path

import pandas as pd
import pytest

import glassmatch
from glassmatch.cli import main as cli
from glassmatch.database import load_default_database
from glassmatch.export_agf import _ZEMAX_STATUS
from glassmatch.importers.agf import ZEMAX_STATUS, parse_agf_text
from glassmatch.manifest import (build_manifest, data_version, stale_files,
                                 write_manifest)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "normalized"


@pytest.fixture(scope="module")
def db():
    return load_default_database()


# --- availability ----------------------------------------------------------

def test_every_zemax_status_code_is_kept():
    text = "".join(f"NM G{i} 2 1 1.5 60 0 {i}\n" for i in range(5))
    g, *_ = parse_agf_text(text, "X", "T")
    assert list(g["status"]) == ["standard", "preferred", "obsolete",
                                 "special", "melt"]


def test_export_writes_status_back_as_zemax_codes():
    for name, code in ZEMAX_STATUS.items():
        assert _ZEMAX_STATUS[code] == name
    assert _ZEMAX_STATUS["inquiry"] == 3     # no Zemax code; written as special


def test_maker_workbooks_correct_the_agf_status(db):
    status = db.glasses.set_index("glass_id")["status"]
    # SCHOTT: "N-LAF35 moved to inquiry glasses" (its own change index), but
    # its June 2025 .agf still says obsolete.
    assert status["SCHOTT-N-LAF35"] == "inquiry"
    assert status["SCHOTT-N-BK7"] == "preferred"
    g = db.glasses
    special = g[g["description"].astype(str).str.contains(
        "OHARA-SPECIAL-XLSX", regex=False)]
    assert len(special) == 14 and (special["status"] == "inquiry").all()


def test_match_results_carry_status(db):
    from glassmatch.matching import DEFAULT_WEIGHTS, match_glasses
    s = db.summary_frame()
    out = match_glasses(s.head(50), {}, DEFAULT_WEIGHTS)
    assert "status" in out.columns and out["status"].notna().all()


# --- data manifest -----------------------------------------------------------

def test_manifest_matches_the_shipped_data():
    assert stale_files(DATA) == [], (
        "a data file changed without `python scripts/build_data_manifest.py`")
    m = json.loads((DATA / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["data_version"] == data_version()
    assert len(m["data_version"].split(".")) == 3
    assert m["summary"]["materials"] == len(pd.read_csv(DATA / "glasses.csv"))


def test_data_version_changes_only_with_the_data(tmp_path):
    import datetime as dt
    for f in DATA.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    first = write_manifest(tmp_path, today=dt.date(2030, 1, 2))
    assert first["data_version"] == "2030.01.02"
    again = build_manifest(tmp_path, today=dt.date(2031, 5, 6))
    assert again["data_version"] == "2030.01.02"          # nothing changed
    with open(tmp_path / "equivalents.csv", "a", encoding="utf-8") as f:
        f.write("A,B,near-equivalent,X,\n")
    assert stale_files(tmp_path) == ["equivalents.csv"]
    changed = build_manifest(tmp_path, today=dt.date(2031, 5, 6))
    assert changed["data_version"] == "2031.05.06"


# --- command line --------------------------------------------------------------

def test_cli_version_info_n_check(capsys):
    assert cli(["version"]) == 0
    assert data_version() in capsys.readouterr().out
    assert cli(["info", "N-BK7"]) == 0
    out = capsys.readouterr().out
    assert "SCHOTT-N-BK7" in out and "SCHOTT-AGF-2025-06" in out
    assert cli(["n", "N-BK7", "587.5618", "3000"]) == 0
    out = capsys.readouterr().out
    assert "1.516800" in out and "unavailable" in out    # never extrapolated
    assert cli(["check"]) == 0


def test_cli_search_and_export(tmp_path, capsys):
    csv = tmp_path / "r.csv"
    assert cli(["search", "--nd", "1.51:1.52", "--vd", "63:65", "--preferred",
                "--top", "5", "--csv", str(csv)]) == 0
    r = pd.read_csv(csv)
    assert 0 < len(r) <= 5 and (r["status"] == "preferred").all()
    agf = tmp_path / "x.agf"
    assert cli(["export-agf", "SCHOTT-N-BK7", "-o", str(agf)]) == 0
    text = agf.read_text(encoding="utf-8")
    assert "NM N-BK7 2" in text and f"data version {data_version()}" in text


def test_cli_refuses_an_ambiguous_name():
    with pytest.raises(SystemExit, match="ambiguous"):
        cli(["info", "F2"])          # SCHOTT, HOYA and HIKARI all have an F2


# --- packaging ------------------------------------------------------------------

def test_pyproject_ships_the_database_and_the_command():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    st = meta["tool"]["setuptools"]
    assert st["package-dir"]["glassmatch.data"] == "data/normalized"
    assert "MANIFEST.json" in st["package-data"]["glassmatch.data"]
    assert meta["project"]["scripts"]["glassmatch"] == "glassmatch.cli:main"
    assert "streamlit" not in " ".join(meta["project"]["dependencies"])
    assert glassmatch.__version__.count(".") == 2


def test_data_dir_can_be_overridden(monkeypatch, tmp_path):
    import importlib
    import glassmatch.database as d
    monkeypatch.setenv("GLASSMATCH_DATA_DIR", str(tmp_path))
    assert d._default_data_dir() == tmp_path
    monkeypatch.delenv("GLASSMATCH_DATA_DIR")
    assert importlib.reload(d).DEFAULT_DATA_DIR == DATA


# --- start-up performance --------------------------------------------------------

def test_cold_start_work_stays_fast():
    """What app.py does before first render took ~130 s (row-by-row scans of
    30k-135k-row tables); it is ~5 s now. The bound only catches a return to
    minutes, not normal machine variance."""
    from glassmatch.validation import (validate_property_frame,
                                       validate_spectral_nk_frame)
    t = time.perf_counter()
    db = load_default_database()
    s = db.summary_frame()
    for gid in s["glass_id"]:
        db.n_at(gid, 587.6)
    validate_property_frame(db.properties)
    validate_spectral_nk_frame(db.spectral_nk)
    assert time.perf_counter() - t < 60
