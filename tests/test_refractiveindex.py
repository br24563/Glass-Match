"""Tests: refractiveindex.info (CC0) crystal pages -> GlassMatch frames.

The coefficient layout in an upstream "formula 1" page is the thing most
likely to be got wrong, so it is pinned against published values here:

  * the list is ``[T, B1, C1, B2, C2, ...]`` - INTERLEAVED, not grouped;
  * each C is a resonance WAVELENGTH in um and must be squared.

Reading it as grouped B's then C's returns a smooth-looking but wrong curve
(n ~ 1.258 at the d-line for CaF2 instead of 1.4338), so these assertions
compare against the literature rather than against our own output.
"""
import math
from pathlib import Path

import pandas as pd
import pytest

from glassmatch.database import GlassDatabase
from glassmatch.importers.refractiveindex_yaml import (REFERENCE_UM,
                                                       n_from_rii_formula,
                                                       parse_ri_page)
from glassmatch.spectra import band_stats_nk, transmission_from_nk


@pytest.fixture(scope="module")
def db():
    return GlassDatabase.load()

# Malitson (1963) CaF2, exactly as it appears on the upstream page:
# n^2-1 = 0.5675888 l^2/(l^2-0.050263605^2)
#      + 0.4710914 l^2/(l^2-0.1003909^2)
#      + 3.8484723 l^2/(l^2-34.649040^2)
CAF2_COEFFS = [0.0, 0.5675888, 0.050263605, 0.4710914, 0.1003909,
               3.8484723, 34.649040]

# Published CaF2 d-line index (Malitson 1963): n_d = 1.4338. This is the one
# value asserted against the literature. The F and C lines are deliberately NOT
# asserted: recalled side-line values disagreed with the fit by ~1e-3, and
# trusting a half-remembered number here is exactly the failure mode this
# project forbids. The d-line, the C-squared identity and the monotonicity
# checks below are sufficient to pin the layout.
CAF2_ND_PUBLISHED = 1.43376


def test_rii_formula_is_interleaved_and_squares_c():
    """The layout guard. A grouped reading gives ~1.258 and fails this."""
    got = n_from_rii_formula(CAF2_COEFFS, 0.5876)
    assert got == pytest.approx(CAF2_ND_PUBLISHED, abs=3e-4), (
        f"n_d = {got:.5f}, expected ~{CAF2_ND_PUBLISHED:.5f}")


def test_c_is_a_resonance_wavelength_not_a_c_squared():
    """Squaring the C entries must reproduce the textbook C coefficients."""
    from glassmatch.spectra import pairs_from_row
    row = {}
    n = (len(CAF2_COEFFS) - 1) // 2
    for i in range(n):
        row[f"B{i+1}"] = CAF2_COEFFS[1 + 2 * i]
        row[f"C{i+1}_um2"] = CAF2_COEFFS[2 + 2 * i] ** 2
    pairs = pairs_from_row(row)
    assert [round(b, 7) for b, _ in pairs] == [0.5675888, 0.4710914, 3.8484723]
    assert [c for _, c in pairs] == pytest.approx(
        [0.00252643, 0.0100783, 1200.556], rel=1e-5)


def test_term_count_derivation():
    assert (len(CAF2_COEFFS) - 1) % 2 == 0
    assert (len(CAF2_COEFFS) - 1) // 2 == 3


def test_dispersion_decreases_with_wavelength():
    """Cheap physical sanity: n must fall monotonically into the IR."""
    vals = [n_from_rii_formula(CAF2_COEFFS, w) for w in (0.4, 0.6, 1.0, 3.0, 8.0)]
    assert all(a > b for a, b in zip(vals, vals[1:])), vals


