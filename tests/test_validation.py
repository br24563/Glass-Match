"""Tests: validation flags bad values, duplicates, missing provenance."""
import pandas as pd
from glassmatch.validation import validate_property_frame, validate_glass_frame


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
