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

from glassmatch.validation import (DEFAULT_DENSITY_RANGE,
                                   DENSITY_RANGES_BY_CLASS)

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


def _nm_positional(parts: list) -> tuple:
    """(formula, nd, vd, status) from a documented-layout NM record, or Nones.

    Zemax: NM <name> <formula> <MIL code> <nd> <vd> [exclude] [status] [melt].
    Accepted only when the formula field is an integer Zemax formula number
    and nd/vd are numeric, so vendor variants still reach the heuristic.
    nd <= 1 and vd <= 0 are Zemax placeholders, returned as None.
    """
    from glassmatch.spectra import ZEMAX_FORMULAS
    if len(parts) < 6:
        return None, None, None, None
    try:
        f = float(parts[2])
        nd, vd = float(parts[4]), float(parts[5])
    except ValueError:
        return None, None, None, None
    if f != int(f) or int(f) not in ZEMAX_FORMULAS or not (0.9 <= nd <= 4.5):
        return None, None, None, None
    status = None
    if len(parts) > 7:
        try:
            status = int(float(parts[7]))
        except ValueError:
            status = None
    return (int(f), nd if nd > 1.0 else None, vd if vd > 0.0 else None, status)


def _nm_heuristic(rest_tokens: list, nums_all: list, code_idx: int) -> tuple:
    """(nd, vd) by value range, for NM records that are not in Zemax layout.

    nd = first float in 1.2..2.7 after the glass code; vd = first float in
    8..130 after nd.  Codename-less records ("NM B270 1 1 1.523080 ...") fall
    back to a whole-line search.
    """
    if code_idx >= 0:
        nums_after = _floats(rest_tokens[code_idx + 1:])
        nd = next((v for v in nums_after if 1.2 <= v <= 2.7), None)
    else:
        nums_after = nums_all
        nd = None
    if nd is None:
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
    return nd, vd


def parse_agf_text(text: str, manufacturer: str, source_id: str,
                   material_class: str = "oxide_glass") -> tuple:
    """Parse .agf text -> (glasses, properties, sellmeier, transmission, issues)."""
    glasses, props, sell, trans, issues = [], [], [], [], []
    cur = None
    parse_agf_text._seen = {}

    def flush():
        if cur is not None and cur.get("glass_name"):
            _flush_cd(cur, source_id, issues)
            _flush_td(cur, source_id, issues)
            # Manufacturer remarks (GC comments, coefficients that exceeded the
            # stored term limit) were collected but never written anywhere, so
            # they were silently discarded. Fold them into the description,
            # which is the one free-text field that survives into the database.
            remarks = cur.get("remarks") or []
            if remarks:
                base = str(cur["glass_row"].get("description") or "")
                cur["glass_row"]["description"] = (
                    base + " " + " ".join(str(r) for r in remarks)).strip()
            glasses.append(cur["glass_row"])
            props.extend(cur["props"])
            sell.extend(cur["sell"])
            trans.extend(cur["trans"])

    def flush_cd_only():
        """Flush whichever multi-line record (CD or TD) is still buffered."""
        if cur is not None and cur.get("_cd_pending"):
            _flush_cd(cur, source_id, issues)
        if cur is not None and cur.get("_td_pending"):
            _flush_td(cur, source_id, issues)

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith((";", "#", "CC", "AGF")):
            continue
        parts = line.split()
        tag = parts[0].upper()
        # Continuation lines: Nikon wraps CD and TD records across lines as
        # bare numbers with no tag. Append to whichever buffer is open.
        if _is_num(tag) or (tag.replace(".", "", 1).replace("-", "", 1)
                            .replace("+", "", 1).replace("E", "", 1)
                            .replace("e", "", 1).strip("0123456789") == ""
                            and _floats(parts)):
            if cur is not None and cur.get("_cd_pending"):
                cur["_cd_pending"].extend(_floats(parts))
                continue
            if cur is not None and cur.get("_td_pending"):
                cur["_td_pending"].extend(_floats(parts))
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
            # Every catalog GlassMatch ships uses the documented layout, so it
            # is read by position. Zemax writes nd=1.0 / vd=0 as a placeholder
            # for materials with no visible-band index (Si, CdTe, ZnSe ...);
            # the value-range search mistook the formula number "2" for n_d
            # there, so it is now only the fallback for non-standard records.
            formula_id, nd, vd, nm_status = _nm_positional(parts)
            if formula_id is None:
                nd, vd = _nm_heuristic(rest_tokens, nums_all, code_idx)
            density = None  # ED record may supply it (see _ed_block)
            if not name:
                issues.append({"line": lineno, "issue": "NM without name"})
                cur = None
                continue
            if nd is None or vd is None:
                issues.append({"line": lineno, "issue": "NM missing nd/vd",
                               "text": raw[:80]})
            if formula_id is None:
                issues.append({"line": lineno, "glass": name,
                               "issue": "NM gives no Zemax formula number; CD "
                                        "evaluated as Sellmeier-1"})
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
                     "material_class": material_class,
                     # Zemax NM status 2 = obsolete; preferred/special/melt
                     # are all still orderable, so they stay "standard".
                     "status": "obsolete" if nm_status == 2 else "standard",
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
                   "props": prows, "sell": [], "trans": [],
                   "formula_id": formula_id, "vd": vd}
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
            # TD = D0 D1 D2 E0 E1 lambda_tk T0: the SCHOTT dn/dT model's
            # coefficients (thermal dispersion, not CTE). NIKON wraps it onto
            # a second line, so it is buffered like CD.
            flush_cd_only()
            cur["_td_pending"] = _floats(parts[1:])
            continue
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
        elif tag == "OD":
            flush_cd_only()
            _od_block(cur, parts[1:], source_id)
        elif tag in ("AI", "DP"):
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