def test_nonlinear_index_is_never_read_as_n_squared(tmp_path):
    """"tabulated n2" is non-linear index (~1e-20), not n^2."""
    f = tmp_path / "n2.yml"
    f.write_text(
        "DATA:\n"
        "  - type: tabulated n2\n"
        "    data: |\n"
        "        0.8 1.80e-20\n"
        "        2.0 1.70e-20\n", encoding="utf-8")
    parsed = parse_ri_page(f)
    assert parsed["blocks"]["n"] == [] and parsed["blocks"]["nk"] == []
    assert [k for k, _ in parsed["blocks"]["skipped"]] == ["tabulated n2"]


def test_unimplemented_formulas_are_reported_not_guessed(tmp_path):
    """formula 2 is implemented; 4/5/7 are not, and must say so."""
    for kind in ("formula 4", "formula 5", "formula 7"):
        f = tmp_path / "x.yml"
        f.write_text(
            f"DATA:\n  - type: {kind}\n    coefficients: 1 2 3 4 5\n",
            encoding="utf-8")
        parsed = parse_ri_page(f)
        assert [k for k, _ in parsed["blocks"]["skipped"]] == [kind]
        assert "not implemented" in parsed["blocks"]["skipped"][0][1]


def test_reference_lines_include_d_and_ir():
    assert 0.5876 in REFERENCE_UM and 0.4861 in REFERENCE_UM
    assert any(w >= 8.0 for w in REFERENCE_UM)


# --- transmission from tabulated n/k --------------------------------------
# Crystals ship measured n and k rather than a manufacturer IT curve, which
# left 195 materials outside the search entirely.
def test_transmission_with_zero_absorption_is_exact_fresnel():
    """k = 0 must reduce to the textbook two-surface Fresnel figure."""
    for n in (1.434, 1.5168, 1.62, 2.0, 4.0):
        expected = (1.0 - ((n - 1.0) / (n + 1.0)) ** 2) ** 2 * 100.0
        got = transmission_from_nk(n, 0.0, 0.5876, 10.0)
        assert got == pytest.approx(expected, abs=1e-9)


def test_absorption_uses_micrometres_converted_to_millimetres():
    """Guards a real bug: um -> mm inverted, which erased absorption.

    With wl_mm = wl_um * 1000 the exponent was 1000x too small, so a strongly
    absorbing material reported as fully transparent (k=0.001 at 5 um gave
    92.13% instead of 0.00%).
    """
    n, k, t, lam_um = 1.5, 1e-3, 10.0, 5.0
    expect = math.exp(-4.0 * math.pi * k * t / (lam_um / 1000.0))
    assert expect < 1e-3, "this case must be strongly absorbing"
    assert transmission_from_nk(n, k, lam_um, t) < 0.01


def test_absorption_scales_with_thickness():
    vals = [transmission_from_nk(1.5, 1e-4, 5.0, t) for t in (1, 5, 10, 25)]
    assert vals == sorted(vals, reverse=True), "thicker must never transmit more"
    assert vals[0] > vals[-1]


def test_absorbing_material_is_not_credited_with_clear_fresnel():
    """R must use the complex index; a transparent-looking n must not win."""
    clear = transmission_from_nk(1.5, 0.0, 5.0, 10.0)
    murky = transmission_from_nk(1.5, 0.01, 5.0, 10.0)
    assert murky < clear / 100.0


def test_band_stats_nk_needs_k_and_says_so():
    n_only = pd.DataFrame({"wavelength_um": [1.0, 2.0, 3.0], "n": [1.43, 1.42, 1.41],
                           "k": [None, None, None]})
    r = band_stats_nk(n_only, 1.0, 3.0, "Average", 10.0)
    assert r["value_pct"] is None
    assert r["reason"] == "no-absorption-data"
    assert "no measured k" in r["label"]


def test_band_stats_nk_refuses_thin_film_measurements():
    """A film's optical constants are not the material's.

    The published 2 nm Ge film page reports n = 1.46 where bulk Ge is n ~ 4-5.
    Using it as bulk data would put a fictitious low-index, low-loss material
    into the catalogue.
    """
    film = pd.DataFrame({"wavelength_um": [1.0, 2.0, 3.0], "n": [1.46, 1.44, 1.43],
                         "k": [1.23, 0.4, 0.1],
                         "measurement_form": ["film"] * 3})
    r = band_stats_nk(film, 1.0, 3.0, "Average", 10.0)
    assert r["value_pct"] is None
    assert r["reason"] == "film-measurement"


