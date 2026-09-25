"""Zemax .agf catalog importer — Ring 1/2 expansion engine.

Parses the documented Zemax glass-catalog subset (NM/CD/ED/GC/TD/OD/LD/IT
records) into GlassMatch normalized frames. Users download the .agf from the
manufacturer site themselves (see importers/catalogs.py + data/manufacturers
READMEs); GlassMatch never redistributes bulk catalogs and never scrapes.

Supported records (tolerant reader — unknown lines ignored, flagged):
  NM <name> <glasscode> <nd> <vd> [density_gcm3] [status] [extra...]
      - name: glass name (may contain dashes); glasscode optional.
      - nd in [1.2, 2.7], vd in [8, 130] auto-detected among floats so
        catalog column-order variants parse without per-vendor code.
  CD <B1> <C1> <B2> <C2> <B3> <C3>   Schott/Sellmeier-1 dispersion
  ED <C1..C8 or thermal coeffs...>   stored raw in notes (not silently used)
  GC <glasscode>                     glass code attachment (alternative to NM field)
  TD <CTE_-30_70> <CTE_20_300> <Tg> <k_thermal>  thermal data (any subset)
  OD <...>  LD <...>                 ignored-but-counted (opaque/mech records)
  IT <wl_um> <T_10mm> [<wl_um> <T_10mm> ...]     internal transmittance pairs

Output: (glasses, properties, sellmeier, transmission, issues).
All rows carry data_type='manufacturer' + caller-supplied source_id.
"""
from __future__ import annotations
import math
import pandas as pd

FAMILY_GUESS = (
    ("FLUOR", "Fluor crown"), ("FK", "Fluor crown"), ("FPL", "Fluor crown"),
    ("FCD", "Fluor crown"), ("PFK", "Fluor crown"), ("FC", "Fluor crown"),
    ("SF", "Dense flint"), ("TIH", "Dense flint"), ("ZF", "Dense flint"),
    ("LASF", "Lanthanum flint"), ("LAF", "Lanthanum flint"), ("LAK", "Lanthanum crown"),
    ("BAK", "Barium crown"), ("SK", "Dense crown"), ("SSK", "Dense crown"),
    ("BAF", "Barium flint"), ("KZ", "Anomalous dispersion"), ("VC", "Dense crown"),
    ("BAL", "Barium crown"), ("BAS", "Barium flint"), ("K9", "Borosilicate crown"),
    ("BK", "Borosilicate crown"), ("BSL", "Borosilicate crown"), ("KZFS", "Anomalous dispersion"),
)


def guess_family(name: str) -> str:
    u = str(name).upper()
    for key, fam in FAMILY_GUESS:
        if key in u:
            return fam
    return "Optical glass"


def _floats(tokens: list) -> list:
    out = []
    for t in tokens:
        try:
            out.append(float(t))
        except (TypeError, ValueError):
            continue
    return out


def _is_num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except (TypeError, ValueError):
        return False


def _prop(gid, prop, value, unit, ref_wl, source_id, notes) -> dict:
    return {"glass_id": gid, "property": prop, "value": value, "unit": unit,
            "reference_wavelength_nm": ref_wl, "data_type": "manufacturer",
            "source_id": source_id, "notes": notes}
