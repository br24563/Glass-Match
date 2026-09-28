"""ED-record field gating: every field is judged on its own.

Regression tests for a bug that silently discarded valid data for ~700
glasses. `_ed_block` used to gate density behind the CTE fields, so any vendor
leaving a 0.0 placeholder in a CTE slot lost its density too:

    CDGM   "ED 0.000000 8.200000 2.300000 -0.000600 0"  -> density 2.30 was dropped
    HIKARI "ED 5.800000 0.000000 4.970000 -0.008600 0"  -> density 4.97 was dropped

A missing CTE is missing, not a reason to throw away a real measurement, and
CTE(-30/+70) and CTE(20/+300) are different quantities that must never be
collapsed into one property.
"""
import pytest

from glassmatch.importers.agf import parse_agf_text

NM = "NM {name} 1 1 517642.251 {nd} 64.17 0 1\n"


def _props(ed_line, material_class="oxide_glass", name="TESTG"):
    text = NM.format(name=name, nd="1.51680") + ed_line
    _, p, _, _, _ = parse_agf_text(text, "TEST", "TEST-AGF", material_class)
    out = {}
    for _, r in p.iterrows():
        out.setdefault(r["property"], []).append(float(r["value"]))
    return out


# --- the regression itself: density must survive a zeroed CTE slot ---------

@pytest.mark.parametrize("ed,expected", [
    ("ED 0.000000 8.200000 2.300000 -0.000600 0\n", 2.30),   # CDGM shape
    ("ED 5.800000 0.000000 4.970000 -0.008600 0\n", 4.97),   # HIKARI/NIKON shape
    ("ED 0.000000 0.000000 2.450000 0.002700 0\n", 2.45),    # no CTE at all
    ("ED 7.100000 8.300000 2.510000 -0.000900 0\n", 2.51),   # SCHOTT, unchanged
])
def test_density_is_not_gated_on_cte_fields(ed, expected):
    got = _props(ed)
    assert "density" in got, f"density dropped for {ed.strip()}"
    assert got["density"] == pytest.approx([expected], abs=1e-9)


def test_cte_absent_when_vendor_does_not_publish_it():
    """A zeroed CTE slot means 'not published' - never inferred or defaulted."""
    got = _props("ED 0.000000 8.200000 2.300000 -0.000600 0\n")
    assert "cte" not in got
    assert got["cte_20_300"] == pytest.approx([8.2])


# --- the two CTEs are distinct quantities ---------------------------------

def test_the_two_ctes_are_separate_properties():
    got = _props("ED 7.100000 8.300000 2.510000 -0.000900 0\n")
    assert got["cte"] == pytest.approx([7.1])
    assert got["cte_20_300"] == pytest.approx([8.3])


def test_never_two_cte_rows_for_one_glass():
    """The old map sent both CTE slots to the same 'cte' key."""
    _, p, _, _, _ = parse_agf_text(
        NM.format(name="TESTG", nd="1.51680") + "ED 7.100000 8.300000 2.510000 0 0\n",
        "TEST", "TEST-AGF")
    cte_rows = p[p["property"] == "cte"]
    assert len(cte_rows) == 1


# --- density gate is per material class ----------------------------------

@pytest.mark.parametrize("mc,ed,accepted", [
    ("oxide_glass", "ED 0.0 0.0 2.51 0 0\n", True),
    ("oxide_glass", "ED 0.0 0.0 1.08 0 0\n", False),   # polymer value, wrong class
    ("polymer",     "ED 0.0 0.0 1.08 0 0\n", True),    # real TOPAS density
    ("polymer",     "ED 0.0 0.0 0.95 0 0\n", True),    # real ZEON density
    ("polymer",     "ED 0.0 0.0 4.20 0 0\n", False),   # impossible for a polymer
    ("oxide_glass", "ED 0.0 0.0 0.40 0 0\n", False),   # impossible for glass
])
def test_density_gate_follows_material_class(mc, ed, accepted):
    got = _props(ed, material_class=mc)
    assert ("density" in got) is accepted


def test_dpgf_unaffected_by_the_decoupling():
    got = _props("ED 0.000000 8.200000 2.300000 -0.000600 0\n")
    assert got["dPgF"] == pytest.approx([-0.0006])
