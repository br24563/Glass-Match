"""Tests: duplicate NM names disambiguate; non-Sellmeier gate; deduped merge."""
from glassmatch.importers.agf import parse_agf_text, is_sellmeier1_formula


def test_duplicate_nm_disambiguates():
    text = ("NM E-FL6 1 567428 1.567320 42.841784 0 0 4\n"
            "CD 1.0 0.01 0.2 0.02 1.0 100.0\n"
            "NM E-FL6 1 567428 1.567320 42.840704 0 0 0\n"
            "CD 1.0 0.01 0.2 0.02 1.0 100.0\n")
    g, p, s, t, issues = parse_agf_text(text, "HOYA", "T")
    assert len(g) == 2
    assert g["glass_id"].is_unique
    assert any("duplicate NM name" in i.get("issue", "") for i in issues)


def test_sellmeier_gate():
    assert is_sellmeier1_formula("Sellmeier-1 (Zemax CD record)")
    assert not is_sellmeier1_formula("Non-Sellmeier CD record (do not disperse as Sellmeier-1)")
    assert not is_sellmeier1_formula(None)


def test_dispersion_status_gating():
    import pandas as pd
    from glassmatch.database import GlassDatabase
    db = GlassDatabase(
        glasses=pd.DataFrame([{"glass_id": "A", "manufacturer_id": "M",
                               "glass_name": "A", "glass_family": "f",
                               "description": ""}]),
        manufacturers=pd.DataFrame([{"manufacturer_id": "M", "name": "M"}]),
        properties=pd.DataFrame(columns=["glass_id", "property", "value",
                                          "data_type", "source_id"]),
        sellmeier=pd.DataFrame([{"glass_id": "A",
                                 "formula": "Non-Sellmeier CD record (x)"}]),
    )
    assert db.dispersion_status("A") == "archived-non-sellmeier"
    assert db.summary_frame().iloc[0]["has_sellmeier"] == False
    assert db.sellmeier_for("A", sellmeier_only=True) is None
