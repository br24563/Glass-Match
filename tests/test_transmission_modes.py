"""Tests: transmission band statistics (Average / Minimum / Entire range)."""
import pandas as pd
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
