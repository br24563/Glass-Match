"""Tests: Nikon multi-line Extended-3 CD rows are joined, kept verbatim, and
evaluated in the formula the NM record names."""
from glassmatch.importers.agf import is_dispersable_formula, parse_agf_text
from glassmatch.spectra import coefficients_of, n_from_row

NIKON_JFK5 = (
    "NM J-FK5 13 1 1.487490 70.318793 0 0 1\n"
    "GC \n"
    "ED 8.900000000E+000 0.000000000E+000 2.450000000E+000 2.700000000E-003 0 0\n"
    "CD 2.188268550E+000 -9.190447240E-003 -1.116210710E-004 9.263728150E-003 \n"
    "7.349007330E-005 4.197242420E-006 -1.154122030E-007 0.000000000E+000 \n"
    "TD 1.000000000E+000 0.000000000E+000 0.000000000E+000 0.000000000E+000 "
    "0.000000000E+000 0.000000000E+000 2.000000000E+001\n"
)


def test_nikon_extended3_is_joined_and_verified():
    g, p, s, t, issues = parse_agf_text(NIKON_JFK5, "NIKON", "NIKON-TEST")
    assert len(g) == 1 and len(s) == 1
    row = s.iloc[0].to_dict()
    # NM field 2 says formula 13 (Extended 3). Evaluated as Sellmeier-1, as an
    # earlier importer did, these coefficients give n(d) = 1.7696 and the glass
    # was archived; in its own formula it reproduces the catalog.
    assert row["formula"] == "Extended 3 (Zemax formula 13, CD record)"
    assert is_dispersable_formula(row["formula"])
    assert int(row["zemax_formula"]) == 13
    # both wrapped lines joined, verbatim
    c = coefficients_of(row)
    assert len(c) == 8 and abs(c[0] - 2.188268550) < 1e-12
    assert abs(c[6] - (-1.154122030e-7)) < 1e-20
    assert abs(n_from_row(row, 0.5875618) - 1.487490) < 2e-5
    vd = ((n_from_row(row, 0.5875618) - 1)
          / (n_from_row(row, 0.4861327) - n_from_row(row, 0.6562725)))
    assert abs(vd - 70.318793) < 0.05
    nd = float(p[p["property"] == "refractive_index_nd"].iloc[0]["value"])
    assert abs(nd - 1.487490) < 1e-9  # NM header still parses


def test_wrong_formula_number_is_archived_not_trusted():
    # Same coefficients declared as Sellmeier-1: they no longer reproduce n(d),
    # so the row is archived with the measured discrepancy in its label.
    text = NIKON_JFK5.replace("NM J-FK5 13 ", "NM J-FK5 2 ")
    g, p, s, t, issues = parse_agf_text(text, "NIKON", "NIKON-TEST")
    row = s.iloc[0]
    assert row["formula"].startswith("Non-dispersable")
    assert "never evaluated" in row["formula"]
    assert "1.76960" in row["formula"] and "1.48749" in row["formula"]
    assert any("n(d)" in i.get("issue", "") for i in issues)
