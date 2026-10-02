"""Tests: transmission precedence — manufacturer → tabulated n/k → Fresnel.

`glassmatch.band_transmission` decides what the matching table, the detail tab
and the CSV export all report as a glass's transmission. Getting the order
wrong is not a cosmetic bug: a Fresnel number shown where measured internal
transmittance was asked for is an unlabelled fabrication, and the whole point
of the chain is that each branch names its own basis.

These cases were characterized against the code *before* it moved out of
`app.py` (22/22 checks against the shipped text, extracted by AST so the real
source was under test), and the same expectations are pinned here afterwards.

Not covered by construction: a glass whose manufacturer rows exist, are in
band, *and* are sparser than "Entire range" requires, must report missing —
see the coverage case below.
"""
import numpy as np
import pandas as pd

from glassmatch.database import GlassDatabase
from glassmatch.spectra import fresnel_transmission, sellmeier_n
from glassmatch.transmission import band_transmission, n_at, transmission_estimate

LO, HI = 0.40, 0.70
SELLMEIER = {"formula": "Sellmeier (3-term)",
             "B1": 1.03961212, "B2": 0.231792344, "B3": 1.01046945,
             "C1_um2": 0.00600069867, "C2_um2": 0.0200179144, "C3_um2": 103.560653}
GIDS = ("G-MFR", "G-NK", "G-FRESNEL", "G-NOTHING", "G-SPARSE",
        "G-MFR-FRESNEL", "G-NKOUT")


def _db():
    return GlassDatabase(
        glasses=pd.DataFrame([{"glass_id": g, "glass": g, "manufacturer_id": "M"}
                              for g in GIDS]),
        sellmeier=pd.DataFrame([dict(SELLMEIER, glass_id="G-FRESNEL"),
                                dict(SELLMEIER, glass_id="G-MFR-FRESNEL"),
                                dict(SELLMEIER, glass_id="G-SPARSE"),
                                dict(SELLMEIER, glass_id="G-NKOUT")]),
        transmission=pd.DataFrame(),
        spectral_nk=pd.DataFrame(),
    )


def _tdf(rows):
    return pd.DataFrame([{"wavelength_um": w, "transmission": t,
                          "thickness_mm": 10.0} for w, t in rows])


def _nkdf(rows, gid="G-NK"):
    return pd.DataFrame([{"glass_id": gid, "wavelength_um": w, "n": n, "k": k,
                          "measurement_form": "bulk", "data_type": "literature",
                          "source_id": "SRC"} for w, n, k in rows])


def _groups():
    t_groups = {
        "G-MFR": _tdf([(0.40, 0.90), (0.50, 0.95), (0.60, 0.97), (0.70, 0.96)]),
        # rows exist, but only at 1.0-1.2 um: must be reported missing
        "G-MFR-FRESNEL": _tdf([(1.00, 0.98), (1.10, 0.97), (1.20, 0.96)]),
        # in band, but spanning only 0.45-0.65 (67% < 90%)
        "G-SPARSE": _tdf([(0.45, 0.95), (0.55, 0.96), (0.65, 0.97)]),
    }
    nk_groups = {
        # k small enough that a 10 mm blank attenuates rather than saturates:
        # the thickness assumption has to show up in the answer.
        "G-NK": _nkdf([(0.40, 1.76, 0.0), (0.50, 1.77, 0.0), (0.60, 1.78, 1e-6),
                       (0.70, 1.79, 2e-6)]),
        # tabulated but outside the band, with a verified Sellmeier row waiting:
        # reporting missing proves this branch cannot fall through to Fresnel
        "G-NKOUT": _nkdf([(1.00, 1.70, 1e-6), (1.10, 1.71, 1e-6)], gid="G-NKOUT"),
    }
    return t_groups, nk_groups



def _bt(gid, mode="Average", thickness_mm=10.0):
    t_groups, nk_groups = _groups()
    return band_transmission(_db(), gid, LO, HI, mode,
                             t_groups=t_groups, nk_groups=nk_groups,
                             thickness_mm=thickness_mm)


def test_manufacturer_rows_win_and_keep_their_label():
    """Highest precedence: measured rows answer, and answer as themselves."""
    from glassmatch.spectra import band_stats
    t_groups, _ = _groups()
    expected = band_stats(t_groups["G-MFR"], LO, HI, "Average")
    val, basis = _bt("G-MFR")
    assert val == round(float(expected["value_pct"]), 1)
    assert basis == expected["label"]
    assert "calculated" not in basis


