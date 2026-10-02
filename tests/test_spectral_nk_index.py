"""``spectral_nk_for`` must not silently drop samples it was given.

A refractiveindex page may publish n and k as two separate tables, and the
normalizer stores them as separate rows that share a wavelength.  The memoized
per-glass index used to be a dict comprehension keyed on wavelength alone, so
whichever row came later *replaced* the earlier one and its half of the data
disappeared - from the Glass Detail table, from the Spectral Analysis plot, and
from ``n_at``'s idea of what the table covers.
"""

import pandas as pd
import pytest

from glassmatch.database import GlassDatabase


def _nk_frame():
    """One wavelength at which n is tabulated, and another where both are."""
    n_rows = pd.DataFrame({
        "glass_id": ["M-SEPARATE", "M-SEPARATE"],
        "wavelength_um": [0.5, 0.6],
        "n": [1.5, 1.6],
        "k": [float("nan"), float("nan")],
        "data_type": ["literature (tabulated n)", "literature (tabulated n)"],
    })
    k_rows = pd.DataFrame({
        "glass_id": ["M-SEPARATE", "M-SEPARATE"],
        "wavelength_um": [0.5, 0.6],
        "n": [float("nan"), float("nan")],
        "k": [0.01, 0.02],
        "data_type": ["literature (tabulated k)", "literature (tabulated k)"],
    })
    return pd.concat([n_rows, k_rows], ignore_index=True)


def _tiny_db():
    return GlassDatabase(spectral_nk=_nk_frame())


def test_separate_n_and_k_rows_at_one_wavelength_both_survive():
    tab = _tiny_db().spectral_nk_for("M-SEPARATE")
    assert tab is not None and len(tab) == 2, tab
    # The old index kept only the last row per wavelength, so one of these
    # two counts was 0 and the other 2.
    assert tab["n"].notna().sum() == 2, tab
    assert tab["k"].notna().sum() == 2, tab
    tab = tab.sort_values("wavelength_um")
    assert list(tab["n"]) == [1.5, 1.6], tab
    assert list(tab["k"]) == [0.01, 0.02], tab


def test_a_merged_row_is_labelled_for_what_it_now_holds():
    """Provenance rule: the label must describe the value that is displayed."""
    tab = _tiny_db().spectral_nk_for("M-SEPARATE")
    labels = set(tab["data_type"])
    assert labels == {"literature (tabulated n,k)"}, labels


def test_an_unmerged_row_keeps_its_own_label():
    single = pd.DataFrame({
        "glass_id": ["M-N-ONLY", "M-N-ONLY"], "wavelength_um": [0.5, 0.6],
        "n": [1.5, 1.6], "k": [float("nan"), float("nan")],
        "data_type": ["literature (tabulated n)"] * 2,
    })
    tab = GlassDatabase(spectral_nk=single).spectral_nk_for("M-N-ONLY")
    assert set(tab["data_type"]) == {"literature (tabulated n)"}, tab


def test_n_at_answers_inside_a_table_that_stores_n_and_k_apart():
    """The user-visible consequence: a coverage hole that is not real.

    With the n rows overwritten, the table looked like it spanned nothing but
    the k wavelengths, so n_at declined a request that the cited page plainly
    answers.
    """
    value, data_type = _tiny_db().n_at("M-SEPARATE", 550.0)
    assert data_type == "interpolated", data_type
    assert value == pytest.approx(1.55), value


# --- the shipped database ---------------------------------------------------
# RII-SI-GREEN-1995 publishes n and k as two tables on one page, so it is the
# case the index used to truncate.  RII-AL2O3-QUERRY is different in kind: it
# carries two rows with *different* values at the same wavelength, which no
# index can serve both of.  Both are pinned by name so a re-import that changes
# either layout is noticed rather than quietly moving the numbers.

def test_silicon_index_answers_across_its_whole_tabulated_range():
    """n(Si) is cited from 0.25 to 1.45 um; the index used to claim 1.01-1.45."""
    db = GlassDatabase.load()
    tab = db.spectral_nk_for("RII-SI-GREEN-1995")
    span = tab.dropna(subset=["n"])["wavelength_um"]
    assert float(span.min()) <= 0.25 and float(span.max()) >= 1.45, (
        float(span.min()), float(span.max()))
    value, data_type = db.n_at("RII-SI-GREEN-1995", 500.0)
    assert data_type == "interpolated", data_type
    assert value == pytest.approx(4.293, abs=1e-9), value


def test_index_serves_every_sample_the_source_states_once():
    """No value may be dropped by the merge; conflicts must be reported instead.

    Where the file gives one value at a wavelength, the index must serve that
    value.  Where it gives two different values for the same column at one
    wavelength the index can only pick one, so the only honest options are to
    serve one of them and say so - and saying so is validation's job, which the
    next test pins.
    """
    from glassmatch.validation import validate_spectral_nk_frame

    db = GlassDatabase.load()
    raw = db.spectral_nk
    flagged = {(i["row"]) for i in validate_spectral_nk_frame(raw)}
    offenders, conflicts = [], []
    for gid, grp in raw.groupby("glass_id", sort=False):
        tab = db.spectral_nk_for(str(gid))
        for col in ("n", "k"):
            served = dict(zip(tab["wavelength_um"], tab[col]))
            held = grp.dropna(subset=[col])
            for wl, vals in held.groupby("wavelength_um")[col].agg(list).items():
                distinct = sorted({round(float(v), 12) for v in vals})
                got = served.get(wl)
                got = None if got is None or pd.isna(got) else round(float(got), 12)
                if len(distinct) == 1:
                    if got != distinct[0]:
                        offenders.append(f"{gid} @ {wl} um: served {got}, "
                                         f"source says {distinct[0]}")
                else:
                    conflicts.append((gid, wl, col, distinct))
                    if got not in distinct:
                        offenders.append(f"{gid} @ {wl} um: served {got}, "
                                         f"invented - source says {distinct}")
                    rows = held.index[held["wavelength_um"] == wl]
                    assert all(r in flagged for r in rows), (gid, wl, col, distinct)
    assert not offenders, f"{len(offenders)} losses:\n" + "\n".join(offenders[:5])
    assert conflicts, "expected the shipped data to contain at least one conflict"