def parse_agf_text(text: str, manufacturer: str, source_id: str,
                   material_class: str = "oxide_glass") -> tuple:
    """Parse .agf text -> (glasses, properties, sellmeier, transmission, issues)."""
    glasses, props, sell, trans, issues = [], [], [], [], []
    cur = None
    parse_agf_text._seen = {}

    def flush():
        if cur is not None and cur.get("glass_name"):
            _flush_cd(cur, source_id, issues)
            glasses.append(cur["glass_row"])
            props.extend(cur["props"])
            sell.extend(cur["sell"])
            trans.extend(cur["trans"])

    def flush_cd_only():
        if cur is not None and cur.get("_cd_pending"):
            _flush_cd(cur, source_id, issues)

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith((";", "#", "CC", "AGF")):
            continue
        parts = line.split()
        tag = parts[0].upper()
        # Continuation lines: Nikon-style polynomial CD wraps across lines as
        # bare numbers with no tag. Append to the pending CD buffer.
        if _is_num(tag) or (tag.replace(".", "", 1).replace("-", "", 1)
                            .replace("+", "", 1).replace("E", "", 1)
                            .replace("e", "", 1).strip("0123456789") == ""
                            and _floats(parts)):
            if cur is not None and cur.get("_cd_pending"):
                cur["_cd_pending"].extend(_floats(parts))
                continue
            issues.append({"line": lineno, "issue": "bare-number line outside CD",
                           "text": raw[:80]})
            continue
        if tag == "NM":
            flush()
            name = parts[1] if len(parts) > 1 else ""
            # nd/vd anchored on the glass CODE position: nd = first float in
            # 1.2..2.7 strictly AFTER the code token. Codes with leading zeros
            # ("005210.619" -> 5210.619) still anchor correctly. Special case:
            # "NM B270 1 1 1.523080 58.571369 ..." has NO code — nd directly
            # follows the two small ints, so fall back to whole-line search.
            rest_tokens = parts[2:]
            code = ""
            code_idx = -1
            for i, tok in enumerate(rest_tokens):
                t = tok.strip().rstrip(",;")
                if _is_num(t):
                    try:
                        f = abs(float(t))
                        if (100000.0 <= f <= 999999.999) or \
                           (100000 <= f <= 999999 and f == int(f)) or \
                           (22200.0 <= f <= 99999.999):
                            # SCHOTT writes high-index codes with leading zero
                            # ("022291.541" parses as 22291.541) — still a code.
                            code, code_idx = t, i
                            break
                    except (TypeError, ValueError):
                        continue
            nums_all = _floats(rest_tokens)
            if code_idx >= 0:
                nums_after = _floats(rest_tokens[code_idx + 1:])
                nd = next((v for v in nums_after if 1.2 <= v <= 2.7), None)
            else:
                nums_after = nums_all
                nd = None
            if nd is None:  # codename-less NM (B270) or odd vendor layout
                tail = nums_all[2:] if len(nums_all) > 3 else nums_all
                nd = next((v for v in tail if 1.2 <= v <= 2.7), None)
                if nd is None:
                    nd = next((v for v in nums_all if 1.2 <= v <= 2.7), None)
                nums_after = nums_all
            vd = None
            if nd is not None:
                seen_nd = False
                for v in nums_after:
                    if not seen_nd and v == nd:
                        seen_nd = True
                        continue
                    if seen_nd and 8.0 <= v <= 130.0:
                        vd = v
                        break
            density = None  # ED record may supply it (see _ed_block)
            if not name:
                issues.append({"line": lineno, "issue": "NM without name"})
                cur = None
                continue
            if nd is None or vd is None:
                issues.append({"line": lineno, "issue": "NM missing nd/vd",
                               "text": raw[:80]})
            # Duplicate NM names in one catalog are real (HOYA mold variants
            # "E-FL6 ... 0 0 4" vs "... 0 0 0", Nikon E-series repeats): same
            # name, slightly different vd/coefficients. Disambiguate with the
            # trailing status flag when the name repeats, else -B/-C suffixes,
            # so glass_ids stay unique and traceable instead of colliding.
            gid_base = f"{manufacturer}-{name}".upper().replace(" ", "_")
            status_flag = rest_tokens[-1] if rest_tokens else ""
            _seen = parse_agf_text._seen if hasattr(parse_agf_text, "_seen") else None
            gid = gid_base
            if _seen is not None and gid_base in _seen:
                n_prev = _seen[gid_base]
                suffix = f"-MOLD{status_flag}" if status_flag not in ("", "1") else f"-B{n_prev}"
                gid = f"{gid_base}{suffix}"
                issues.append({"line": lineno, "glass": name,
                               "issue": f"duplicate NM name #{n_prev + 1} -> glass_id {gid} "
                                        f"(status flag {status_flag!r}; vd={vd})"})
                _seen[gid_base] += 1
            elif _seen is not None:
                _seen[gid_base] = 1
            grows = {"glass_id": gid, "manufacturer_id": manufacturer,
                     "glass_name": name, "manufacturer_code": name,
                     "glass_family": guess_family(name),
                     "material_class": material_class, "status": "standard",
                     "description": f"Imported from {source_id}."}
            prows = []
            if nd is not None:
                prows.append(_prop(gid, "refractive_index_nd", nd, "",
                                   587.6, source_id, "nd from .agf NM record."))
            if vd is not None:
                prows.append(_prop(gid, "abbe_number_vd", vd, "",
                                   587.6, source_id, "Vd from .agf NM record."))
            if density is not None:
                prows.append(_prop(gid, "density", density, "g/cm3",
                                   "", source_id, "density from .agf NM record."))
            if code:
                prows.append(_prop(gid, "glass_code", code, "",
                                   "", source_id, "glass code from .agf."))
            cur = {"glass_name": name, "glass_row": grows,
                   "props": prows, "sell": [], "trans": []}
        elif cur is None:
            issues.append({"line": lineno, "issue": f"{tag} outside NM block"})
        elif tag == "CD":
            # Buffer CD numbers; Nikon-style polynomial rows wrap across lines
            # as bare numbers, appended by the continuation handler above.
            # Flush at the next real tag (flush_cd_only before each branch).
            flush_cd_only()
            cur["_cd_pending"] = _floats(parts[1:])
            cur["_cd_lineno"] = lineno
            continue
        elif tag == "TD":
            flush_cd_only()
            # SCHOTT-style TD = thermal dn/dT polynomial (D0 D1 D2 E0 E1 Ltk),
            # NOT CTE/Tg — record but never map to cte/tg properties.
            issues.append({"line": lineno, "glass": cur["glass_name"],
                           "issue": "TD thermal-dispersion record noted, not parsed"})
        elif tag == "MD":
            flush_cd_only()
            issues.append({"line": lineno, "glass": cur["glass_name"],
                           "issue": "MD mechanical record noted, not parsed"})
        elif tag == "GC":
            flush_cd_only()
            # GC is free-text comment ("radiation resistant glass", glass code,
            # "NEW GLASS!! ..."). Only a 6-digit glass-code PATTERN (nnnnnn.nnn
            # or plain 6-digit int) is stored as glass_code; words like
            # "resistant"/"glass" never become properties.
            joined = " ".join(parts[1:])
            mcode = ""
            for tok in parts[1:]:
                t = tok.strip().rstrip(",;")
                if _is_num(t):
                    try:
                        f = abs(float(t))
                        if (100000.0 <= f <= 999999.999) or \
                           (100000 <= f <= 999999 and f == int(f)):
                            mcode = t
                            break
                    except (TypeError, ValueError):
                        continue
            if mcode:
                cur["props"].append(_prop(cur["glass_row"]["glass_id"],
                                          "glass_code", mcode, "", "",
                                          source_id, ".agf GC glass code."))
            if joined:
                cur.setdefault("remarks", []).append(f"GC: {joined}")
        elif tag == "IT":
            flush_cd_only()
            _it_block(cur, _floats(parts[1:]), source_id, issues, lineno)
        elif tag == "LD":
            flush_cd_only()
            nums = _floats(parts[1:])
            if len(nums) >= 2:
                gid = cur["glass_row"]["glass_id"]
                cur["props"].append(_prop(gid, "wl_min_um", nums[0], "um", "",
                                          source_id, ".agf LD lower wavelength limit."))
                cur["props"].append(_prop(gid, "wl_max_um", nums[1], "um", "",
                                          source_id, ".agf LD upper wavelength limit."))
        elif tag == "ED":
            flush_cd_only()
            _ed_block(cur, _floats(parts[1:]), source_id)
        elif tag in ("OD", "AI", "DP"):
            flush_cd_only()
            issues.append({"line": lineno, "glass": cur["glass_name"],
                           "issue": f"{tag} record noted, not parsed into optics"})
        elif tag == "BD":
            flush_cd_only()
            issues.append({"line": lineno, "glass": cur["glass_name"],
                           "issue": "BD bubble-class record noted, not parsed"})
        else:
            flush_cd_only()
            issues.append({"line": lineno, "issue": f"unknown '{tag}' ignored",
                           "text": raw[:80]})
    flush()
    import pandas as pd
    return (pd.DataFrame(glasses), pd.DataFrame(props),
            pd.DataFrame(sell), pd.DataFrame(trans), issues)
