"""Supply-risk flags are catalog facts in the source's own terms, never a
score, and appear wherever glasses are chosen."""
from glassmatch.supply import supply_flags, supply_text


def test_flags_from_catalog_facts():
    assert supply_flags({"status": "preferred"}) == []
    assert supply_flags({"status": "obsolete"})[0][0] == "high"
    f = supply_flags({"status": "inquiry", "manufacturer_id": "CDGM",
                      "production_frequency": "D", "relative_cost": 17.3})
    assert [lv for lv, _ in f] == ["caution"] * 3
    assert "every 2+ years" in f[1][1] and "17.3 x" in f[2][1]
    assert supply_flags({"data_tier": "unverified_mirror"})[0][0] == "high"


def test_maker_scales_are_not_reinterpreted():
    # Frequency letters only mean something in the maker that defines them.
    assert supply_flags({"manufacturer_id": "SCHOTT", "production_frequency": "D"}) == []
    assert supply_flags({"manufacturer_id": "CDGM", "production_frequency": "B"}) == []
    assert supply_flags({"relative_cost": 9.9}) == []
    assert supply_flags({"relative_cost": "n/a"}) == []


def test_text_orders_high_first():
    t = supply_text({"status": "obsolete", "relative_cost": 12})
    assert t.startswith("HIGH: no longer produced") and "caution: relative cost 12 x" in t
    assert supply_text({"status": "standard"}) == ""


def test_replacement_and_cli_carry_supply():
    import subprocess
    import sys
    from pathlib import Path

    from glassmatch import lens as L
    from glassmatch.database import load_default_database
    db = load_default_database()
    rx = L.read_prescription(db, Path(__file__).parent / "fixtures" / "doublet.json")
    _, df = L.replacement_candidates(db, rx, "SCHOTT-N-SF5")
    assert "supply" in df.columns
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-m", "glassmatch.cli", "info", "N-PK51",
                          "--maker", "SCHOTT"], capture_output=True, text=True,
                         cwd=root, check=True)
    assert "supply (caution): relative cost" in out.stdout