def test_manufacturer_rows_out_of_band_report_missing_not_fresnel():
    """The glass HAS measured rows (and a Sellmeier row) — but none in band.

    Returning the Fresnel estimate here would replace "we have no measurement
    for the band you asked about" with a number that looks like one.
    """
    val, basis = _bt("G-MFR-FRESNEL")
    assert val is None
    assert basis == "missing (manufacturer rows exist but none inside the band)"
    assert not basis.startswith("calculated")


def test_sparse_manufacturer_rows_cannot_claim_the_entire_range():
    """Entire range spans 67% of the band; the claim would be false."""
    val, basis = _bt("G-SPARSE", mode="Entire range")
    assert val is None
    assert basis == ("missing (manufacturer coverage 67% of band "
                     "(<90% required for Entire range))")
    assert not basis.startswith("calculated")


def test_tabulated_nk_answers_when_there_are_no_manufacturer_rows():
    """Crystals publish n/k, not a transmittance curve — 195 materials."""
    from glassmatch.spectra import band_stats_nk
    _, nk_groups = _groups()
    expected = band_stats_nk(nk_groups["G-NK"], LO, HI, "Average", 10.0)
    val, basis = _bt("G-NK")
    assert val == round(float(expected["value_pct"]), 1)
    assert basis == "calculated from tabulated n/k at 10 mm, 4 samples"
    assert basis.startswith("calculated")


def test_assumed_thickness_changes_value_and_is_stated():
    """A calculated figure without its thickness assumption is not a fact."""
    val10, basis10 = _bt("G-NK", thickness_mm=10.0)
    val35, basis35 = _bt("G-NK", thickness_mm=3.5)
    assert basis35 == "calculated from tabulated n/k at 3.5 mm, 4 samples"
    assert basis10 != basis35
    assert val35 > val10


def test_nk_out_of_band_reports_missing_not_fresnel():
    """Same rule one level down: tabulated data that cannot answer says so,
    even though a verified Sellmeier row is ready to produce a Fresnel number.
    """
    val, basis = _bt("G-NKOUT")
    assert val is None
    assert basis == ("missing (tabulated n/k exist but none inside the band "
                     "(10 mm))")
    assert not basis.startswith("calculated")


def test_fresnel_is_the_last_resort_and_is_labelled_calculated():
    """No manufacturer rows, no tabulated n/k: estimate from Sellmeier."""
    val, basis = _bt("G-FRESNEL")
    assert basis == "calculated (Fresnel, uncoated)"
    B = (1.03961212, 0.231792344, 1.01046945)
    C = (0.00600069867, 0.0200179144, 103.560653)
    vals = [fresnel_transmission(sellmeier_n(float(w), B, C))
            for w in np.linspace(LO, HI, 12)]
    assert val == round(float(sum(vals) / len(vals) * 100.0), 1)


def test_no_data_at_all_invents_nothing():
    val, basis = _bt("G-NOTHING")
    assert val is None
    assert basis == "missing (no Sellmeier data)"


def test_every_returned_value_is_one_decimal_place():
    """Table, caption and CSV export must all show the same number."""
    t_groups, nk_groups = _groups()
    t_groups["G-MFR"] = _tdf([(0.50, 0.98437)])
    val, _ = band_transmission(_db(), "G-MFR", LO, HI, "Average",
                               t_groups=t_groups, nk_groups=nk_groups,
                               thickness_mm=10.0)
    assert val == 98.4 and val == round(val, 1)


# --- the two helpers the chain is built from --------------------------------

def test_n_at_only_evaluates_verified_sellmeier_rows():
    db = _db()
    assert n_at(db, "G-FRESNEL", 0.5876) is not None
    assert n_at(db, "G-NOTHING", 0.5876) is None


def test_transmission_estimate_is_labelled_and_declines_without_data():
    db = _db()
    val, basis = transmission_estimate(db, "G-FRESNEL", LO, HI)
    assert val is not None and basis == "calculated (Fresnel, uncoated)"
    val, basis = transmission_estimate(db, "G-NOTHING", LO, HI)
    assert val is None and basis == "missing (no Sellmeier data)"

