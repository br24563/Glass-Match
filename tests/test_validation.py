"""Tests: validation flags bad values, duplicates, missing provenance."""
import pandas as pd
from glassmatch.validation import (validate_property_frame, validate_glass_frame,
                                   validate_transmission_frame, orphan_source_ids,
                                   orphan_glass_ids)


def test_flags_out_of_range():
    p = pd.DataFrame([{"glass_id": "G", "property": "refractive_index_nd",
                       "value": 5.0, "source_id": "S"}])
    assert validate_property_frame(p)


def test_flags_duplicate_and_missing_source():
    p = pd.DataFrame([
        {"glass_id": "G", "property": "refractive_index_nd", "value": 1.5, "source_id": ""},
        {"glass_id": "G", "property": "refractive_index_nd", "value": 1.5, "source_id": ""},
    ])
    issues = validate_property_frame(p)
    assert any("missing source" in i["issue"] for i in issues)
    assert any("duplicate" in i["issue"] for i in issues)


def test_flags_duplicate_glass():
    g = pd.DataFrame([
        {"glass_id": "G", "manufacturer_id": "M"},
        {"glass_id": "G", "manufacturer_id": "M"},
    ])
    assert validate_glass_frame(g)


def test_transmission_clean_frame_no_issues():
    t = pd.DataFrame({"glass_id": ["G", "G"],
                      "wavelength_um": [0.5, 0.6],
                      "transmission": [0.95, 0.97],
                      "source_id": ["S", "S"]})
    assert validate_transmission_frame(t) == []


def test_transmission_flags_out_of_fraction_and_wavelength():
    t = pd.DataFrame({"glass_id": ["G", "G"],
                      "wavelength_um": [0.5, 75.0],
                      "transmission": [95.0, 0.9],  # 95.0 = percent, not fraction
                      "source_id": ["S", "S"]})
    issues = validate_transmission_frame(t)
    assert any("0-1 fraction" in i["issue"] for i in issues)
    assert any("outside 0.05-50" in i["issue"] for i in issues)


def test_transmission_flags_missing_source_and_duplicates():
    t = pd.DataFrame({"glass_id": ["G", "G"],
                      "wavelength_um": [0.5, 0.5],
                      "transmission": [0.9, 0.9],
                      "source_id": ["", ""]})
    issues = validate_transmission_frame(t)
    assert any("missing source_id" in i["issue"] for i in issues)
    assert any("duplicate" in i["issue"] for i in issues)


def test_orphan_source_ids():
    g = pd.DataFrame([{"glass_id": "G", "source_id": "KNOWN"}])
    p = pd.DataFrame([{"glass_id": "G", "source_id": "MISSING"}])
    s = pd.DataFrame([{"source_id": "KNOWN"}])
    assert orphan_source_ids(g, p, s) == ["MISSING"]
    s2 = pd.DataFrame([{"source_id": "KNOWN"}, {"source_id": "MISSING"}])
    assert orphan_source_ids(g, p, s2) == []


def test_orphan_glass_ids():
    """Properties pointing at a glass that does not exist are reported."""
    g = pd.DataFrame([{"glass_id": "REAL"}])
    p = pd.DataFrame([{"glass_id": "REAL"}, {"glass_id": "GHOST"}])
    assert orphan_glass_ids(p, g) == ["GHOST"]
    assert orphan_glass_ids(p, pd.DataFrame([{"glass_id": "REAL"},
                                             {"glass_id": "GHOST"}])) == []


def test_orphan_glass_ids_is_empty_safe():
    assert orphan_glass_ids(pd.DataFrame(), pd.DataFrame([{"glass_id": "A"}])) == []
    assert orphan_glass_ids(pd.DataFrame([{"glass_id": "A"}]), pd.DataFrame()) == []
    # No glass_id column at all must not raise.
    assert orphan_glass_ids(pd.DataFrame([{"value": 1}]),
                            pd.DataFrame([{"glass_id": "A"}])) == []


def test_density_rule_admits_polymer_but_rejects_nonsense():
    """Widen enough for real polymers, still tight enough to catch junk."""
    props = pd.DataFrame([
        {"glass_id": "G", "property": "density", "value": 1.02, "source_id": "S"},
        {"glass_id": "G", "property": "density", "value": 0.95, "source_id": "S"},
        {"glass_id": "G", "property": "density", "value": 5.58, "source_id": "S"},
        {"glass_id": "G", "property": "density", "value": 250.0, "source_id": "S"},
    ])
    flagged = [i for i in validate_property_frame(props) if "density" in i["issue"]]
    assert len(flagged) == 1
    assert flagged[0]["value"] == 250.0
