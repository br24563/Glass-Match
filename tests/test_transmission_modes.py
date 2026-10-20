"""Tests: transmission band statistics (Average / Minimum / Entire range)."""
import math

import pandas as pd
import pytest
from glassmatch.spectra import band_stats


def _tdf(rows):
    return pd.DataFrame(rows, columns=["wavelength_um", "transmission", "thickness_mm"])


FULL = _tdf([(w / 1000.0, t, 25.0) for w, t in
             [(400, 0.90), (450, 0.94), (500, 0.96), (550, 0.97),
              (600, 0.97), (650, 0.95), (700, 0.92)]])

SPARSE = _tdf([(0.40, 0.90, 25.0), (0.45, 0.94, 25.0)])  # only 0.40-0.45 of a 0.40-0.70 band


def test_average_mode_returns_mean_pct():
    s = band_stats(FULL, 0.40, 0.70, "Average")
    assert s is not None and s["value_pct"] is not None
    expected = sum(t for _, t, _ in FULL.itertuples(index=False)) / len(FULL) * 100
    assert abs(s["value_pct"] - expected) < 1e-6
    assert "manufacturer" in s["label"] and "mean" in s["label"]


def test_minimum_mode_returns_worst_sample():
    s = band_stats(FULL, 0.40, 0.70, "Minimum")
    assert abs(s["value_pct"] - 90.0) < 1e-6
    assert "minimum" in s["label"]


def test_entire_range_passes_with_full_coverage():
    s = band_stats(FULL, 0.40, 0.70, "Entire range")
    assert s is not None and abs(s["value_pct"] - 90.0) < 1e-6
    assert s["coverage"] >= 0.90


def test_entire_range_fails_on_sparse_coverage_not_guess():
    s = band_stats(SPARSE, 0.40, 0.70, "Entire range")
    assert s is not None and s["value_pct"] is None
    assert s["reason"] == "insufficient-coverage"


def test_average_still_works_on_sparse_coverage():
    s = band_stats(SPARSE, 0.40, 0.70, "Average")
    assert s is not None and s["value_pct"] is not None  # honest partial data


def test_no_samples_in_band():
    s = band_stats(FULL, 1.0, 1.2, "Average")
    assert s is not None and s["value_pct"] is None
    assert s["reason"] == "no-samples-in-band"


def test_none_or_empty_input():
    assert band_stats(None, 0.4, 0.7, "Average") is None
    assert band_stats(FULL.iloc[0:0], 0.4, 0.7, "Average") is None


def test_inverted_band_rejected():
    assert band_stats(FULL, 0.7, 0.4, "Average") is None


def test_conflicting_duplicates_excluded_not_pick_winner():
    tdf = _tdf([(0.50, 0.95, 10.0),   # sane
                (0.55, 0.96, 10.0),
                (0.55, 1e-6, 10.0),   # conflicting duplicate at 0.55
                (0.60, 0.97, 10.0)])
    s = band_stats(tdf, 0.50, 0.60, "Minimum")
    assert s is not None and s["value_pct"] is not None
    # 0.55 row pair excluded entirely; min of remaining = 0.95
    assert abs(s["value_pct"] - 95.0) < 1e-6
    assert "conflicting duplicate" in s["label"] and "excluded" in s["label"]
    assert s["n_points"] == 2


def test_identical_duplicates_are_not_conflicts():
    tdf = _tdf([(0.50, 0.95, 10.0), (0.50, 0.95, 10.0), (0.60, 0.97, 10.0)])
    s = band_stats(tdf, 0.50, 0.60, "Minimum")
    assert s is not None and "excluded" not in s["label"]
    assert abs(s["value_pct"] - 95.0) < 1e-6


def test_all_samples_conflicting_returns_missing_not_number():
    tdf = _tdf([(0.50, 0.95, 10.0), (0.50, 1e-6, 10.0)])
    s = band_stats(tdf, 0.45, 0.55, "Average")
    assert s is not None and s["value_pct"] is None
    assert s["reason"] == "all-samples-conflict"


# --- thickness normalisation ----------------------------------------------
# Catalogs list internal transmittance at different thicknesses (SCHOTT 25 mm,
# most others 10 mm). Compared raw, a 25 mm glass looks worse than it is.

def test_beer_lambert_scaling():
    from glassmatch.spectra import scale_internal_transmittance as scale
    assert scale(0.95, 25.0, 10.0) == pytest.approx(0.95 ** 0.4)
    assert scale(0.95, 25.0, 10.0) == pytest.approx(0.97969, abs=1e-5)
    assert scale(0.95, 10.0, 10.0) == pytest.approx(0.95)
    assert scale(0.0, 25.0, 10.0) == 0.0 and scale(1.0, 25.0, 10.0) == 1.0
    assert math.isnan(scale(0.95, 0.0, 10.0))   # 0 mm says nothing per mm


def test_scaling_flips_a_raw_ranking():
    thick = _tdf([(0.5, 0.95, 25.0), (0.6, 0.95, 25.0)])   # SCHOTT-style
    thin = _tdf([(0.5, 0.96, 10.0), (0.6, 0.96, 10.0)])
    raw = [band_stats(x, 0.5, 0.6, "Average")["value_pct"] for x in (thick, thin)]
    assert raw[0] < raw[1]
    same = [band_stats(x, 0.5, 0.6, "Average", thickness_mm=10.0)["value_pct"]
            for x in (thick, thin)]
    assert same[0] > same[1]
    s = band_stats(thick, 0.5, 0.6, "Average", thickness_mm=10.0)
    assert "scaled from 25 mm as listed to 10 mm" in s["label"]
    s = band_stats(thin, 0.5, 0.6, "Average", thickness_mm=10.0)
    assert "10 mm as listed" in s["label"] and "scaled" not in s["label"]


def test_samples_without_a_usable_thickness_are_excluded_and_disclosed():
    # NIKON Q-FK01AS lists its first two IT samples at 1 mm and the rest at
    # 0 mm - a catalog defect. Those cannot be converted, only disclosed.
    tdf = _tdf([(0.5, 0.97, 1.0), (0.55, 0.98, 0.0), (0.6, 0.99, 0.0)])
    s = band_stats(tdf, 0.5, 0.6, "Average", thickness_mm=10.0)
    assert s["n_points"] == 1
    assert s["value_pct"] == pytest.approx(0.97 ** 10 * 100)
    assert "2 sample(s) excluded" in s["label"]
    only_zero = _tdf([(0.5, 0.97, 0.0), (0.6, 0.98, 0.0)])
    s = band_stats(only_zero, 0.5, 0.6, "Average", thickness_mm=10.0)
    assert s["value_pct"] is None and s["reason"] == "no-usable-thickness"


def test_mixed_thickness_glass_is_scaled_per_sample():
    # SCHOTT BAF50 lists some samples at 5 mm and the rest at 25 mm.
    tdf = _tdf([(0.5, 0.90, 5.0), (0.6, 0.90, 25.0)])
    s = band_stats(tdf, 0.5, 0.6, "Minimum", thickness_mm=10.0)
    assert s["value_pct"] == pytest.approx(0.90 ** 2 * 100)
    assert "5/25 mm as listed" in s["label"]