def test_band_stats_nk_drops_film_rows_from_a_mixed_page():
    mixed = pd.DataFrame({
        "wavelength_um": [1.0, 2.0, 3.0, 4.0], "n": [1.46, 1.44, 1.42, 1.41],
        "k": [1.23, 0.4, 0.0, 0.0],
        "measurement_form": ["film", "film", "bulk", "bulk"]})
    r = band_stats_nk(mixed, 1.0, 4.0, "Average", 10.0)
    assert r["value_pct"] is not None
    assert r["n_points"] == 2


def test_band_stats_nk_reports_empty_band_rather_than_guessing():
    df = pd.DataFrame({"wavelength_um": [1.0, 2.0], "n": [1.43, 1.42],
                       "k": [0.0, 0.0], "measurement_form": ["bulk", "bulk"]})
    r = band_stats_nk(df, 5.0, 8.0, "Average", 10.0)
    assert r["value_pct"] is None
    assert r["reason"] == "no-samples-in-band"


def test_measurement_form_detects_film_pages():
    from glassmatch.importers.refractiveindex_yaml import measurement_form
    assert measurement_form("nk__Ciesielski-2nm", "") == "film"
    assert measurement_form("nk__Ciesielski-20nm", "") == "film"
    assert measurement_form("nk__Amotchkina-film", "") == "film"
    assert measurement_form("nk__Foo", "2 nm-thick Ge film on SiO2") == "film"
    assert measurement_form("nk__Foo", "Thin films of amorphous alumina") == "film"
    assert measurement_form("nk__Li-293K", "single crystal, room temperature") == "bulk"
    # An unlabelled page must not be silently treated as bulk.
    assert measurement_form("nk__Malitson", "") == "unknown"


def test_staged_2nm_germanium_film_is_never_marked_bulk():
    """The real page, not a synthetic one: its n=1.46 is not germanium."""
    from glassmatch.database import GlassDatabase
    db = GlassDatabase.load()
    nk = db.spectral_nk
    gid = "RII-GE-CIESIELSKI-2NM"
    sub = nk[nk.glass_id == gid]
    assert len(sub), "fixture page missing - did the staged data change?"
    assert set(sub["measurement_form"].unique()) == {"film"}
    r = band_stats_nk(sub, 0.2, 1.5, "Average", 10.0)
    assert r["value_pct"] is None and r["reason"] == "film-measurement"


def test_n_at_refuses_to_extrapolate_past_a_stated_range(db):
    """Malitson's CaF2 fit is declared valid to 9.7 um. 10 um must be 'unknown'.

    The fit happily produces a smooth 1.2996 at 10 um, which is exactly the
    kind of plausible-looking number GlassMatch must not invent.
    """
    inside, _ = db.n_at("RII-CAF2-MALITSON", 9700.0)
    outside, kind = db.n_at("RII-CAF2-MALITSON", 10000.0)
    assert inside is not None and inside > 1.0
    assert outside is None and kind is None


def test_sellmeier_range_prefers_the_source_then_the_catalog(db):
    rii_range = db._sellmeier_range("RII-CAF2-MALITSON",
                                   db.sellmeier_for("RII-CAF2-MALITSON"))
    # Malitson's page declares 0.23-9.7 um; the guard must use the source's own
    # numbers, so this is pinned to the staged YAML, not to a remembered value.
    assert rii_range == (0.23, 9.7)
    # N-BK7's .agf row carries no "lo-hi", so the catalog LD limits are used.
    agf_range = db._sellmeier_range("SCHOTT-N-BK7",
                                   db.sellmeier_for("SCHOTT-N-BK7"))
    assert agf_range is not None and agf_range[0] < agf_range[1]
    assert db.n_at("SCHOTT-N-BK7", 587.6)[0] is not None
    # and outside the catalog's own limit it declines to answer
    assert db.n_at("SCHOTT-N-BK7", 50_000.0)[0] is None


