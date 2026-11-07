"""n(lambda, T) from measured temperature series of crystals - the cryogenic
data GlassMatch holds - interpolated in T, never beyond the series."""
import pytest

from glassmatch import thermal as T
from glassmatch.database import load_default_database


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def test_series_are_found_and_films_are_not(db):
    s = T.temperature_series(db, "RII-SI-LI-293K")
    assert len(s) == 14 and s[0][1] == "RII-SI-LI-100K"
    assert T.temperature_series(db, "RII-CAF2-BOSOMWORTH-5K")[0][0] == pytest.approx(-268.15)
    assert T.temperature_series(db, "RII-SI-KARAMAN-20C") == []      # a-Si films
    assert T.temperature_series(db, "SCHOTT-N-BK7") == []


def test_measured_temperatures_are_exact_and_between_is_linear(db):
    lo = T.index_at(db, "RII-SI-LI-293K", 4000, -173.15)
    hi = T.index_at(db, "RII-SI-LI-293K", 4000, -123.15)
    mid = T.index_at(db, "RII-SI-LI-293K", 4000, -148.15)
    assert lo["n"] == pytest.approx(db.n_at("RII-SI-LI-100K", 4000)[0], abs=1e-12)
    assert mid["n"] == pytest.approx((lo["n"] + hi["n"]) / 2, abs=1e-12)
    assert "measured temperature series" in mid["method"]
    assert "as published" in mid["basis"]


def test_outside_the_series_is_refused(db):
    r = T.index_at(db, "RII-GE-LI-293K", 10000, -196.0)
    assert r["n"] is None and "not extrapolated" in r["reason"]


def test_dndt_from_series_matches_known_values(db):
    # Ge at 10 um near room temperature: ~4e-4/K (literature ~396e-6/K).
    d = T.dn_dt(db, "RII-GE-LI-293K", 10000, 0, 40)
    assert 360 < d["dn_dt"] < 440
    # Si's dn/dT falls on cooling.
    cold = T.dn_dt(db, "RII-SI-LI-293K", 4000, -150, -100)["dn_dt"]
    warm = T.dn_dt(db, "RII-SI-LI-293K", 4000, 0, 50)["dn_dt"]
    assert 0 < cold < warm