def is_sellmeier1_formula(formula: str | None) -> bool:
    """True only for verified Sellmeier-1 rows — the app's dispersion gate.

    Non-Sellmeier rows (Nikon polynomials, Herzberger-style legacy) carry
    archived coefficients that must NEVER be evaluated as Sellmeier-1.
    """
    return str(formula or "") == "Sellmeier-1 (Zemax CD record)"


def _flush_cd(cur: dict, source_id: str, issues: list) -> None:
    """Flush a buffered CD record (single-line or multi-line polynomial)."""
    pending = cur.pop("_cd_pending", None)
    lineno = cur.pop("_cd_lineno", 0)
    if not pending:
        return
    _cd_block(cur, pending, source_id, issues, lineno)


def _cd_block(cur: dict, nums: list, source_id: str,
              issues: list, lineno: int) -> None:
    """Sellmeier CD block + nd cross-check (flags >0.002 mismatch).

    OHARA ships discontinued/legacy glasses with Herzberger-style CD rows
    (C-terms ~1e-2..1e-6, e.g. APL1) that are NOT Sellmeier-1, and Nikon ships
    multi-line polynomial CD rows — neither disperses as Sellmeier-1. The
    n(d)-mismatch flags exactly those; coefficients are still stored verbatim
    with a non-Sellmeier note so nothing is lost or mislabelled.
    """
    if len(nums) < 6:
        issues.append({"line": lineno, "glass": cur["glass_name"],
                       "issue": f"CD has {len(nums)} coeffs (<6)"})
        return
    b = (nums[0], nums[2], nums[4])
    c = (nums[1], nums[3], nums[5])
    from glassmatch.spectra import sellmeier_n
    sell_ok = True
    try:
        n587 = sellmeier_n(0.5876, b, c)
        hdr = next((p["value"] for p in cur["props"]
                    if p["property"] == "refractive_index_nd"), None)
        if hdr is not None and abs(float(n587) - float(hdr)) > 0.002:
            sell_ok = False
            issues.append({"line": lineno, "glass": cur["glass_name"],
                           "issue": f"Sellmeier n(d)={n587:.5f} vs header {hdr}"})
    except (TypeError, ValueError):
        sell_ok = False
        issues.append({"line": lineno, "glass": cur["glass_name"],
                       "issue": "Sellmeier evaluation failed"})
    formula = "Sellmeier-1 (Zemax CD record)" if sell_ok else \
        "Non-Sellmeier CD record (do not disperse as Sellmeier-1)"
    cur["sell"].append({"glass_id": cur["glass_row"]["glass_id"],
                        "formula": formula,
                        "wavelength_um": "", "B1": nums[0], "C1_um2": nums[1],
                        "B2": nums[2], "C2_um2": nums[3],
                        "B3": nums[4], "C3_um2": nums[5],
                        "source_id": source_id,
                        "notes": ".agf CD coefficients; verify with catalog."})
    # Record the dispersion formula + any extra trailing terms so exotic
    # layouts (B270-style extended CD) stay traceable, not silently trimmed.
    extra = nums[6:]
    if any(abs(v) > 0 for v in extra):
        cur.setdefault("remarks", []).append(
            f"CD extra terms ({len(extra)}): " +
            " ".join(f"{v:.6E}" for v in extra))