# --- formula 2 -------------------------------------------------------------
# From specs/schott/optical/N-BK7.yml. Same interleaved layout as formula 1,
# but C is already in um^2 rather than a resonance wavelength. These are N-BK7's
# published spectral-line indices, so the fit must reproduce all three.
N_BK7_F2 = [0.0, 1.03961212, 0.00600069867, 0.231792344, 0.0200179144,
            1.01046945, 103.560653]
N_BK7_LINES = {0.4861: 1.52238, 0.5876: 1.51680, 0.6563: 1.51432}


def test_formula_2_does_not_square_c():
    """Squaring formula-2 C values gives 1.50723 at the d-line, not 1.51680."""
    for lam, expected in N_BK7_LINES.items():
        got = n_from_rii_formula(N_BK7_F2, lam, square_c=False)
        assert got == pytest.approx(expected, abs=1e-4), (
            f"formula 2 n({lam} um) = {got:.5f}, expected {expected:.5f}")
    wrong = n_from_rii_formula(N_BK7_F2, 0.5876, square_c=True)
    assert abs(wrong - 1.51680) > 1e-3, "the squared reading should NOT match"


def test_formula_1_and_2_differ_only_in_c_scaling():
    a = n_from_rii_formula(CAF2_COEFFS, 0.5876, square_c=True)
    b = n_from_rii_formula(CAF2_COEFFS, 0.5876, square_c=False)
    assert a == pytest.approx(CAF2_ND_PUBLISHED, abs=3e-4)
    assert abs(a - b) > 0.01


def test_formula_2_is_supported_not_skipped():
    from glassmatch.importers import refractiveindex_yaml as rii
    assert "formula 2" in rii.SUPPORTED_FORMULAS
    assert rii.SQUARES_C == {"formula 1": True, "formula 2": False}
    assert "formula 2" not in rii.UNSUPPORTED


def test_formula_2_page_imports(tmp_path):
    from glassmatch.importers.refractiveindex_yaml import import_refractiveindex
    d = tmp_path / "N-BK7"
    d.mkdir()
    (d / "nk__N-BK7.yml").write_text(
        "REFERENCES: |\n    SCHOTT Zemax catalog\n"
        "DATA:\n  - type: formula 2\n"
        "    wavelength_range: 0.3 2.5\n"
        "    coefficients: " + " ".join(str(c) for c in N_BK7_F2) + "\n",
        encoding="utf-8")
    out = import_refractiveindex(tmp_path, {"N-BK7": ("NBK7", "t", "crystal")})
    assert len(out["sellmeier"]) == 1
    assert "formula 2" in out["sellmeier"].iloc[0]["formula"]
    # C stored as the source states it - not squared
    assert float(out["sellmeier"].iloc[0]["C1_um2"]) == pytest.approx(0.00600069867)
    nd = out["properties"][(out["properties"].property == "n_at_reference")
                           & (out["properties"].reference_wavelength_nm == 587.6)]
    assert float(nd.iloc[0]["value"]) == pytest.approx(1.51680, abs=1e-4)