# Labels a verified row may start with. Anything else - notably the
# "Non-dispersable ..." archive label - is never evaluated.
VERIFIED_PREFIXES = ("Sellmeier", "Schott", "Herzberger", "Conrady",
                     "Handbook", "Extended",
                     # refractiveindex.info literature fits (crystal pages)
                     "Polynomial", "RefractiveIndex.INFO", "Cauchy", "Gases",
                     "Retro", "Exotic")
# A catalog prints n_d to 5-6 decimals and V_d to 2; a fit in the formula the
# catalog names reproduces both far inside these limits (median |dn| ~1e-6).
ND_TOL = 2e-4
VD_TOL = 0.5
D_LINE_UM, F_LINE_UM, C_LINE_UM = 0.5875618, 0.4861327, 0.6562725


def is_dispersable_formula(formula: str | None) -> bool:
    """True only for verified dispersion rows - the app's gate.

    Rows that fail the n(d)/V_d cross-check, or name a formula GlassMatch
    cannot evaluate, carry archived coefficients that must NEVER be drawn as
    a curve; they are labelled "Non-dispersable ...".
    """
    f = str(formula or "")
    return f.startswith(VERIFIED_PREFIXES)


# Kept for callers written when Sellmeier was the only evaluated form.
is_sellmeier1_formula = is_dispersable_formula


def verified_label(formula: int, n_terms: int | None = None) -> str:
    """The sellmeier.csv label of a verified Zemax CD row (passes the gate)."""
    from glassmatch.spectra import SELLMEIER_POLES, ZEMAX_FORMULAS
    fname = ZEMAX_FORMULAS.get(formula, f"formula {formula}")
    if formula == 2:
        return f"Sellmeier-1 ({n_terms}-term, Zemax CD record)"
    if formula in SELLMEIER_POLES:
        return f"Sellmeier ({n_terms}-term, Zemax formula {formula} {fname})"
    return f"{fname} (Zemax formula {formula}, CD record)"