def _ed_block(cur: dict, nums: list, source_id: str) -> None:
    """SCHOTT-style ED = environmental data: CTE(-30/+70) CTE(20/300) density dPgF.

    Observed: "ED 7.100000 8.300000 2.510000 -0.000900 0" for N-BK7 — CTEs in
    1e-6/K, density in g/cm3, dPgF dimensionless. OHARA-style ED carries
    different semantics, so only values passing tight plausibility gates are
    stored; anything else is ignored (never guessed).
    """
    gid = cur["glass_row"]["glass_id"]
    if len(nums) >= 3 and 0 < nums[0] < 30 and 0 < nums[1] < 30 \
            and 1.5 <= nums[2] <= 9.0:
        cur["props"].append(_prop(gid, "cte", nums[0], "1e-6/K", "",
                                  source_id, ".agf ED record (CTE -30/+70)."))
        cur["props"].append(_prop(gid, "density", nums[2], "g/cm3", "",
                                  source_id, ".agf ED record (density)."))
    if len(nums) >= 4 and -0.05 <= nums[3] <= 0.05:
        cur["props"].append(_prop(gid, "dPgF", nums[3], "", "",
                                  source_id, ".agf ED record (dPgF)."))


def _td_block(cur: dict, nums: list, source_id: str) -> None:
    labels = ["cte_-30_70", "cte_20_300", "tg", "k_thermal"]
    pmap = {"cte_-30_70": ("cte", "1e-6/K"), "cte_20_300": ("cte", "1e-6/K"),
            "tg": ("tg", "degC"), "k_thermal": ("thermal_conductivity", "W/(m K)")}
    gid = cur["glass_row"]["glass_id"]
    for label, val in zip(labels, nums):
        prop, unit = pmap[label]
        ok = (prop == "cte" and 0 < val < 30) or \
             (prop == "tg" and 200 < val < 900) or \
             (prop == "thermal_conductivity" and 0.2 < val < 3.0)
        if ok:
            cur["props"].append(_prop(gid, prop, val, unit, "",
                                      source_id, f".agf TD ({label})."))


