"""Tests: manufacturers' Excel data workbooks (SCHOTT, OHARA, CDGM) as extra
property sources - header parsing, units, name mapping, no clobbering - and
the rows they added to the shipped data."""
import pandas as pd
import pytest

from glassmatch.database import load_default_database
from glassmatch.importers.maker_xlsx import _num, import_maker_xlsx, name_key

openpyxl = pytest.importorskip("openpyxl")


def _book(path, sheets):
    """sheets: {title: rows}; the first sheet replaces the default one."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(list(r))
    wb.save(path)
    return path


# OHARA layout: a group-title row, then the header row with the name in
# column B. "nD" (589.3 nm) precedes "nd"; a rounded V_d precedes the exact.
OHARA_HEAD = ["", "Glass ", "nD", "nd", "νd", "νd", "Tg（℃）",
              "λ(W/(m･K))", "Young's (E) ", "Rigidity (G)", "Poisson's(σ)",
              "Knoop (Hk)", "β", "RW(P)", "RA(P)", "W(S)max", "W(S)min", "SR",
              "PR"]


def _ohara_row(name, nd=1.497, e=72.7, g=28, nu=0.299, sr=52.1):
    return [1, name, 1.49694, nd, 81.6, 81.54, 459, 0.78, e, g, nu, 360,
            0.74, 1, 3, 1, None, sr, 4]


def _ohara(tmp_path, rows):
    return _book(tmp_path / "ohara.xlsx", {
        "Recommended glasses 5桁": [["", "", "REFRACTIVE INDICES"], OHARA_HEAD]
        + rows})


NAMES = {name_key("S-FPL51"): "OHARA-S-FPL51",
         name_key("S-FPM2"): "OHARA-S-FPM2"}


def _vals(df, gid):
    return df[df["glass_id"] == gid].set_index("property")["value"]


def test_ohara_columns_found_by_header_and_mapped_by_name(tmp_path):
    path = _ohara(tmp_path, [_ohara_row("S-FPL51"), _ohara_row("S-FPM 2"),
                             _ohara_row("S-NOPE9")])
    df, rep = import_maker_xlsx(path, "OHARA", "T", NAMES)
    v = _vals(df, "OHARA-S-FPL51")
    assert v["tg"] == 459 and v["thermal_conductivity"] == 0.78
    assert v["youngs_modulus"] == 72.7 and v["shear_modulus"] == 28
    assert v["poisson_ratio"] == 0.299 and v["knoop_hardness"] == 360
    assert v["stress_optic_coefficient"] == 0.74
    assert v["water_resistance_powder"] == 1 and v["acid_resistance_powder"] == 3
    assert "weathering_resistance_surface_min" not in v      # blank cell
    assert set(df["data_type"]) == {"manufacturer"}
    assert set(df["source_id"]) == {"T"}
    units = df.drop_duplicates("property").set_index("property")["unit"]
    assert units["youngs_modulus"] == "GPa"
    assert units["stress_optic_coefficient"] == "1e-12/Pa"
    # 'S-FPM 2' in the workbook is S-FPM2 in the .agf; S-NOPE9 is reported.
    assert "OHARA-S-FPM2" in set(df["glass_id"])
    assert rep["unmatched"] == ["Recommended glasses 5桁: S-NOPE9"]
    assert rep["moduli_checked"] == 2 and not rep["moduli"]


def test_workbook_never_stores_nd_vd_and_reports_disagreement(tmp_path):
    path = _ohara(tmp_path, [_ohara_row("S-FPL51", nd=1.49700),
                             _ohara_row("S-FPM 2", nd=1.59522)])
    cat = {"OHARA-S-FPL51": (1.497, 81.54), "OHARA-S-FPM2": (1.5952, 81.54)}
    df, rep = import_maker_xlsx(path, "OHARA", "T", NAMES,
                                catalog_nd_vd=cat)
    assert not df["property"].isin(["refractive_index_nd",
                                    "abbe_number_vd"]).any()
    # The 'nd' column is read, not 'nD' (1.49694), so S-FPL51 agrees.
    assert rep["nd_vd"] == [("OHARA-S-FPM2", "n_d", 1.59522, 1.5952)]


def test_existing_values_are_never_clobbered_or_duplicated(tmp_path):
    path = _ohara(tmp_path, [_ohara_row("S-FPL51", sr=52.1),
                             _ohara_row("S-FPM 2", sr=4)])
    existing = {("OHARA-S-FPL51", "acid_resistance"): 52.1,
                ("OHARA-S-FPM2", "acid_resistance"): 3.0}
    df, rep = import_maker_xlsx(path, "OHARA", "T", NAMES, existing)
    assert "acid_resistance" not in set(df["property"])
    assert rep["skipped_existing"] == 2
    assert rep["conflicts"] == [("OHARA-S-FPM2", "acid_resistance", 4.0, 3.0)]
    # A second workbook over the same glasses adds nothing; the stored class
    # stays, so the disagreement is reported again.
    df2, rep2 = import_maker_xlsx(path, "OHARA", "T2", NAMES, existing)
    assert df2.empty and rep2["conflicts"] == rep["conflicts"]
    assert existing[("OHARA-S-FPM2", "acid_resistance")] == 3.0


def test_moduli_not_in_gpa_are_refused(tmp_path):
    # E and G in 1e8 N/m^2 still satisfy E = 2G(1+nu) - only the magnitude
    # check tells them from GPa.
    path = _ohara(tmp_path, [_ohara_row("S-FPL51", e=727, g=280),
                             _ohara_row("S-FPM 2", e=727, g=280)])
    with pytest.raises(ValueError, match="GPa"):
        import_maker_xlsx(path, "OHARA", "T", NAMES)


CDGM_HEAD = ["Glass", "Code", "nD", "nd", "νd", "DW", "DA", "CR", "Tg(℃)",
             "λ[W/(m·K)]", "cp[J/(g·K)]", "HK(107Pa)", "E(107Pa)", "G(107Pa)",
             "μ", "B(10-12/Pa)"]
CDGM_NAMES = {name_key("H-FK61"): "CDGM-H-FK61", name_key("H-QK1"): "CDGM-H-QK1"}


def _cdgm(tmp_path, g1=2694, g2=1955):
    return _book(tmp_path / "cdgm.xlsx", {"optical glass": [
        CDGM_HEAD, [None, None, 589.29, 587.56],
        ["H-FK61", 497816, 1.49695, 1.497, 81.61, 1, 5, 1, 461, 0.578, 0.545,
         372, 7007, g1, 0.3, 0.69],
        ["H-QK1", 470669, 1.47041, 1.47047, 66.88, 5, 5, "4c", 399, 0.719,
         0.674, 374, 4828, g2, 0.235, 3.76],
        ["over!"], ["H-FK61", 1, 1, 1]],
        "i line glass": [CDGM_HEAD], "infrared glass": [CDGM_HEAD]})


def test_cdgm_units_from_header_and_moduli_check(tmp_path):
    df, rep = import_maker_xlsx(_cdgm(tmp_path), "CDGM", "T", CDGM_NAMES)
    v = _vals(df, "CDGM-H-FK61")
    assert v["youngs_modulus"] == pytest.approx(70.07)      # 7007 x 1e7 Pa
    assert v["shear_modulus"] == pytest.approx(26.94)
    assert v["youngs_modulus"] == pytest.approx(
        2 * v["shear_modulus"] * (1 + v["poisson_ratio"]), rel=0.01)
    assert v["specific_heat"] == 0.545 and v["stress_optic_coefficient"] == 0.69
    k = df[(df["glass_id"] == "CDGM-H-FK61")
           & (df["property"] == "knoop_hardness")].iloc[0]
    assert (k["value"], k["unit"]) == (372, "1e7 Pa")      # as printed
    # CR duplicates the .agf climate class and is not read; reading stops
    # at CDGM's "over!" marker.
    assert "climate_resistance" not in set(df["property"])
    assert rep["rows"] == 2 and rep["moduli_checked"] == 2


def test_cdgm_wrong_shear_unit_is_refused(tmp_path):
    # G printed in GPa beside E in 1e7 Pa: E = 2G(1+mu) fails on every row.
    with pytest.raises(ValueError, match="E = 2G"):
        import_maker_xlsx(_cdgm(tmp_path, g1=26.94, g2=19.55), "CDGM", "T",
                          CDGM_NAMES)


SCHOTT_HEAD = ["Glass", "nd", "vd", "K", "CR", "SR", "SR-J", "Density", "Tg",
               "Heat capacity (cp)", "Heat conductivity(lambda)",
               "Young´s modulus (E)", "Poisson ratio (µ)",
               "Knoop hardness (HK)"]
SCHOTT_DESC = [
    ["", "Tg", "glass transformation temperature [°C] (ISO 7884-8)"],
    ["", "Heat capacity (cp)", "heat capacity [J/gK]"],
    ["", "Heat conductivity(lambda)", "heat conductivity [W/mK]"],
    ["Mechanical properties", "Young´s modulus (E)", "Young's modolus [GPa]"],
    ["", "K", "stress optical coefficient in [10-6MPa-1]"]]


def _schott(tmp_path, desc=SCHOTT_DESC):
    row = ["N-BK7", 1.5168, 64.17, 2.77, 1, 1, "4-5", 2.51, 557, 0.858, 1.114,
           82, 0.206, 610]
    return _book(tmp_path / "schott.xlsx", {
        "Preferred glasses": [["SCHOTT, Optical Glass"], [], [], SCHOTT_HEAD,
                              row],
        "Inquiry glasses": [[], [], [], SCHOTT_HEAD],
        "Description": desc})


def test_schott_units_confirmed_by_its_description_sheet(tmp_path):
    names = {name_key("N-BK7"): "SCHOTT-N-BK7"}
    df, rep = import_maker_xlsx(_schott(tmp_path), "SCHOTT", "T", names)
    v = _vals(df, "SCHOTT-N-BK7")
    assert v["youngs_modulus"] == 82 and v["poisson_ratio"] == 0.206
    assert v["stress_optic_coefficient"] == 2.77 and v["tg"] == 557
    assert "acid_resistance_powder" not in v      # '4-5' is a range, not a value
    assert rep["unparsed"] == 1
    bad = [r if r[1] != "Young´s modulus (E)" else [r[0], r[1], "Young's [MPa]"]
           for r in SCHOTT_DESC]
    with pytest.raises(ValueError, match="GPa"):
        import_maker_xlsx(_schott(tmp_path, bad), "SCHOTT", "T", names)


@pytest.mark.parametrize("cell", ["4-5", "4c", "#N/A", " ", "", None, "-"])
def test_non_numbers_are_not_values(cell):
    assert _num(cell) is None


# --- the shipped data -------------------------------------------------------

WORKBOOKS = ("SCHOTT-XLSX-2025-11-13", "CDGM-XLSX-2026-09",
             "OHARA-XLSX-2026-04-02", "OHARA-L-XLSX-2025-03-12",
             "OHARA-SPECIAL-XLSX-2025-03-12")


@pytest.fixture(scope="module")
def shipped():
    db = load_default_database()
    p = db.properties
    return db, p[p["source_id"].isin(WORKBOOKS)]


def test_workbook_rows_are_sourced_manufacturer_rows(shipped):
    db, x = shipped
    assert set(x["source_id"]) == set(WORKBOOKS)
    assert set(x["data_type"]) == {"manufacturer"}
    assert set(WORKBOOKS) <= set(db.sources["source_id"])
    assert not x["property"].isin(["refractive_index_nd", "abbe_number_vd",
                                   "density", "cte"]).any()
    makers = set(x["glass_id"].str.split("-").str[0])
    assert makers == {"SCHOTT", "OHARA", "CDGM"}
    for maker, n in (("SCHOTT", 150), ("OHARA", 150), ("CDGM", 300)):
        tg = x[(x["property"] == "tg") & x["glass_id"].str.startswith(maker)]
        assert tg["glass_id"].nunique() >= n


def test_no_property_is_given_twice_for_a_glass(shipped):
    db, x = shipped
    p = db.properties
    p = p[p["glass_id"].isin(set(x["glass_id"]))]
    dup = p[p.duplicated(["glass_id", "property", "reference_wavelength_nm"],
                         keep=False) & ~p["property"].str.startswith("n_at")]
    assert dup.empty, dup.head()


def test_shipped_moduli_are_self_consistent(shipped):
    _, x = shipped
    w = x.pivot_table(index="glass_id", columns="property", values="value",
                      aggfunc="first")
    w = w.dropna(subset=["youngs_modulus", "shear_modulus", "poisson_ratio"])
    assert len(w) > 450
    e = pd.to_numeric(w["youngs_modulus"])
    calc = 2 * pd.to_numeric(w["shear_modulus"]) * (
        1 + pd.to_numeric(w["poisson_ratio"]))
    assert ((e - calc).abs() <= 0.03 * e).all()


def test_same_glass_type_agrees_across_makers(shipped):
    # Units checked across makers: OHARA prints no unit for E or beta, SCHOTT
    # states GPa and 1e-6/MPa. S-BSL7 and N-BK7 are the same glass type.
    db = shipped[0]
    for prop, tol in (("youngs_modulus", 0.05), ("stress_optic_coefficient", 0.1)):
        a = db.property_value("OHARA-S-BSL7", prop)
        b = db.property_value("SCHOTT-N-BK7", prop)
        assert a == pytest.approx(b, rel=tol), prop
