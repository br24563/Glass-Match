"""Glasses known only from a third-party mirror of unknown date are a
distinct data tier, hidden by default wherever a glass is chosen."""
import pytest

from glassmatch.cli import main as cli
from glassmatch.database import load_default_database


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def test_tiers(db):
    t = db.data_tiers()
    assert set(t.values()) == {"manufacturer", "literature", "unverified_mirror"}
    assert t["SCHOTT-N-BK7"] == "manufacturer"
    assert t["RII-CAF2-MALITSON"] == "literature"
    mir = [g for g, v in t.items() if v == "unverified_mirror"]
    assert len(mir) > 250
    assert any(g.startswith(("CORNING-", "LZOS-")) for g in mir)
    # Every unverified glass rests on a source whose licence says so.
    s = db.summary_frame()
    assert (s["data_tier"] == s["glass_id"].map(t)).all()


def test_search_hides_mirrors_by_default(tmp_path):
    import pandas as pd
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    assert cli(["search", "--top", "5000", "--csv", str(a)]) == 0
    assert cli(["search", "--top", "5000", "--include-mirrors", "--csv", str(b)]) == 0
    ra, rb = pd.read_csv(a), pd.read_csv(b)
    assert not ra["glass_id"].str.startswith(("CORNING-", "LZOS-")).any()
    assert rb["glass_id"].str.startswith(("CORNING-", "LZOS-")).any()


def test_replacement_never_offers_an_unverified_glass(db):
    from pathlib import Path

    from glassmatch import lens as L
    rx = L.read_prescription(db, Path(__file__).parent / "fixtures" / "doublet.json")
    t = db.data_tiers()
    _, df = L.replacement_candidates(db, rx, "SCHOTT-N-SF5", tol_vd=3, max_results=200)
    assert not df.empty and not (df["glass_id"].map(t) == "unverified_mirror").any()
    _, df2 = L.replacement_candidates(db, rx, "SCHOTT-N-SF5", tol_vd=3,
                                      max_results=200, include_mirrors=True)
    assert len(df2) >= len(df)