def _flush_cd(cur: dict, source_id: str, issues: list) -> None:
    """Flush a buffered CD record (single-line or multi-line polynomial)."""
    pending = cur.pop("_cd_pending", None)
    lineno = cur.pop("_cd_lineno", 0)
    if not pending:
        return
    _cd_block(cur, pending, source_id, issues, lineno)


def _cd_block(cur: dict, nums: list, source_id: str,
              issues: list, lineno: int) -> None:
    """CD record: store every coefficient, and keep the fit only if it works.

    The coefficients are evaluated in the formula the NM record names (Schott,
    Sellmeier-1, Extended 3 ...). The row is dispersable only if that
    reproduces the catalog n(d) within ND_TOL and, where the catalog gives one,
    V_d within VD_TOL. A glass with no catalog n(d) (Zemax writes 1.0 as a
    placeholder for IR crystals) cannot be checked, so it is archived rather
    than trusted.

    Coefficients that fail are still stored verbatim and labelled
    non-dispersable, so nothing is lost and nothing is ever evaluated as a
    curve it is not.
    """
    from glassmatch.spectra import (MAX_TERMS, B_COLS, C_COLS, SELLMEIER_POLES,
                                    ZEMAX_FORMULAS, active_pairs,
                                    classify_dispersion, zemax_n)
    if len(nums) < 6:
        issues.append({"line": lineno, "glass": cur["glass_name"],
                       "issue": f"CD has {len(nums)} coeffs (<6)"})
        return
    declared = cur.get("formula_id")
    formula = declared if declared is not None else 2
    fname = ZEMAX_FORMULAS.get(formula, f"formula {formula}")
    row = {"glass_id": cur["glass_row"]["glass_id"], "wavelength_um": "",
           "source_id": source_id, "zemax_formula": formula,
           "coefficients": " ".join(repr(float(x)) for x in nums),
           "notes": f".agf CD coefficients, Zemax formula {formula} ({fname})."}
    n_terms = None
    if formula in SELLMEIER_POLES:
        pairs = active_pairs(nums)
        n_terms, sign_note = classify_dispersion(nums)
        if sign_note:
            row["notes"] += " " + sign_note + "."
        for i, (b, c) in enumerate(pairs[:MAX_TERMS]):
            row[B_COLS[i]] = b
            row[C_COLS[i]] = c
        if len(pairs) > SELLMEIER_POLES[formula]:
            issues.append({"line": lineno, "glass": cur["glass_name"],
                           "issue": f"CD has {len(pairs)} poles; {fname} uses "
                                    f"{SELLMEIER_POLES[formula]}"})

    def archive(why: str) -> None:
        row["formula"] = f"Non-dispersable ({why}) - archived, never evaluated"
        issues.append({"line": lineno, "glass": cur["glass_name"],
                       "issue": f"CD archived: {why}"})

    hdr = next((p["value"] for p in cur["props"]
                if p["property"] == "refractive_index_nd"), None)
    if formula not in ZEMAX_FORMULAS:
        archive(f"unknown Zemax formula {formula}")
    elif not any(float(x) != 0.0 for x in nums):
        archive("no non-zero CD coefficients")
    elif hdr is None:
        archive(f"{fname} CD with no catalog n(d) to verify against")
    else:
        nd = zemax_n(formula, nums, D_LINE_UM)
        nF = zemax_n(formula, nums, F_LINE_UM)
        nC = zemax_n(formula, nums, C_LINE_UM)
        vd = (nd - 1.0) / (nF - nC) if nF != nC else float("nan")
        cat_vd = cur.get("vd")
        if not (nd == nd) or abs(nd - float(hdr)) > ND_TOL:
            archive(f"{fname} CD gives n(d)={nd:.5f} vs catalog {hdr}")
        elif cat_vd is not None and (not (vd == vd)
                                     or abs(vd - float(cat_vd)) > VD_TOL):
            archive(f"{fname} CD gives V_d={vd:.2f} vs catalog {cat_vd}")
        else:
            row["notes"] += (f" Verified: n(d) {nd:.6f} vs catalog {hdr}; "
                             f"V_d {vd:.2f}"
                             + (f" vs catalog {cat_vd}." if cat_vd is not None
                                else "."))
            row["formula"] = verified_label(formula, n_terms)
    if n_terms and is_dispersable_formula(row.get("formula")):
        row["n_terms"] = n_terms
    cur["sell"].append(row)


