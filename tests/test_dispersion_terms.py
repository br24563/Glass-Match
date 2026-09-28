"""Tests: N-term Sellmeier storage, the n(d) gate, and the archived-curve rule.

Background: the importer used to keep only the first three (B, C) pairs, so a
genuine 4-term fit (NIKON NIFS-V) was silently truncated into a wrong curve.
It also gated on "every C must be positive", which is wrong - OHARA ships
genuine fits with a negative C (S-BSL7) that reproduce n(d) exactly.
"""
import pytest

from glassmatch.spectra import (MAX_TERMS, active_pairs, classify_dispersion,
                                dispersion_curve, n_from_row, pairs_from_row,
                                sellmeier_n)
from glassmatch.importers.agf import is_sellmeier1_formula, parse_agf_text

# N-BK7, the canonical 3-term Sellmeier-1 fit.
BK7 = [1.039612120, 0.00600069867, 0.231792344, 0.0200179144,
       1.010469450, 103.560653]
BK7_ND = 1.516800

# A 4-term fit: NIFS-V. Its 4th pair sits in fields 7-8 of the CD record.
NIFS_V = [0.640349086, 0.004253794, 0.374308316, 0.012779420,
          0.089750539, 0.014004037, 0.908924481, 99.3231891]
NIFS_V_ND = 1.458564

# OHARA S-BSL7: a genuine 3-term fit carrying a NEGATIVE C2.
S_BSL7 = [1.151502, 0.01059841, 0.1185836, -0.01182252, 1.263014, 129.6177]
S_BSL7_ND = 1.51633


def _agf(name, coeffs, nd):
    return (f"NM {name} 2 1 {nd} 64.0 0 1\nGC \n"
            f"CD {' '.join(f'{c:.12E}' for c in coeffs)}\n")


def test_active_pairs_drops_zero_padding():
    assert active_pairs([1.0, 0.01, 2.0, 0.02, 0.0, 0.0]) == [(1.0, 0.01), (2.0, 0.02)]
    assert len(active_pairs(BK7 + [0.0, 0.0, 0.0, 0.0])) == 3


def test_classify_reports_terms_without_judging_signs():
    """A negative C is an observation, never a rejection verdict."""
    n, note = classify_dispersion(S_BSL7)
    assert n == 3
    assert "non-positive" in note
    n, note = classify_dispersion(BK7)
    assert n == 3 and note == ""


def test_sellmeier_n_reproduces_nd():
    assert sellmeier_n(0.5876, (1.03961212, 0.231792344, 1.01046945),
                        (0.00600069867, 0.0200179144, 103.560653)) == \
        pytest.approx(BK7_ND, abs=1e-5)


def test_four_term_fit_is_stored_and_evaluated():
    """The regression this change exists for: B4/C4 used to be dropped."""
    g, p, s, t, issues = parse_agf_text(_agf("NIFS-V", NIFS_V, NIFS_V_ND),
                                        "NIKON", "T")
    row = s.iloc[0]
    assert float(row["B4"]) == pytest.approx(NIFS_V[6])
    assert float(row["C4_um2"]) == pytest.approx(NIFS_V[7])
    assert row["formula"].startswith("Sellmeier")
    assert "4-term" in row["formula"]
    assert is_sellmeier1_formula(row["formula"])
    assert n_from_row(row.to_dict(), 0.5876) == pytest.approx(NIFS_V_ND, abs=2e-3)


def test_negative_c_glass_stays_dispersable():
    """S-BSL7 must not lose its curve to an over-strict physical rule."""
    g, p, s, t, issues = parse_agf_text(_agf("S-BSL7", S_BSL7, S_BSL7_ND),
                                        "OHARA", "T")
    row = s.iloc[0]
    assert is_sellmeier1_formula(row["formula"]), row["formula"]
    assert "non-positive" in row["notes"]


def test_coefficients_that_fail_nd_are_archived_not_evaluated():
    """Series/polynomial CD rows keep their coefficients but are gated off."""
    bogus = [2.188268550, -0.009190447, -0.000111621, 0.009263728,
             0.000073490, 0.000004197]
    g, p, s, t, issues = parse_agf_text(_agf("J-FK5", bogus, 1.487490),
                                        "NIKON", "T")
    row = s.iloc[0]
    assert not is_sellmeier1_formula(row["formula"])
    assert row["formula"].startswith("Non-dispersable")
    assert "never evaluated" in row["formula"]
    assert float(row["B1"]) == pytest.approx(bogus[0])  # verbatim


def test_dispersion_curve_uses_every_stored_term():
    row = {"B1": 0.640349086, "C1_um2": 0.004253794,
           "B2": 0.374308316, "C2_um2": 0.012779420,
           "B3": 0.089750539, "C3_um2": 0.014004037,
           "B4": 0.908924481, "C4_um2": 99.3231891}
    assert len(pairs_from_row(row)) == 4
    curve = dispersion_curve(row, [0.4, 0.5876, 0.7])
    assert curve["n"].between(1.4, 2.0).all()
    assert "4-term" in curve.iloc[0]["note"]


def test_terms_beyond_the_stored_maximum_are_recorded_not_dropped():
    six = [1.0, 0.01, 1.0, 0.02, 1.0, 0.03, 1.0, 0.04, 1.0, 0.05, 1.0, 0.06]
    g, p, s, t, issues = parse_agf_text(_agf("MANY", six, 1.50), "X", "T")
    row = s.iloc[0]
    assert len(pairs_from_row(row.to_dict())) == MAX_TERMS
    # The surplus must survive into the database, not vanish.
    assert "beyond the" in str(g.iloc[0]["description"])
    assert any("beyond the" in str(i.get("issue", "")) for i in issues)


def test_manufacturer_gc_comment_is_not_discarded():
    txt = ("NM GCGLASS 2 1 1.50 64.0 0 1\n"
           "GC suitable for precision molding. step 0.5 available\n"
           "CD 1.0 0.01 1.0 0.02 1.0 0.10 0 0 0 0\n")
    g, p, s, t, issues = parse_agf_text(txt, "X", "T")
    assert "precision molding" in str(g.iloc[0]["description"])


def test_gate_predicate_accepts_both_label_generations():
    """Older databases used the unlabelled-term form; it must still work."""
    assert is_sellmeier1_formula("Sellmeier-1 (Zemax CD record)")
    assert is_sellmeier1_formula("Sellmeier-1 (3-term, Zemax CD record)")
    assert is_sellmeier1_formula("Sellmeier (4-term, Zemax CD record)")
    assert not is_sellmeier1_formula("Non-dispersable (x) - archived, never evaluated")
    assert not is_sellmeier1_formula("Non-Sellmeier CD record (x)")
    assert not is_sellmeier1_formula(None)
    assert not is_sellmeier1_formula("")