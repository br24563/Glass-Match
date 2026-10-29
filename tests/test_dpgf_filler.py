"""dPgF = 0 in an .agf ED record: a real value, or the catalog's filler?

Zemax has no "not given" marker in ED, so HOYA, OHARA and the IR/polymer
files write 0 for glasses whose dPgF they do not publish; before this check
OHARA's FPL51 was stored as dPgF 0 (its workbook gives +0.0280). A real 0 does
exist - K7, F2 and C7 define the normal lines - so each 0 is judged against
the glass's own fit (zero_dpgf_verdicts).
"""
import datetime as dt

import pytest

from glassmatch.database import load_default_database
from glassmatch.export_agf import export_agf
from glassmatch.importers.agf import parse_agf_text, zero_dpgf_verdicts


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def _schott_catalog(db, zero_out=()):
    """A real SCHOTT selection written as .agf, with some dPgF set to 0."""
    ids = [g for g in db.glass_ids() if g.startswith("SCHOTT-")][:60]
    ids += ["SCHOTT-K7", "SCHOTT-N-K5", "SCHOTT-SF6"]
    ex = export_agf(db, ids, today=dt.date(2026, 10, 28))
    text = ex.text
    for gid in zero_out:
        name = next(n for n, g in ex.exported.items() if g == gid)
        block = text.split(f"NM {name} ", 1)[1]
        ed = next(ln for ln in block.split("\r\n") if ln.startswith("ED "))
        parts = ed.split()
        parts[4] = "0.0"
        text = text.replace(ed, " ".join(parts), 1)
    return text


def _dpgf(p, gid):
    hit = p[(p["glass_id"] == gid) & (p["property"] == "dPgF")]
    return float(hit["value"].iloc[0]) if len(hit) else None


def test_filler_zero_dropped_real_zero_kept(db):
    text = _schott_catalog(db, zero_out=["SCHOTT-SF6"])      # really +0.0092
    g, p, s, t, issues = parse_agf_text(text, "SCHOTT", "T")
    assert _dpgf(p, "SCHOTT-SF6") is None
    assert _dpgf(p, "SCHOTT-K7") == 0.0                       # normal-line glass
    assert _dpgf(p, "SCHOTT-N-K5") == 0.0
    desc = g.set_index("glass_id").loc["SCHOTT-SF6", "description"]
    assert "dPgF 0 not stored" in desc and "+0.009" in desc
    assert any(i["issue"].startswith("dPgF 0 dropped") for i in issues)


def test_catalog_with_no_nonzero_dpgf_has_no_dpgf(db):
    ids = [g for g in db.glass_ids() if g.startswith("SCHOTT-")][:20]
    text = export_agf(db, ids).text
    lines = []
    for ln in text.split("\r\n"):
        if ln.startswith("ED "):
            parts = ln.split()
            parts[4] = "0.0"
            ln = " ".join(parts)
        lines.append(ln)
    _, p, _, _, _ = parse_agf_text("\r\n".join(lines), "SCHOTT", "T")
    assert not (p["property"] == "dPgF").any()


@pytest.mark.parametrize("gid", ["SCHOTT-K7", "SCHOTT-N-K5", "CDGM-H-K6",
                                 "CDGM-H-BAK1", "OHARA-S-TIL2", "OHARA-S-LAH93"])
def test_published_zero_survives_in_database(db, gid):
    # Each of these is a 0 in the maker's own Excel workbook too.
    assert db.property_value(gid, "dPgF") == 0.0


@pytest.mark.parametrize("gid", ["OHARA-FPL51", "OHARA-FPL53", "OHARA-BSL7",
                                 "SCHOTT-SF6G05", "INFRARED-CDTE", "CDGM-HWS1"])
def test_filler_zero_gone_from_database(db, gid):
    assert db.property_value(gid, "dPgF") is None
    assert "dPgF 0 not stored" in db.get_glass_row(gid)["description"]


def test_database_has_no_unconfirmed_zero(db):
    p = db.properties
    for sid, part in p.groupby("source_id"):
        ids = set(part["glass_id"])
        sell = db.sellmeier[db.sellmeier["glass_id"].isin(ids)]
        v = zero_dpgf_verdicts(part.to_dict(orient="records"),
                               sell.to_dict(orient="records"))
        assert all(keep for keep, _, _ in v.values()), sid


def test_export_header_flags_missing_dpgf(db):
    ex = export_agf(db, ["SCHOTT-SF6G05"])
    assert "dPgF not given (ED carries 0)" in ex.text
