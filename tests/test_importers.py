"""Tests: generic importer normalizes without touching app logic."""
from glassmatch.importers.generic_csv import normalize_frame
import pandas as pd


def test_generic_import():
    raw = pd.DataFrame([{"name": "DemoGlass", "manufacturer": "ACME",
                         "nd": 1.52, "vd": 60.0, "density": 2.5}])
    g, p = normalize_frame(raw, "ACME", "USER-IMPORT")
    assert len(g) == 1 and len(p) == 3
    assert set(p["property"]) == {"refractive_index_nd", "abbe_number_vd", "density"}
    assert (p["data_type"] == "user_imported").all()