TD_PROPS = (("td_D0", "1/K"), ("td_D1", "1/K^2"), ("td_D2", "1/K^3"),
            ("td_E0", "um^2/K"), ("td_E1", "um^2/K^2"), ("td_lambda_tk", "um"),
            ("td_T0", "C"))
# Zemax OD: relative cost, then climate, stain, acid, alkali and phosphate
# resistance classes. -1 (or "_") means "not given". The class scale is the
# manufacturer's own (SCHOTT uses ISO classes, the Japanese makers JOGIS), so
# these are shown per glass, never ranked across makers.
OD_PROPS = ("relative_cost", "climate_resistance", "stain_resistance",
            "acid_resistance", "alkali_resistance", "phosphate_resistance")


# |dn/dT| above this is not a material property: germanium, the largest of
# any listed material, is about 4e-4/K. NIKON's 2019 file prints J-BASF2's D0
# as -2.62 and Q-LASFH11S's as 7.32 - the 1e-6 exponent dropped - and the
# formula then returns figures near 1/K.
MAX_DN_DT = 1e-3


def _flush_td(cur: dict, source_id: str, issues: list | None = None) -> None:
    """Store a buffered TD record, plus the dn/dT it implies at the d line.

    All-zero coefficients are Zemax's way of saying "no thermal data" and are
    not stored. The derived absolute dn/dT (d line, averaged over +20..+40 C,
    the interval catalogs quote) is labelled calculated.
    """
    nums = cur.pop("_td_pending", None)
    if not nums or len(nums) < 7 or not any(nums[:5]):
        return
    gid = cur["glass_row"]["glass_id"]
    for (prop, unit), v in zip(TD_PROPS, nums[:7]):
        cur["props"].append(_prop(gid, prop, v, unit, "", source_id,
                                  ".agf TD record (thermal dn/dT model)."))
    nd = next((p["value"] for p in cur["props"]
               if p["property"] == "refractive_index_nd"), None)
    if nd:
        from glassmatch.spectra import dn_dt_abs
        v = dn_dt_abs(nums[:7], float(nd), D_LINE_UM, 20.0, 40.0)
        if v == v and abs(v) > MAX_DN_DT:
            cur.setdefault("remarks", []).append(
                f"TD record implausible (dn/dT would be {v:.3g}/K; D0 = "
                f"{nums[0]:g}, probably a dropped exponent) - stored verbatim, "
                "dn/dT not derived.")
            if issues is not None:
                issues.append({"glass": cur["glass_name"],
                               "issue": f"TD implausible: dn/dT {v:.3g}/K"})
        elif v == v:
            row = _prop(gid, "dn_dt_abs_d_20_40", round(v * 1e6, 3), "1e-6/K",
                        587.6, source_id,
                        "Absolute dn/dT at the d line, mean over +20..+40 C, "
                        "evaluated from the .agf TD coefficients (SCHOTT "
                        "dn/dT formula) with the catalog n_d.")
            row["data_type"] = "calculated"
            cur["props"].append(row)


def _od_block(cur: dict, tokens: list, source_id: str) -> None:
    gid = cur["glass_row"]["glass_id"]
    for prop, tok in zip(OD_PROPS, tokens):
        try:
            v = float(tok)
        except ValueError:
            continue                      # "_" = not given
        if v < 0:
            continue                      # -1 = not given
        cur["props"].append(_prop(
            gid, prop, v, "" if prop == "relative_cost" else "class", "",
            source_id, ".agf OD record" + (" (relative to N-BK7 / the maker's "
                                           "reference glass)." if prop ==
                                           "relative_cost" else
                                           "; class scale is the maker's own.")))


