"""Tests: Nikon multi-line polynomial CD rows stay verbatim, flagged non-Sellmeier."""
from glassmatch.importers.agf import parse_agf_text

NIKON_JFK5 = (
    "NM J-FK5 13 1 1.487490 70.318793 0 0 1\n"
    "GC \n"
    "ED 8.900000000E+000 0.000000000E+000 2.450000000E+000 2.700000000E-003 0 0\n"
    "CD 2.188268550E+000 -9.190447240E-003 -1.116210710E-004 9.263728150E-003 \n"
    "7.349007330E-005 4.197242420E-006 -1.154122030E-007 0.000000000E+000 \n"
    "TD 1.000000000E+000 0.000000000E+000 0.000000000E+000 0.000000000E+000 "
    "0.000000000E+000 0.000000000E+000 2.000000000E+001\n"
)


def test_nikon_polynomial_kept_verbatim_flagged():
    g, p, s, t, issues = parse_agf_text(NIKON_JFK5, "NIKON", "NIKON-TEST")
    assert len(g) == 1 and len(s) == 1
    row = s.iloc[0]
    assert row["formula"].startswith("Non-Sellmeier")
    assert abs(float(row["B1"]) - 2.188268550) < 1e-9  # verbatim, never "fixed"
    nd = float(p[p["property"] == "refractive_index_nd"].iloc[0]["value"])
    assert abs(nd - 1.487490) < 1e-9  # NM header still parses
    assert any("Sellmeier" in i.get("issue", "") for i in issues)