def test_staged_pages_import_and_are_cc0(tmp_path):
    """A real staged page must import with citation and license intact."""
    from glassmatch.importers.refractiveindex_yaml import import_refractiveindex
    material = tmp_path / "CaF2"
    material.mkdir()
    (material / "nk__Malitson.yml").write_text(
        "REFERENCES: |\n"
        "    I. H. Malitson.\n"
        "    A redetermination of some optical properties of calcium fluoride.\n"
        "    <a href=\"https://doi.org/10.1364/AO.2.001103\">Appl. Opt. 2</a>\n"
        "COMMENTS: |\n"
        "    24 C\n"
        "DATA:\n"
        "  - type: formula 1\n"
        "    wavelength_range: 0.23 9.7\n"
        "    coefficients: " + " ".join(str(c) for c in CAF2_COEFFS) + "\n",
        encoding="utf-8")
    out = import_refractiveindex(tmp_path, {"CaF2": ("CAF2", "Calcium fluoride",
                                                    "crystal")}, "2026-09-27")
    assert len(out["glasses"]) == 1
    assert out["glasses"].iloc[0]["material_class"] == "crystal"
    assert "CC0" in out["sources"].iloc[0]["license"]
    assert "Malitson" in out["sources"].iloc[0]["source_document"]
    assert "10.1364/AO.2.001103" in out["sources"].iloc[0]["notes"]
    nd = out["properties"][(out["properties"].property == "n_at_reference")
                           & (out["properties"].reference_wavelength_nm == 587.6)]
    assert float(nd.iloc[0]["value"]) == pytest.approx(CAF2_ND_PUBLISHED, abs=3e-4)
    assert nd.iloc[0]["data_type"] == "calculated"
    assert len(out["sellmeier"]) == 1
    assert "formula 1" in out["sellmeier"].iloc[0]["formula"]


def test_upsert_preserves_existing_rows(tmp_path):
    """Regression: a boolean *DataFrame* indexer silently drops columns.

    The first version of the merge helper filtered existing rows with

        old[~old[cols].astype(str).isin(new_keys)]

    where ``cols`` is a list.  That builds a boolean DataFrame, and
    ``frame[boolean_frame]`` selects **columns**, not rows - so the result
    had no columns at all, and concatenating it wiped every value in
    properties.csv (19,904 manufacturer rows lost their numbers while the
    row count stayed correct).  This test keeps that failure from returning.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "merge_ri", Path(__file__).resolve().parents[1] /
        "scripts" / "merge_refractiveindex.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    path = tmp_path / "properties.csv"
    existing = pd.DataFrame([
        {"glass_id": "SCHOTT-N-BK7", "property": "refractive_index_nd",
         "value": 1.5168, "reference_wavelength_nm": 587.6},
        {"glass_id": "OHARA-S-BSL7", "property": "refractive_index_nd",
         "value": 1.51633, "reference_wavelength_nm": 587.6},
    ])
    existing.to_csv(path, index=False, encoding="utf-8")
    new = pd.DataFrame([
        {"glass_id": "RII-CAF2-MALITSON", "property": "n_at_reference",
         "value": 1.43385, "reference_wavelength_nm": 587.6},
    ])
    mod._upsert(path, new, ["glass_id", "property", "reference_wavelength_nm"])

    out = pd.read_csv(path, encoding="utf-8")
    assert len(out) == 3
    assert out["value"].notna().all(), out.to_string()
    kept = out[out.glass_id == "SCHOTT-N-BK7"]
    assert float(kept.iloc[0]["value"]) == pytest.approx(1.5168)


def test_upsert_replaces_matching_keys_rather_than_duplicating(tmp_path):
    """Re-running the merge must update in place, not accumulate rows."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "merge_ri2", Path(__file__).resolve().parents[1] /
        "scripts" / "merge_refractiveindex.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    path = tmp_path / "p.csv"
    row = {"glass_id": "RII-CAF2-MALITSON", "property": "n_at_reference",
           "value": 1.0, "reference_wavelength_nm": 587.6}
    pd.DataFrame([row]).to_csv(path, index=False, encoding="utf-8")
    mod._upsert(path, pd.DataFrame([{**row, "value": 1.43385}]),
                ["glass_id", "property", "reference_wavelength_nm"])
    mod._upsert(path, pd.DataFrame([{**row, "value": 1.43385}]),
                ["glass_id", "property", "reference_wavelength_nm"])
    out = pd.read_csv(path, encoding="utf-8")
    assert len(out) == 1
    assert float(out.iloc[0]["value"]) == pytest.approx(1.43385)
