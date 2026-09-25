"""Transmission conflict detection, quarantine, and the migration contract."""
import math

import pandas as pd
import pytest

from glassmatch.validation import (CONFLICT_COLUMNS, TRANSMISSION_KEY,
                                   find_transmission_conflicts,
                                   split_transmission_conflicts)


def _t(rows):
    """rows: (glass_id, wl_um, thickness, transmission, source)"""
    return pd.DataFrame(
        [{"glass_id": g, "wavelength_um": w, "thickness_mm": th,
          "transmission": v, "data_type": "manufacturer", "source_id": s,
          "notes": ""} for g, w, th, v, s in rows])


# The two real shapes seen in manufacturer catalogs: a stray 1E-6 artifact
# beside a real reading, and a genuine disagreement between catalog sections.
CONFLICTED = _t([
    ("LZOS-LZ_F1", 1.5, 10.0, 0.996, "LZOS-AGF"),
    ("LZOS-LZ_F1", 1.5, 10.0, 1e-06, "LZOS-AGF"),   # artifact
    ("CDGM-H-LAF2", 2.4, 10.0, 0.800, "CDGM-AGF"),
    ("CDGM-H-LAF2", 2.4, 10.0, 0.843, "CDGM-AGF"),   # genuine disagreement
    ("SCHOTT-N-BK7", 0.50, 10.0, 0.998, "SCHOTT-AGF"),   # undisputed
    ("SCHOTT-N-BK7", 0.51, 10.0, 0.997, "SCHOTT-AGF"),
])


def test_detects_conflicting_keys():
    c = find_transmission_conflicts(CONFLICTED)
    assert len(c) == 2
    assert set(c["glass_id"]) == {"LZOS-LZ_F1", "CDGM-H-LAF2"}
    assert list(c.columns) == CONFLICT_COLUMNS


def test_all_distinct_values_are_preserved_never_collapsed():
    """The point of the ledger: nothing is decided, both numbers survive."""
    c = find_transmission_conflicts(CONFLICTED).set_index("glass_id")
    assert c.loc["LZOS-LZ_F1", "n_values"] == 2
    vals = {float(v) for v in c.loc["LZOS-LZ_F1", "values"].split("; ")}
    assert vals == {0.996, 1e-06}
    assert c.loc["CDGM-H-LAF2", "values"].split("; ") == ["0.8", "0.843"]
    assert c.loc["CDGM-H-LAF2", "spread"] == pytest.approx(0.043)


def test_undisputed_rows_are_not_flagged():
    c = find_transmission_conflicts(CONFLICTED)
    assert "SCHOTT-N-BK7" not in set(c["glass_id"])


def test_identical_duplicates_are_not_a_conflict():
    """The same value twice is a harmless duplicate, not a disagreement."""
    t = _t([("A", 0.5, 10.0, 0.9, "S"), ("A", 0.5, 10.0, 0.9, "S")])
    assert find_transmission_conflicts(t).empty


def test_thickness_and_glass_are_part_of_the_key():
    t = _t([("A", 0.5, 10.0, 0.9, "S"),
            ("A", 0.5, 25.0, 0.8, "S"),     # different thickness -> fine
            ("B", 0.5, 10.0, 0.7, "S")])    # different glass -> fine
    assert find_transmission_conflicts(t).empty


def test_split_quarantines_every_row_of_a_conflicting_key():
    clean, conflicts, dropped = split_transmission_conflicts(CONFLICTED)
    assert len(clean) == 2 and len(dropped) == 4 and len(conflicts) == 2
    assert "SCHOTT-N-BK7" in set(clean["glass_id"])
    # both rows of each conflict are removed, not just one
    for gid in ("LZOS-LZ_F1", "CDGM-H-LAF2"):
        assert (clean["glass_id"] == gid).sum() == 0
        assert (dropped["glass_id"] == gid).sum() == 2


def test_split_is_a_noop_on_clean_data():
    clean, conflicts, dropped = split_transmission_conflicts(
        _t([("A", 0.5, 10.0, 0.9, "S"), ("A", 0.6, 10.0, 0.8, "S")]))
    assert conflicts.empty
    assert dropped.empty
    assert len(clean) == 2


def test_split_preserves_unaffected_rows_verbatim():
    clean, _, _ = split_transmission_conflicts(CONFLICTED)
    row = clean[clean["glass_id"] == "SCHOTT-N-BK7"].iloc[0]
    assert row["wavelength_um"] == 0.50
    assert row["transmission"] == pytest.approx(0.998)
    assert row["source_id"] == "SCHOTT-AGF"
    assert row["data_type"] == "manufacturer"


def test_split_handles_non_default_index():
    """A merge-based mask breaks on a duplicated index; tuple keys must not."""
    t = CONFLICTED.copy()
    t.index = [0] * len(t)
    clean, conflicts, dropped = split_transmission_conflicts(t)
    assert len(conflicts) == 2
    assert len(clean) == 2
    assert len(dropped) == 4


def test_empty_and_malformed_inputs():
    assert find_transmission_conflicts(pd.DataFrame()).empty
    assert find_transmission_conflicts(None).empty
    missing_cols = pd.DataFrame([{"glass_id": "A", "wavelength_um": 0.5}])
    assert find_transmission_conflicts(missing_cols).empty


def test_non_numeric_values_do_not_crash():
    t = _t([("A", 0.5, 10.0, math.nan, "S"), ("A", 0.5, 10.0, math.nan, "S")])
    assert find_transmission_conflicts(t).empty


def test_conflict_rows_are_labelled_for_review():
    c = find_transmission_conflicts(CONFLICTED)
    assert (c["status"] == "quarantined").all()
    assert c["reason"].str.contains("does not choose a winner").all()
    assert c["action"].str.contains("excluded from band statistics").all()
    assert (c["source_ids"] == "LZOS-AGF").any()
    assert (c["data_types"] == "manufacturer").all()


def test_committed_database_has_no_live_conflicts():
    """The shipped data must already be clean; the ledger is the record."""
    from pathlib import Path
    from glassmatch.database import load_default_database
    db = load_default_database()
    assert find_transmission_conflicts(db.transmission).empty
    ledger = Path("data/normalized/transmission_conflicts.csv")
    if ledger.exists():
        saved = pd.read_csv(ledger)
        assert len(saved) > 0
        assert set(CONFLICT_COLUMNS).issubset(saved.columns)
        # every quarantined key really is gone from the database
        for _, r in saved.iterrows():
            hit = db.transmission[
                (db.transmission["glass_id"] == r["glass_id"]) &
                (db.transmission["wavelength_um"] == r["wavelength_um"])]
            assert hit.empty
