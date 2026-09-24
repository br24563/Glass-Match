"""Tests: IR mode never penalizes missing Vd; oxide behaviour unchanged."""
from glassmatch.matching import score_glass, match_glasses, is_ir_glass
import pandas as pd


def test_ir_mode_skips_vd():
    props = {"nd": 4.0, "vd": None, "density": None, "cte": None,
             "transmission": 95.0}
    req = {"nd_min": 3.9, "nd_max": 4.1, "vd_min": 20, "vd_max": 80,
           "transmission_min": 90.0}
    w = {"nd": 1, "vd": 1, "transmission": 1, "density": 0, "cte": 0}
    sc_oxide = score_glass(props, req, w)
    sc_ir = score_glass(props, req, w, ir_mode=True)
    assert sc_ir["overall"] > sc_oxide["overall"]
    assert sc_ir["flags"]["vd"] == "n/a (IR material)"
    assert "vd" not in sc_ir["missing"]


def test_is_ir_glass():
    assert is_ir_glass({"material_class": "chalcogenide", "manufacturer_id": "X"})
    assert is_ir_glass({"material_class": "oxide_glass", "manufacturer_id": "INFRARED"})
    assert not is_ir_glass({"material_class": "oxide_glass", "manufacturer_id": "SCHOTT"})


def test_match_marks_ir_rows():
    s = pd.DataFrame([
        {"glass_id": "IR", "glass": "GE", "manufacturer": "M", "manufacturer_id": "INFRARED",
         "family": "f", "material_class": "chalcogenide",
         "nd": 4.0, "vd": None, "density": None, "cte": None},
        {"glass_id": "OX", "glass": "BK7", "manufacturer": "M", "manufacturer_id": "SCHOTT",
         "family": "f", "material_class": "oxide_glass",
         "nd": 1.52, "vd": 64.0, "density": 2.5, "cte": 7.0},
    ])
    out = match_glasses(s, {"nd_min": 3.9, "nd_max": 4.1},
                        {"nd": 1, "vd": 1, "transmission": 0, "density": 0, "cte": 0})
    assert bool(out[out["glass_id"] == "IR"].iloc[0]["ir_mode"]) is True
    assert bool(out[out["glass_id"] == "OX"].iloc[0]["ir_mode"]) is False