def _ed_block(cur: dict, nums: list, source_id: str) -> None:
    """ED record: CTE(-30/+70) CTE(20/+300) density dPgF.

    Observed SCHOTT/NIKON form: "ED 7.100000 8.300000 2.510000 -0.000900 0",
    CTEs in 1e-6/K, density in g/cm3, dPgF dimensionless.

    Each field is gated INDEPENDENTLY. A vendor that leaves one slot at 0.0
    (meaning "not published") must not cost us the others: CDGM publishes
    density but not CTE(-30/+70), while HIKARI and NIKON publish density but
    not CTE(20/+300). Gating density on the CTE fields - as an earlier revision
    did - silently discarded valid density for ~700 glasses. A missing CTE is
    reported missing, never inferred from the other one: CTE(-30/+70) and
    CTE(20/+300) are different quantities and are stored as separate
    properties rather than collapsed into one.
    """
    gid = cur["glass_row"]["glass_id"]
    mclass = str(cur["glass_row"].get("material_class") or "oxide_glass")
    if len(nums) >= 1 and 0 < nums[0] < 30:
        cur["props"].append(_prop(gid, "cte", nums[0], "1e-6/K", "",
                                  source_id, ".agf ED record (CTE -30/+70)."))
    if len(nums) >= 2 and 0 < nums[1] < 30:
        cur["props"].append(_prop(gid, "cte_20_300", nums[1], "1e-6/K", "",
                                  source_id, ".agf ED record (CTE 20/+300)."))
    if len(nums) >= 3:
        lo, hi = DENSITY_RANGES_BY_CLASS.get(mclass, DEFAULT_DENSITY_RANGE)
        if lo <= nums[2] <= hi:
            cur["props"].append(_prop(gid, "density", nums[2], "g/cm3", "",
                                      source_id, ".agf ED record (density)."))
    if len(nums) >= 4 and -0.05 <= nums[3] <= 0.05:
        cur["props"].append(_prop(gid, "dPgF", nums[3], "", "",
                                  source_id, ".agf ED record (dPgF)."))


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
        # 0.1-50 um: deep-UV grades (NIKON NIFS/NICF, OHARA SK-1300) list
        # 157-193 nm and IR crystals (Ge, KBr, GASIR) list out to 30 um; an
        # earlier 0.2-5 um gate silently dropped those real samples. T outside
        # 0..1 (HOYA -999 placeholders, a 12.0 typo) is still rejected.
        if 0.1 <= wl <= 50.0 and 0.0 <= tval <= 1.0:
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
               material_class: str = "oxide_glass",
               quarantine: bool = True) -> tuple:
    """Read a user-downloaded .agf file -> normalized frames + issues.

    Conflicting duplicate transmission samples (the same wavelength carrying
    two different values) are quarantined at import rather than written to the
    database: the clean frame keeps only undisputed samples, and each displaced
    row is recorded in the returned issues with both values so the change is
    auditable. Callers that persist data should write
    ``data/normalized/transmission_conflicts.csv`` from those issue rows.

    ``quarantine=False`` returns every IT sample untouched, for a caller that
    runs scripts/clean_transmission.py afterwards to write the audit ledgers.
    """
    glasses, props, sell, trans, issues = parse_agf_text(
        read_agf_file(path), manufacturer, source_id, material_class)
    if quarantine and trans is not None and not trans.empty:
        from glassmatch.validation import (dedupe_transmission,
                                           split_transmission_conflicts)
        # Identical duplicates first (no information lost), then conflicts
        # (never collapsed - quarantined with both values recorded).
        trans, dupes = dedupe_transmission(trans)
        if not dupes.empty:
            issues.append({
                "line": "", "glass": f"{len(dupes)} duplicate sample(s)",
                "issue": (f"{len(dupes)} byte-identical transmission sample(s) "
                          "collapsed (same glass, wavelength, thickness and "
                          "value) - no information lost"),
            })
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



