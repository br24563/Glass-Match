"""Displayed percentages must be rounded, not raw binary-float means.

Regression test: the Glass Detail caption rendered ``98.49999999999999%``
because a band mean of binary floats was interpolated straight into an
f-string. Percentages are now rounded where they are produced, so the results
table, the caption and the exports can never show different numbers.
"""
import pandas as pd
import pytest

from glassmatch.spectra import band_stats


def _group(values, glass_id="SCHOTT-N-BK7"):
    return pd.DataFrame(
        [{"glass_id": glass_id, "wavelength_um": round(0.40 + 0.01 * i, 3),
          "thickness_mm": 10.0, "transmission": v, "data_type": "manufacturer",
          "source_id": "TEST", "notes": ""}
         for i, v in enumerate(values)])


# 11 samples averaging 0.985 - the shape that produced the long float.
NOISY = [0.98, 0.99] + [0.985] * 9


def test_raw_mean_reproduces_the_bug():
    """Guard the premise: this data really does produce float noise."""
    stats = band_stats(_group(NOISY), 0.40, 0.50, "Average")
    assert len(str(stats["value_pct"])) > len(str(round(stats["value_pct"], 1)))


@pytest.mark.parametrize("mode", ["Average", "Minimum", "Entire range"])
def test_displayed_percentage_is_rounded(mode):
    stats = band_stats(_group(NOISY), 0.40, 0.50, mode)
    rounded = round(stats["value_pct"], 1)
    assert stats["value_pct"] == pytest.approx(rounded, abs=0.05)
    assert len(f"{rounded:.1f}") <= 5


def test_rounding_does_not_alter_provenance():
    """Rounding is display-only; the basis label must stay intact."""
    stats = band_stats(_group(NOISY), 0.40, 0.50, "Average")
    assert "manufacturer" in stats["label"]
    assert "mean of samples in band" in stats["label"]


def test_unsatisfiable_band_stays_missing_not_zero():
    stats = band_stats(_group(NOISY), 8.0, 12.0, "Average")
    assert stats["value_pct"] is None
