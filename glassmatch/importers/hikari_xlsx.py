"""HIKARI "All Catalog Data" workbook -> GlassMatch normalized frames.

HIKARI Glass (a Nikon group company) publishes no Zemax file; its current
catalog is an Excel workbook (hikari-g.co.jp, "HIKARI All Catalog Data",
catalog 2025-06-01). Like the .agf catalogs it is redistribution-limited, so
the workbook stays in the gitignored data/staging/ and only normalized rows
ship.

Per glass the workbook carries more than any .agf record:

* the 9-term power-series dispersion coefficients A0..A8 - the same equation
  as Zemax formula 13 ("Extended 3"), in the same order, so the fit is stored
  as a Zemax formula 13 row and evaluated by glassmatch.spectra.zemax_n;
* the catalog index at 20 wavelengths (t .. i line). Each fit is verified
  against all of them, not only n_d - a much stronger check than the .agf gate;
* thermal (CTE, T_g, yield point, conductivity, specific heat), mechanical
  (Knoop, Young's and shear modulus, Poisson's ratio, stress-optic
  coefficient) and chemical-resistance properties, 10 mm internal
  transmittance from 280 to 2400 nm, relative dn/dT, and HIKARI's own list of
  similar glasses from OHARA, HOYA, CDGM and SCHOTT.

Units follow the HIKARI catalog: CTE is printed in 1e-7/K and stored here in
1e-6/K like every other source; moduli are GPa (Young's = 2 x shear x
(1 + Poisson) holds for every row, which pins them to one unit), thermal
conductivity W/(m K), specific heat J/(g K), stress-optic coefficient
1e-12/Pa. Columns are located by their header text, never by position, so a
re-ordered workbook fails loudly instead of mis-assigning values.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from glassmatch.spectra import zemax_n

SOURCE_NOTE = "HIKARI All Catalog Data workbook"
# The fit reproduces the catalog's own tabulated index (printed to 5-6
# decimals) far inside this; a larger miss means a wrong row or column.
N_TOL = 5e-5

# Catalog spectral lines -> wavelength (um), as the workbook labels them.
LINES = {"t": 1.01398, "s": 0.85211, "A'": 0.768195, "r": 0.706519,
         "C": 0.656273, "C'": 0.643847, "He-Ne": 0.632816, "D": 0.589294,
         "d": 0.587562, "e": 0.546074, "F": 0.486133, "F'": 0.479992,
         "g": 0.435835, "h": 0.404656, "i": 0.365015}

# Scalar properties: (substring of the column header, property, unit, scale,
# note). Matched against the second header row.
SCALARS = [
    ("常温線膨張係数", "cte", "1e-6/K", 0.1, "CTE -30/+70 C (catalog 1e-7/K)"),
    ("高温線膨張係数", "cte_100_300", "1e-6/K", 0.1,
     "CTE +100/+300 C (catalog 1e-7/K)"),
    ("転移温度Tg", "tg", "C", 1.0, "glass transformation temperature"),
    ("屈伏点At", "yield_point", "C", 1.0, "yield point At"),
    ("熱伝導率", "thermal_conductivity", "W/(m K)", 1.0, "thermal conductivity"),
    ("比熱c", "specific_heat", "J/(g K)", 1.0, "specific heat capacity"),
    ("磨耗度", "abrasion", "", 1.0, "abrasion (FA)"),
    ("ヤング率", "youngs_modulus", "GPa", 1.0, "Young's modulus"),
    ("剛性率", "shear_modulus", "GPa", 1.0, "shear modulus"),
    ("ポアソン比", "poisson_ratio", "", 1.0, "Poisson's ratio"),
    ("光弾性定数", "stress_optic_coefficient", "1e-12/Pa", 1.0,
     "stress-optic coefficient"),
    ("表面法耐酸性AR(S)", "acid_resistance_surface", "class", 1.0,
     "acid resistance, surface method"),
    ("耐洗剤性PR(S)", "phosphate_resistance", "class", 1.0,
     "alkaline (phosphate) detergent resistance, surface method"),
    ("耐候性CR(S)", "climate_resistance", "class", 1.0,
     "climate resistance, surface method"),
    ("粉末法耐水性WR(P)", "water_resistance_powder", "class", 1.0,
     "water resistance, powder method"),
    ("粉末法耐酸性AR(P)", "acid_resistance_powder", "class", 1.0,
     "acid resistance, powder method"),
    ("ΔPg,F", "dPgF", "", 1.0, "anomalous partial dispersion dPg,F"),
]


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    m = re.match(r"^-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


def _line_of(label) -> float | None:
    """Wavelength (um) of an index column header such as 'd\\n0.587562'."""
    if isinstance(label, (int, float)):
        return float(label)
    parts = str(label or "").split()
    for p in reversed(parts):
        try:
            return float(p)
        except ValueError:
            continue
    return LINES.get(str(label).strip())


def _columns(head1: tuple, head2: tuple) -> dict:
    """Header text -> column index map for everything the importer reads."""
    cols: dict = {"index": [], "it": [], "coef": [], "similar": {}}
    group = ""
    for j, (g, h) in enumerate(zip(head1, head2)):
        if isinstance(g, str) and g.strip():
            group = g
        hs = str(h).strip() if h is not None else ""
        if "屈折率" in group and j >= 3 and j < 24:
            wl = _line_of(h)
            if wl:
                cols["index"].append((j, wl))
        if hs == "νd":
            cols["vd"] = j
        m = re.fullmatch(r"(\d{3,4})nm", hs)
        if m and "透過率" in group:
            cols["it"].append((j, int(m.group(1)) / 1000.0))
        if re.match(r"^A[0-8]", hs):
            cols["coef"].append((int(hs[1]), j))
        if hs.startswith("比重") or (isinstance(g, str) and g.startswith("比重")):
            cols.setdefault("density", j)
        if "ヌープ" in hs:
            cols["knoop"] = j
        if "生産頻度" in str(g or ""):
            cols["frequency"] = j
        if "相対" in group and "+20ºC to +40ºC" in group and hs == "d":
            cols["dndt_rel_d"] = j
        for key, prop, unit, scale, note in SCALARS:
            if key in hs or (key == "ΔPg,F" and hs == key):
                cols.setdefault(prop, (j, unit, scale, note))
    # Similar-glass columns: header row 2 names the maker.
    for j, h in enumerate(head2):
        hs = str(h or "")
        for maker in ("OHARA", "HOYA", "CDGM", "SCHOTT"):
            if hs.endswith(maker) or hs.split()[-1:] == [maker]:
                cols["similar"][maker] = j
    cols["coef"] = [j for _, j in sorted(cols["coef"])]
    missing = [k for k in ("vd", "density") if k not in cols]
    if len(cols["coef"]) != 9 or len(cols["index"]) < 15 or missing:
        raise ValueError(f"HIKARI workbook layout not recognised (coef "
                         f"{len(cols['coef'])}, index {len(cols['index'])}, "
                         f"missing {missing})")
    return cols


def _prop(gid, prop, value, unit, ref_nm, source_id, note):
    return {"glass_id": gid, "property": prop, "value": value, "unit": unit,
            "reference_wavelength_nm": ref_nm, "data_type": "manufacturer",
            "source_id": source_id, "notes": f"HIKARI catalog: {note}."}


def _absolute_dndt(wb) -> dict:
    """glass name -> absolute dn/dT (1e-6/K), d line, +20 to +40 C.

    From the workbook's "dn dT" sheet, where each glass has a "(rel.)" and an
    "(abs.)" row and each temperature range is a block of line columns.
    """
    if "dn dT" not in wb.sheetnames:
        return {}
    rows = list(wb["dn dT"].iter_rows(values_only=True))
    start = next((j for j, h in enumerate(rows[1])
                  if isinstance(h, str) and "+20ºC to +40ºC" in h), None)
    if start is None:
        return {}
    col = next((j for j in range(start, start + 16)
                if str(rows[2][j]).strip() == "d"), None)
    if col is None:
        return {}
    out = {}
    for r in rows[3:]:
        label = str(r[0] or "")
        if label.endswith("(abs.)") and _num(r[col]) is not None:
            out[label[:-len("(abs.)")].strip()] = _num(r[col])
    return out


def import_hikari_xlsx(path, source_id: str, manufacturer: str = "HIKARI"):
    """Read the workbook -> (glasses, properties, sellmeier, transmission,
    equivalents, issues). Equivalents are HIKARI's "similar glass type"
    cross-references, as (maker, name) pairs for the caller to resolve."""
    import openpyxl
    wb = openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    rows = list(wb["Data"].iter_rows(values_only=True))
    cols = _columns(rows[1], rows[2])
    abs_dndt = _absolute_dndt(wb)
    glasses, props, sell, trans, equiv, issues = [], [], [], [], [], []
    for r in rows[3:]:
        name = r[0]
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        gid = f"{manufacturer}-{name}".upper().replace(" ", "_")
        freq = str(r[cols["frequency"]]).strip() if "frequency" in cols else ""
        glasses.append({
            "glass_id": gid, "manufacturer_id": manufacturer,
            "glass_name": name, "manufacturer_code": name,
            "glass_family": "", "material_class": "oxide_glass",
            "status": "standard",
            "description": (f"Imported from {source_id}."
                            + (f" Production frequency {freq} (A = most "
                               "frequent)." if freq and freq != "None" else ""))})
        tab = {wl: _num(r[j]) for j, wl in cols["index"]}
        nd = tab.get(LINES["d"])
        vd = _num(r[cols["vd"]])
        if nd:
            props.append(_prop(gid, "refractive_index_nd", nd, "", 587.6,
                               source_id, "n_d"))
        if vd:
            props.append(_prop(gid, "abbe_number_vd", vd, "", 587.6,
                               source_id, "V_d"))
        dens = _num(r[cols["density"]])
        if dens:
            props.append(_prop(gid, "density", dens, "g/cm3", "", source_id,
                               "specific gravity"))
        if "knoop" in cols and _num(r[cols["knoop"]]) is not None:
            props.append(_prop(gid, "knoop_hardness", _num(r[cols["knoop"]]),
                               "HK", "", source_id, "Knoop hardness"))
        for key, prop, unit, scale, note in SCALARS:
            if prop not in cols:
                continue
            j, unit, scale, note = cols[prop]
            v = _num(r[j])
            if v is not None:
                props.append(_prop(gid, prop, round(v * scale, 6), unit, "",
                                   source_id, note))
        if "dndt_rel_d" in cols and _num(r[cols["dndt_rel_d"]]) is not None:
            props.append(_prop(gid, "dn_dt_rel_d_20_40",
                               _num(r[cols["dndt_rel_d"]]), "1e-6/K", 587.6,
                               source_id, "relative dn/dT, d line, +20 to +40 C"))
        if name in abs_dndt:
            props.append(_prop(gid, "dn_dt_abs_d_20_40", abs_dndt[name],
                               "1e-6/K", 587.6, source_id,
                               "absolute dn/dT, d line, +20 to +40 C"))
        # Dispersion: A0..A8 are Zemax formula 13's coefficients.
        coeffs = [_num(r[j]) for j in cols["coef"]]
        row = {"glass_id": gid, "wavelength_um": "", "source_id": source_id,
               "zemax_formula": 13}
        if any(c is None for c in coeffs):
            row["formula"] = ("Non-dispersable (incomplete A0-A8 coefficients) "
                              "- archived, never evaluated")
            row["coefficients"] = " ".join("" if c is None else repr(c)
                                           for c in coeffs)
            row["notes"] = "HIKARI catalog power-series coefficients."
            issues.append({"glass": name, "issue": "incomplete coefficients"})
        else:
            row["coefficients"] = " ".join(repr(float(c)) for c in coeffs)
            miss = [(wl, abs(zemax_n(13, coeffs, wl) - n))
                    for wl, n in tab.items() if n is not None]
            worst = max(miss, key=lambda x: x[1]) if miss else (None, None)
            if not miss or worst[1] > N_TOL:
                row["formula"] = (f"Non-dispersable (power series misses the "
                                  f"catalog index by {worst[1]:.2e} at "
                                  f"{worst[0]} um) - archived, never evaluated")
                issues.append({"glass": name, "issue": row["formula"]})
            else:
                row["formula"] = "Extended 3 (Zemax formula 13, HIKARI catalog)"
            row["notes"] = (f"HIKARI catalog 9-term power series (A0-A8 = Zemax "
                            f"formula 13). Verified against the catalog index "
                            f"at {len(miss)} wavelengths "
                            f"({min(tab):.3f}-{max(tab):.3f} um): max |dn| "
                            f"{worst[1]:.1e}.")
            row["wavelength_um"] = f"{min(tab)}-{max(tab)}"
        sell.append(row)
        for j, wl in cols["it"]:
            t = _num(r[j])
            if t is not None and 0.0 <= t <= 1.0:
                trans.append({"glass_id": gid, "wavelength_um": wl,
                              "transmission": t, "thickness_mm": 10.0,
                              "data_type": "manufacturer",
                              "source_id": source_id,
                              "notes": "HIKARI catalog internal transmittance "
                                       "(10 mm)."})
        for maker, j in cols["similar"].items():
            other = r[j]
            if isinstance(other, str) and other.strip() not in ("", "-"):
                for nm in re.split(r"[,/、\s]+", other.strip()):
                    if nm:
                        equiv.append((gid, maker, nm))
    return (pd.DataFrame(glasses), pd.DataFrame(props), pd.DataFrame(sell),
            pd.DataFrame(trans), equiv, issues)
