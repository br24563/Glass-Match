"""SCHOTT's IRG chalcogenide glasses: the official .agf with transmission,
its fits verified against SCHOTT's own datasheets."""
import pandas as pd
import pytest

from glassmatch.database import DEFAULT_DATA_DIR, load_default_database

SHEETS = DEFAULT_DATA_DIR.parent / "validation" / "schott_irg_datasheets.csv"


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def test_datasheet_extract():
    d = pd.read_csv(SHEETS)
    assert set(d["glass_id"]) == {f"SCHOTT-IRG{i}" for i in (22, 24, 25, 26, 27)}
    assert len(d) == 74
    r = d[(d.glass_id == "SCHOTT-IRG25") & (d.wavelength_um == 10.0)].iloc[0]
    assert r["n_22c"] == 2.6030 and r["dn_dt_abs_1e6_per_k"] == 61.1
    # Negative dn/dT printed with a typographic minus is read as negative.
    assert d.loc[(d.glass_id == "SCHOTT-IRG27") & (d.wavelength_um == 12.0),
                 "dn_dt_abs_1e6_per_k"].iloc[0] == -3.7


def test_fits_verified_only_where_they_match_the_datasheet():
    s = pd.read_csv(DEFAULT_DATA_DIR / "sellmeier.csv", dtype=str,
                    keep_default_na=False).set_index("glass_id")
    for g in ("SCHOTT-IRG22", "SCHOTT-IRG24", "SCHOTT-IRG25"):
        assert not s.loc[g, "formula"].startswith("Non-dispersable")
        assert "Maker table check" in s.loc[g, "notes"]
    for g in ("SCHOTT-IRG26", "SCHOTT-IRG27"):          # 2.1e-4 and 3e-3 off
        assert s.loc[g, "formula"].startswith("Non-dispersable")
        assert "FAILED" in s.loc[g, "notes"]


def test_lwir_transmission_and_dispersion(db):
    from glassmatch import band as B
    from glassmatch.transmission import band_transmission
    tg = {str(g): x for g, x in db.transmission.groupby("glass_id")}
    v, basis = band_transmission(db, "SCHOTT-IRG25", 8, 12, "Average",
                                 t_groups=tg, nk_groups={}, thickness_mm=10)
    assert v is not None and v > 80 and basis.startswith("manufacturer")
    f = B.band_figures(db, "SCHOTT-IRG25", B.PRESETS["LWIR (8 / 10 / 12 um)"])
    assert f is not None and 100 < f["v_band"] < 250


def test_td_record_matches_datasheet_dndt(db):
    from glassmatch.spectra import delta_n_abs
    from glassmatch.thermal import td_record
    d = pd.read_csv(SHEETS).dropna(subset=["dn_dt_abs_1e6_per_k"])
    for gid, g in d.groupby("glass_id"):
        td = td_record(db, gid)
        diffs = [abs((delta_n_abs(td, r.n_22c, r.wavelength_um, 22.5)
                      - delta_n_abs(td, r.n_22c, r.wavelength_um, 21.5)) * 1e6
                     - r.dn_dt_abs_1e6_per_k) for r in g.itertuples()]
        assert max(diffs) < 0.7, gid
