"""Tests: refractiveindex.info (CC0) crystal pages -> GlassMatch frames.

The coefficient layout in an upstream "formula 1" page is the thing most
likely to be got wrong, so it is pinned against published values here:

  * the list is ``[T, B1, C1, B2, C2, ...]`` - INTERLEAVED, not grouped;
  * each C is a resonance WAVELENGTH in um and must be squared.

Reading it as grouped B's then C's returns a smooth-looking but wrong curve
(n ~ 1.258 at the d-line for CaF2 instead of 1.4338), so these assertions
compare against the literature rather than against our own output.
"""
from pathlib import Path

import pandas as pd
import pytest

from glassmatch.importers.refractiveindex_yaml import (REFERENCE_UM,
                                                       n_from_rii_formula,
                                                       parse_ri_page)

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


def test_unsupported_formulas_are_reported_not_guessed(tmp_path):
    for kind in ("formula 2", "formula 4", "formula 5", "formula 7"):
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
