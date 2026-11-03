"""Header parsing of the makers' dn/dT tables, on synthetic header rows in
each maker's layout (the workbooks themselves stay local)."""
from glassmatch.importers.dndt_xlsx import LINES_UM, column_map


def test_ohara_style():
    g = [[None, "Δn/ΔT  relative   (10-6 K-1)", None]]
    c = [None, "d(-60~-40)", "1550(20~40)"]
    m = column_map(g, c)
    assert m[1] == (LINES_UM["d"], -60, -40, "relative", "")
    assert m[2] == (1.55, 20, 40, "relative", "")


def test_hoya_style_wide_groups_and_constants_skipped():
    row0 = ["Temperature Coefficient of Refractive Index", None,
            "Temperature Coefficient of Refractive Index  nd  587.56   (×10-6/℃)"] + [None] * 21
    row1 = ["Constants", None, "Relative value dn/dT"] + [None] * 9 + ["Absolute value dn/dT"] + [None] * 11
    row2 = ["D0", "D1"] + ["20 / 40"] * 22
    m = column_map([row0, row1], row2)
    assert 0 not in m and 1 not in m              # model constants
    assert m[2][0] == 0.58756 and m[2][3] == "relative"
    assert m[23][3] == "absolute"                 # 21 columns from its label


def test_hoya_abbe_columns_skipped():
    row0 = ["Temperature Coefficient of Abbe number  dνd/dT 587.56   (×10-3/℃)"]
    row1 = ["Relative value dνd/dT"]
    assert column_map([row0, row1], ["-40 / -20"]) == {}


def test_cdgm_style():
    g = [["dn/dt relative(10-6/℃) for C'", None]]
    m = column_map(g, ["-60~-40", "-40~-20"])
    assert m[0] == (LINES_UM["C'"], -60, -40, "relative", "")
    assert m[1][1:3] == (-40, -20)


def test_hikari_style_reference_marks():
    g = [[None, "Δn/ΔT　-70ºC to -60ºC　（1E-6/ºC）， 　上段：相対屈折率（参考値），下段：絶対屈折率", None]]
    m = column_map(g, [None, 1.083, "ｔ"])
    assert m[1] == (1.083, -70, -60, None, "relative")
    assert m[2][0] == LINES_UM["t"]


def test_schott_style():
    g = [["Absolute temperature coefficients of refractive index\n [-40/-20 deg.C]", None, None]]
    m = column_map(g, ["1060nm", "e-line", " g-line"])
    assert m[0] == (1.06, -40, -20, "absolute", "")
    assert m[1][0] == LINES_UM["e"] and m[2][0] == LINES_UM["g"]