def _it_block(cur: dict, nums: list, source_id: str,
              issues: list, lineno: int) -> None:
    """IT records: (wl_um, T, thickness_mm) triples or (wl_um, T) pairs.

    SCHOTT writes triples: IT <wl_um> <T_internal> <thickness_mm>.
    OHARA-style files may write pairs: IT <wl_um> <T_internal>.
    Thickness is preserved verbatim; nothing is rescaled or assumed.
    """
    gid = cur["glass_row"]["glass_id"]
    # Total-count heuristic: pairs (even, not mult of 3) vs triples.
    # "IT 0.40 0.998 0.50 0.999 0.70 0.999" (6 nums) is 3 PAIRS, not 2 triples.
    if len(nums) >= 2 and len(nums) % 2 == 0 and len(nums) % 3 != 0:
        step = 2
    elif len(nums) >= 3 and len(nums) % 3 == 0:
        step = 3
    elif len(nums) >= 2 and len(nums) % 2 == 0:
        step = 2
    else:
        issues.append({"line": lineno, "glass": cur["glass_name"],
                       "issue": f"IT record has {len(nums)} numbers (not pairs/triples)"})
        return
    for i in range(0, len(nums), step):
        wl, tval = nums[i], nums[i + 1]
        thick = nums[i + 2] if step == 3 else 10.0
        if 0.2 <= wl <= 5.0 and 0.0 <= tval <= 1.0:
            cur["trans"].append({"glass_id": gid, "wavelength_um": wl,
                                 "transmission": tval, "thickness_mm": thick,
                                 "data_type": "manufacturer",
                                 "source_id": source_id,
                                 "notes": ".agf IT record (thickness as listed)."})
        else:
            issues.append({"line": lineno, "glass": cur["glass_name"],
                           "issue": f"IT pair wl={wl} T={tval} out of range"})


def read_agf_file(path) -> str:
    """Read an .agf with encoding fallback (UTF-8 -> UTF-16/LE).

    Real-world catalogs (notably OHARA exports) ship as UTF-16; a naive
    UTF-8 read yields null-interleaved garbage. Sniff for null bytes and
    retry as UTF-16 variants. Returns decoded text.
    """
    from pathlib import Path
    raw = Path(path).read_bytes()
    if b"\x00" in raw[:400]:
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, ValueError):
                continue
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


def import_agf(path, manufacturer: str, source_id: str,
               material_class: str = "oxide_glass") -> tuple:
    """Read a user-downloaded .agf file -> normalized frames + issues.

    Conflicting duplicate transmission samples (the same wavelength carrying
    two different values) are quarantined at import rather than written to the
    database: the clean frame keeps only undisputed samples, and each displaced
    row is recorded in the returned issues with both values so the change is
    auditable. Callers that persist data should write
    ``data/normalized/transmission_conflicts.csv`` from those issue rows.
    """
    glasses, props, sell, trans, issues = parse_agf_text(
        read_agf_file(path), manufacturer, source_id, material_class)
    if trans is not None and not trans.empty:
        from glassmatch.validation import split_transmission_conflicts
        clean, conflicts, dropped = split_transmission_conflicts(trans)
        for _, r in conflicts.iterrows():
            issues.append({
                "line": "", "glass": r["glass_id"],
                "issue": (f"transmission conflict at {r['wavelength_um']} um "
                          f"({r['n_values']} values: {r['values']}) - quarantined, "
                          "not written to the database"),
                "wavelength_um": r["wavelength_um"],
                "thickness_mm": r["thickness_mm"],
                "values": r["values"],
                "source_id": r["source_ids"],
            })
        trans = clean
    return glasses, props, sell, trans, issues



