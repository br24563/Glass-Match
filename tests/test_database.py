"""Tests: database loads equivalents + material_class/status defaults."""
from pathlib import Path
from glassmatch.database import GlassDatabase

DATA = Path(__file__).resolve().parents[1] / "data" / "normalized"


def test_loads():
    db = GlassDatabase.load(DATA)
    assert len(db.glasses) >= 10
    assert set(db.manufacturers["manufacturer_id"]) >= {"SCHOTT", "OHARA", "HOYA", "CDGM", "SUMITA"}


def test_provenance_present():
    db = GlassDatabase.load(DATA)
    prov = db.property_provenance("SCHOTT-N-BK7", "refractive_index_nd")
    assert prov and prov[0]["source_id"]
    assert db.get_source_row(prov[0]["source_id"]) is not None


def test_summary_has_nd_vd():
    db = GlassDatabase.load(DATA)
    s = db.summary_frame()
    assert s["nd"].notna().sum() >= 10
    assert s["vd"].notna().sum() >= 10
    assert "material_class" in s.columns and "status" in s.columns


def test_equivalents_present():
    db = GlassDatabase.load(DATA)
    eq = db.equivalents_for("SCHOTT-N-BK7")
    assert not eq.empty
    assert "OHARA-S-BSL7" in set(eq["glass_id_a"]) | set(eq["glass_id_b"])
