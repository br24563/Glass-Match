"""Tests: .agf importer (Zemax NM layout), IT triples/pairs, UTF-16 read."""
from pathlib import Path
from glassmatch.importers.agf import parse_agf_text, guess_family, read_agf_file
from glassmatch.spectra import sellmeier_n

FIX = Path(__file__).resolve().parent / "fixtures" / "demo.agf"


def test_agf_nbK7_roundtrip():
    g, p, s, t, issues = parse_agf_text(FIX.read_text(), "SCHOTT", "SCHOTT-AGF-TEST")
    assert len(g) == 2
    nbk7 = p[(p["glass_id"] == "SCHOTT-N-BK7") & (p["property"] == "refractive_index_nd")]
    assert abs(float(nbk7.iloc[0]["value"]) - 1.51680) < 1e-6
    row = s[s["glass_id"] == "SCHOTT-N-BK7"].iloc[0]
    n587 = sellmeier_n(0.5876, (row["B1"], row["B2"], row["B3"]),
                       (row["C1_um2"], row["C2_um2"], row["C3_um2"]))
    assert abs(n587 - 1.51680) < 0.002  # nd/Sellmeier cross-check must pass
    assert not [i for i in issues if "Sellmeier n(d)" in i.get("issue", "")
                and i.get("glass") == "N-BK7"]
    assert (p["data_type"] == "manufacturer").all()


def test_agf_flags_unknown_and_parses_it_ld():
    g, p, s, t, issues = parse_agf_text(FIX.read_text(), "SCHOTT", "SCHOTT-AGF-TEST")
    assert any("unknown" in i.get("issue", "") for i in issues)
    nbk7t = t[t["glass_id"] == "SCHOTT-N-BK7"]
    assert len(nbk7t) == 4  # 2 pairs + 2 triples-with-thickness
    assert set(nbk7t["thickness_mm"]) == {10.0, 25.0}
    assert "wl_min_um" in set(p["property"]) and "wl_max_um" in set(p["property"])
    assert "glass_code" in set(p["property"])
    nbk7p = p[p["glass_id"] == "SCHOTT-N-BK7"]
    assert abs(float(nbk7p[nbk7p["property"] == "density"].iloc[0]["value"]) - 2.51) < 1e-9
    assert abs(float(nbk7p[nbk7p["property"] == "cte"].iloc[0]["value"]) - 7.1) < 1e-9
    assert guess_family("S-TIH53") == "Dense flint"


def test_agf_nm_positional_skips_formula_melt():
    # "1 1" are dispformula/meltfreq — must not be mistaken for nd/vd.
    g, p, s, t, issues = parse_agf_text(
        "NM N-BK7 1 1 517642.251 1.51680 64.17 0 1\n", "SCHOTT", "T")
    nd = float(p[(p["property"] == "refractive_index_nd")].iloc[0]["value"])
    vd = float(p[(p["property"] == "abbe_number_vd")].iloc[0]["value"])
    assert abs(nd - 1.51680) < 1e-9 and abs(vd - 64.17) < 1e-9


def test_agf_it_triples_keep_thickness():
    g, p, s, t, issues = parse_agf_text(
        "NM G 1 1 123456.789 1.50000 60.00 0 1\nIT 0.40 0.50 25.0\n",
        "M", "T")
    assert len(t) == 1
    assert abs(float(t.iloc[0]["thickness_mm"]) - 25.0) < 1e-9
    assert abs(float(t.iloc[0]["transmission"]) - 0.50) < 1e-9


def test_agf_utf16_read(tmp_path):
    blob = ("NM N-BK7 1 1 517642.251 1.51680 64.17 0 1\n"
            "CD 1.03961212 0.00600069867 0.231792344 0.0200179144 "
            "1.01046945 103.560653\n").encode("utf-16")
    f = tmp_path / "u16.agf"
    f.write_bytes(blob)
    text = read_agf_file(f)
    assert "NM N-BK7" in text
    g, p, s, t, issues = parse_agf_text(text, "SCHOTT", "T")
    assert len(g) == 1 and not [i for i in issues if "outside NM" in i["issue"]]


def test_agf_gc_freetext_never_property():
    text = ("NM G 1 1 999888.777 1.50000 60.00 0 1\n"
            "GC radiation resistant glass\n")
    g, p, s, t, issues = parse_agf_text(text, "M", "T")
    assert "glass_code" in set(p["property"])  # NM code kept
    gc_rows = p[(p["property"] == "glass_code")]
    assert all("GC glass code" not in str(n) for n in gc_rows["notes"])
    g2, p2, s2, t2, _ = parse_agf_text(
        "NM G 1 1 517642.251 1.51680 64.17 0 1\nGC 517642.251\n", "M", "T")
    assert "glass_code" in set(p2["property"])
