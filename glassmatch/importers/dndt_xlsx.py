"""Measured dn/dT tables from the manufacturers' Excel data workbooks.

Every maker that publishes a data workbook also tabulates the temperature
coefficient of refractive index it measured: per spectral line, per 20 K
temperature interval, relative to air and/or absolute (in vacuum).

  * SCHOTT  - relative and absolute, 1060 nm / e / g, -40/-20, +20/+40, +60/+80 C
  * OHARA   - relative, 1550 nm and t ... i, -80 ... +180 C
  * HOYA    - relative and absolute, h ... r, -40 ... +150 C
  * CDGM    - relative, t / C' / d / e / F' / g, -60 ... +140 C
  * HIKARI  - relative and absolute, 1083 nm ... 389 nm, -70 ... +90 C
              ("dn dT" sheet; HIKARI marks some relative ranges 参考値,
              reference values only, and that mark is kept)

Each value is one row of dn_dt_measured.csv: (glass_id, wavelength_um,
t_lo_c, t_hi_c, basis, dn_dt in 1e-6/K, reference_only, source_id). These
are what GlassMatch checks the SCHOTT dn/dT model (Zemax TD records)
against, and what n(lambda, T) falls back on for a glass with no TD record
(glassmatch.thermal).

Columns are found by their header text, never by position: a column counts
only when its header names a temperature coefficient of refractive index, a
spectral line or wavelength, and a temperature interval. Anything else -
the dn/dT model constants, HOYA's dV/dT columns - is left alone.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Fraunhofer and laser lines the workbooks name, in um.
LINES_UM = {
    "t": 1.01398, "s": 0.85211, "A'": 0.7681944, "r": 0.706519,
    "C": 0.6562725, "C'": 0.6438469, "He-Ne": 0.6328, "D": 0.5892938,
    "d": 0.5875618, "e": 0.546074, "F": 0.4861327, "F'": 0.4799914,
    "g": 0.4358343, "h": 0.4046561, "i": 0.3650146,
}

# Per maker: sheets, the name column's header, and how many header rows
# (counting the one holding the name header) sit above the data.
LAYOUTS = {
    "SCHOTT": {"sheets": ("Preferred glasses", "Inquiry glasses"),
               "name_header": "Glass", "depth": 1},
    "OHARA": {"sheets": None, "name_header": "Glass", "depth": 1},
    "HOYA": {"sheet_pattern": r"\d{8}data_table1", "name_header": "Glass Type",
             "depth": 4},
    "CDGM": {"sheets": ("optical glass", "i line glass", "infrared glass"),
             "name_header": "Glass", "depth": 2, "end_marker": "over!"},
    "HIKARI": {"sheets": ("dn dT",), "name_header": "Glass type", "depth": 2,
               "row_basis": True},
}

_KEYWORDS = ("dn/dt", "δn/δt", "temperaturecoefficient")
# NFKC turns HIKARI's "º" (U+00BA) into "o".
_RANGE = re.compile(r"([-+]?\d+)\s*(?:deg\.?)?\s*(?:º|°|℃|o)?\s*C?\s*"
                    r"(?:~|/|to)\s*([-+]?\d+)\s*(?:º|°|℃|deg)?")
GROUP_SPAN = 24         # a group label covers at most this many columns


def _norm(v) -> str:
    return unicodedata.normalize("NFKC", str(v)).strip() if v is not None else ""


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _left(row, j) -> str:
    """The group label over column j: the nearest non-empty text at or left
    of j, no more than GROUP_SPAN columns away."""
    for k in range(min(j, len(row) - 1), max(-1, j - GROUP_SPAN), -1):
        v = row[k]
        if isinstance(v, str) and v.strip():
            return _norm(v)
    return ""


def _line_um(cell: str, group: str):
    """Wavelength (um) named by the column's own header cell, else by its
    group label ('... for d', '... nh 404.66 ...')."""
    c = re.sub(r"\(.*$", "", cell).replace("-line", "").strip()
    if c in LINES_UM:
        return LINES_UM[c]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(nm|μm|µm|um)?", c)
    if m:
        x = float(m.group(1))
        if m.group(2) in ("μm", "µm", "um"):     # CDGM's IR sheet: "5μm"
            return x
        return x / 1000.0 if (m.group(2) or x > 100) else x
    m = re.search(r"\bfor\s+(\S+)\s*$", group)
    if m and m.group(1) in LINES_UM:
        return LINES_UM[m.group(1)]
    m = re.search(r"(\d{3,4}\.\d+)", group)
    if m:
        return float(m.group(1)) / 1000.0
    return None


def _range(text: str):
    for m in _RANGE.finditer(text):
        lo, hi = int(m.group(1)), int(m.group(2))
        if -300 <= lo < hi <= 400:
            return lo, hi
    return None


def column_map(group_rows, cell_row) -> dict:
    """Column index -> (wavelength_um, t_lo, t_hi, basis or None, reference)
    for every dn/dT column in a header block."""
    width = max([len(r) for r in group_rows] + [len(cell_row)])
    out = {}
    for j in range(width):
        groups = [_left(r, j) for r in group_rows]
        cell = _norm(cell_row[j]) if j < len(cell_row) else ""
        text = " | ".join(p for p in groups + [cell] if p)
        flat = _flat(text)
        if not any(k in flat for k in _KEYWORDS) or "abbe" in flat \
                or "dν" in text:
            continue
        rng = _range(cell) or _range(" ".join(groups))
        wl = _line_um(cell, " ".join(groups).strip())
        if rng is None or wl is None:
            continue
        basis = ("absolute" if "absolute" in flat else
                 "relative" if "relative" in flat else None)
        if "相対屈折率(参考値)" in flat:       # HIKARI: relative rows only
            ref = "relative"
        else:
            ref = "all" if "参考値" in text else ""
        out[j] = (wl, rng[0], rng[1], basis, ref)
    return out


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    s = str(v).strip()
    return float(s) if re.fullmatch(r"[-+]?\d+(\.\d+)?", s) else None


def _header_row(rows, name_header):
    """(row, column) of the name header: a cell that starts with it, else
    one that contains it (HIKARI writes '硝種 Glass type (relative/...)')."""
    want = _flat(_norm(name_header))
    for test in (str.startswith, str.__contains__):
        for i, r in enumerate(rows[:10]):
            for j, v in enumerate(r):
                if isinstance(v, str) and test(_flat(_norm(v)), want):
                    return i, j
    raise ValueError(f"no {name_header!r} header in the first 10 rows")


def name_key(name) -> str:
    return re.sub(r"\s+", "", str(name or "")).upper()


def import_dndt_xlsx(path, maker: str, source_id: str, names: dict):
    """Read one workbook -> (rows, report).

    names: name_key(glass name) -> glass_id for this maker's glasses.
    """
    import openpyxl
    lay = LAYOUTS[maker]
    wb = openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    if "sheet_pattern" in lay:
        sheets = [n for n in wb.sheetnames
                  if re.fullmatch(lay["sheet_pattern"], n)]
    else:
        sheets = [s for s in (lay["sheets"] or wb.sheetnames[:1])
                  if s in wb.sheetnames]
    if not sheets:
        raise ValueError(f"{maker} workbook: no dn/dT sheet found")
    out, report = [], {"glasses": set(), "unmatched": set(), "columns": {},
                       "implausible": 0}
    seen = set()
    for sheet in sheets:
        rows = list(wb[sheet].iter_rows(values_only=True))
        hr, name_col = _header_row(rows, lay["name_header"])
        depth = lay["depth"]
        cols = column_map(rows[max(0, hr - 2):hr + depth - 1], rows[hr + depth - 1])
        report["columns"][sheet] = len(cols)
        if not cols:
            continue
        for r in rows[hr + depth:]:
            name = r[name_col] if name_col < len(r) else None
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()
            if name == lay.get("end_marker"):
                break
            row_basis = None
            if lay.get("row_basis"):
                m = re.fullmatch(r"(.*?)\s*\((rel|abs)\.\)", name)
                if not m:
                    continue
                name = m.group(1)
                row_basis = "relative" if m.group(2) == "rel" else "absolute"
            gid = names.get(name_key(name))
            if gid is None:
                report["unmatched"].add(name)
                continue
            for j, (wl, lo, hi, basis, ref) in cols.items():
                v = _num(r[j]) if j < len(r) else None
                basis = basis or row_basis
                if v is None or basis is None:
                    continue
                if abs(v) > 1000:           # not a dn/dT in 1e-6/K (Ge ~400)
                    report["implausible"] += 1
                    continue
                key = (gid, round(wl, 6), lo, hi, basis)
                if key in seen:             # same glass on two sheets
                    continue
                seen.add(key)
                out.append({
                    "glass_id": gid, "wavelength_um": round(wl, 7),
                    "t_lo_c": lo, "t_hi_c": hi, "basis": basis,
                    "dn_dt": v, "unit": "1e-6/K",
                    "reference_only": bool(ref == "all"
                                           or (ref == "relative"
                                               and basis == "relative")),
                    "source_id": source_id})
                report["glasses"].add(gid)
    report["unmatched"] = sorted(report["unmatched"])
    report["glasses"] = len(report["glasses"])
    return out, report
