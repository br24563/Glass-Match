"""Lens prescriptions and first-order (paraxial) analysis.

FIRST-ORDER SCREENING ONLY. Everything here is a paraxial y-nu trace of a
rotationally symmetric, all-refracting system: focal length, back focus,
primary axial colour, secondary spectrum, Petzval sum and the thermal shift
of focus. It says nothing about aberrations beyond first order (spherical,
coma, astigmatism, distortion, lateral colour off axis), tolerances or
manufacturability. A glass that screens well here still has to be checked in
a real optical design program before anything is changed.

Prescription
------------
A list of surfaces in order from the object. Each has a radius (mm; inf =
plane), the thickness to the next surface (mm), and the material that
follows it (a glass, or None for air). Object space is air; the last
surface's material must be air. Mirrors, coordinate breaks and
non-rotationally-symmetric surfaces are refused, not approximated.

Readers: JSON, CSV, Zemax OpticStudio .zmx (sequential, STANDARD and EVENASPH
surfaces) and CODE V .seq (S/SO/SI/STO lines, radius or curvature mode).

Indices
-------
Every index is relative to air (air = 1 exactly), which is what a lens in
air sees. At the catalog temperature they come from db.n_at; at another
temperature from glassmatch.thermal.index_at (relative to air at that
temperature and pressure), and nothing is extrapolated - a glass without an
index at a wavelength or temperature makes the result unavailable, with the
reason.

Thermal model
-------------
From T0 = 20 C to T: glass thicknesses scale with that glass's CTE, air
spaces with the mount CTE, each radius with the CTE of the glass after the
surface (the glass before it for a lens's last surface), indices from
n(lambda, T). The image plane is held by the mount, so the thermal focus
shift is BFL(T) - BFL(T0) (1 + alpha_mount (T - T0)). Catalog CTEs are the
-30/+70 C means; outside that range no thermal shift is given unless the
caller explicitly allows a linear extrapolation, which is then labelled.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

LINES_NM = {"g": 435.8343, "F": 486.1327, "e": 546.074, "d": 587.5618,
            "C": 656.2725}
T_REF = 20.0
CTE_RANGE = (-30.0, 70.0)


@dataclass
class Surface:
    radius: float                 # mm; math.inf for a plane
    thickness: float              # mm to the next surface
    material: str | None = None   # glass_id after this surface; None = air
    semi_diameter: float | None = None
    label: str = ""               # the glass as the file named it

    @property
    def curvature(self) -> float:
        return 0.0 if math.isinf(self.radius) or self.radius == 0 else 1.0 / self.radius


@dataclass
class Prescription:
    surfaces: list
    name: str = ""
    object_distance: float = math.inf   # mm before the first surface
    stop: int | None = None
    notes: list = field(default_factory=list)

    def glasses(self) -> list:
        return sorted({s.material for s in self.surfaces if s.material})

    def with_material(self, old: str, new: str, media=None) -> "Prescription":
        """A copy with glass `old` replaced by `new` (in every medium, or in
        the medium indices given)."""
        surfs = [replace(s, material=new) if s.material == old
                 and (media is None or i in media) else s
                 for i, s in enumerate(self.surfaces)]
        return replace(self, surfaces=surfs)

    def with_curvature(self, i: int, c: float) -> "Prescription":
        surfs = list(self.surfaces)
        surfs[i] = replace(surfs[i], radius=math.inf if c == 0 else 1.0 / c)
        return replace(self, surfaces=surfs)

    def to_dict(self) -> dict:
        return {"name": self.name, "units": "mm",
                "object_distance": (None if math.isinf(self.object_distance)
                                    else self.object_distance),
                "surfaces": [{"radius": (None if math.isinf(s.radius) else s.radius),
                              "thickness": s.thickness, "glass": s.material,
                              "semi_diameter": s.semi_diameter}
                             for s in self.surfaces]}


class PrescriptionError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Glass names

def _key(name) -> str:
    return re.sub(r"\s+", "", str(name or "")).upper()


def resolve_glass(db, name: str, makers=()) -> str:
    """glass_id for a name as a lens file writes it ('N-BK7', 'NBK7_SCHOTT',
    'S-BSL7.OHARA', or an id). makers narrows an ambiguous name. Raises
    PrescriptionError rather than guess."""
    g = db.glasses
    raw = str(name).strip().strip("'\"")
    if (g["glass_id"] == raw).any():
        return raw
    makers = [m.upper() for m in makers if m]
    m = re.fullmatch(r"(.+?)[_.]([A-Za-z]+)", raw)
    if m and m.group(2).upper() in set(g["manufacturer_id"].str.upper()):
        raw, makers = m.group(1), [m.group(2).upper()]
    keys = g["glass_name"].map(_key)
    want = _key(raw)
    # Exact name first, then without hyphens (CODE V writes 'NBK7').
    for cand, w in ((keys, want),
                    (keys.str.replace("-", "", regex=False), want.replace("-", ""))):
        hit = g[cand == w]
        if makers:
            narrowed = hit[hit["manufacturer_id"].str.upper().isin(makers)]
            hit = narrowed if not narrowed.empty else hit
        if len(hit) == 1:
            return str(hit["glass_id"].iloc[0])
        if len(hit) > 1:
            # One maker listing a name twice (HIKARI's -MOLD variants): the
            # glass whose id is MAKER-NAME is the catalog glass.
            if hit["manufacturer_id"].nunique() == 1:
                ids = hit["manufacturer_id"].str.upper() + "-" + hit["glass_name"].map(_key)
                exact = hit[hit["glass_id"].str.upper() == ids]
                if len(exact) == 1:
                    return str(exact["glass_id"].iloc[0])
            raise PrescriptionError(
                f"glass {name!r} is ambiguous: {', '.join(hit['glass_id'])} - "
                "name the maker (catalog) or use the glass id")
    raise PrescriptionError(f"glass {name!r} is not in the database")


# ---------------------------------------------------------------------------
# Readers

def _radius(v) -> float:
    if v is None or str(v).strip().lower() in ("", "inf", "infinity", "none"):
        return math.inf
    r = float(v)
    return math.inf if r == 0 else r


def _material(db, v, makers):
    if v is None or str(v).strip().upper() in ("", "AIR", "NONE"):
        return None, ""
    if str(v).strip().upper() == "MIRROR":
        raise PrescriptionError("mirrors are not supported (refracting "
                                "systems only)")
    return resolve_glass(db, v, makers), str(v).strip()


def from_dict(db, d: dict) -> Prescription:
    scale = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}[
        str(d.get("units", "mm")).lower()]
    makers = d.get("makers", ())
    surfs = []
    for i, s in enumerate(d["surfaces"]):
        mat, label = _material(db, s.get("glass"), [s.get("maker")] + list(makers))
        r = _radius(s.get("radius"))
        surfs.append(Surface(r * scale if not math.isinf(r) else r,
                             float(s.get("thickness") or 0.0) * scale, mat,
                             (float(s["semi_diameter"]) * scale
                              if s.get("semi_diameter") not in (None, "") else None),
                             label))
    od = d.get("object_distance")
    return _checked(Prescription(
        surfs, str(d.get("name", "")),
        math.inf if od in (None, "", "inf") else float(od) * scale,
        d.get("stop")))


def read_json(db, text: str) -> Prescription:
    return from_dict(db, json.loads(text))


def read_csv(db, text: str) -> Prescription:
    """Columns radius, thickness, glass, and optionally maker, semi_diameter."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "radius" not in rows[0] or "thickness" not in rows[0]:
        raise PrescriptionError("CSV needs columns radius, thickness, glass")
    return from_dict(db, {"surfaces": rows})


_ZMX_UNITS = {"MM": 1.0, "CM": 10.0, "IN": 25.4, "METER": 1000.0, "M": 1000.0}


def read_zmx(db, text: str) -> Prescription:
    """Zemax OpticStudio sequential .zmx: SURF blocks with TYPE, CURV, DISZ,
    GLAS, DIAM, STOP; UNIT and GCAT at the top. EVENASPH surfaces count
    their r^2 term (PARM 1) in the paraxial curvature."""
    scale, makers, blocks, cur = 1.0, [], [], None
    for line in text.splitlines():
        tok = line.split()
        if not tok:
            continue
        k = tok[0]
        if k == "UNIT" and len(tok) > 1:
            scale = _ZMX_UNITS.get(tok[1].upper())
            if scale is None:
                raise PrescriptionError(f"unknown .zmx unit {tok[1]!r}")
        elif k == "GCAT":
            makers = tok[1:]
        elif k == "MODE" and len(tok) > 1 and tok[1].upper() != "SEQ":
            raise PrescriptionError("non-sequential .zmx files are not supported")
        elif k == "SURF":
            cur = {"type": "STANDARD", "curv": 0.0, "disz": 0.0, "glas": None,
                   "diam": None, "stop": False, "parm1": 0.0}
            blocks.append(cur)
        elif cur is not None:
            if k == "TYPE":
                cur["type"] = tok[1].upper()
            elif k == "CURV":
                cur["curv"] = float(tok[1])
            elif k == "DISZ":
                cur["disz"] = (math.inf if tok[1].upper() == "INFINITY"
                               else float(tok[1]))
            elif k == "GLAS":
                cur["glas"] = tok[1]
            elif k == "DIAM":
                cur["diam"] = float(tok[1])
            elif k == "STOP":
                cur["stop"] = True
            elif k == "PARM" and len(tok) > 2 and tok[1] == "1":
                cur["parm1"] = float(tok[2])
    if len(blocks) < 3:
        raise PrescriptionError("no lens surfaces found in the .zmx file")
    obj, lens = blocks[0], blocks[1:-1]
    surfs, stop = [], None
    for i, b in enumerate(lens):
        if b["type"] not in ("STANDARD", "EVENASPH"):
            raise PrescriptionError(
                f"surface {i + 1} is TYPE {b['type']}: only STANDARD and "
                "EVENASPH surfaces are supported for paraxial screening")
        if b["glas"] and b["glas"].upper().startswith("___BLANK"):
            raise PrescriptionError(
                f"surface {i + 1} uses a model glass (n_d/V_d only), which "
                "has no dispersion to trace")
        c = b["curv"] / scale + (2.0 * b["parm1"] / scale
                                 if b["type"] == "EVENASPH" else 0.0)
        mat, label = _material(db, b["glas"], makers)
        surfs.append(Surface(math.inf if c == 0 else 1.0 / c,
                             b["disz"] * scale if not math.isinf(b["disz"]) else 0.0,
                             mat, b["diam"] * scale if b["diam"] else None, label))
        if b["stop"]:
            stop = i
    od = obj["disz"]
    return _checked(Prescription(surfs, "", od * scale if not math.isinf(od)
                                 else math.inf, stop))


_SEQ_UNITS = {"M": 1.0, "C": 10.0, "I": 25.4}


def read_seq(db, text: str) -> Prescription:
    """CODE V .seq: DIM, RDM, SO, S, STO, SI. Glasses as NAME_MAKER (or
    NAME.MAKER, or a quoted name). Other commands are ignored; a fictitious
    glass ('1.5:60') is refused."""
    scale, curv_mode, surfs, stop, od = 1.0, False, [], None, math.inf
    for raw in text.splitlines():
        line = raw.split("!")[0].strip()
        if not line:
            continue
        tok = line.replace(";", " ").split()
        k = tok[0].upper()
        if k == "DIM" and len(tok) > 1:
            scale = _SEQ_UNITS.get(tok[1].upper()[0], 1.0)
        elif k == "RDM":
            curv_mode = len(tok) > 1 and tok[1].upper().startswith("N")
        elif k == "SO":
            if len(tok) > 2:
                t = float(tok[2])
                od = math.inf if abs(t) >= 1e10 else t * scale
        elif k in ("S", "STO") or re.fullmatch(r"S\d+", k):
            if k == "STO" and len(tok) == 1:
                stop = len(surfs) - 1
                continue
            v = float(tok[1]) if len(tok) > 1 else 0.0
            if curv_mode:
                r = math.inf if v == 0 else 1.0 / (v / scale)
            else:
                r = math.inf if v == 0 else v * scale
            t = float(tok[2]) * scale if len(tok) > 2 else 0.0
            g = tok[3] if len(tok) > 3 else None
            if g and re.fullmatch(r"'?[\d.]+:[\d.]+'?", g):
                raise PrescriptionError(f"fictitious glass {g} has no dispersion "
                                        "to trace")
            mat, label = _material(db, g, ())
            surfs.append(Surface(r, t, mat, None, label))
            if k == "STO":
                stop = len(surfs) - 1
        elif k == "SI":
            break
    return _checked(Prescription(surfs, "", od, stop))


def read_prescription(db, path=None, text: str | None = None,
                      fmt: str | None = None) -> Prescription:
    """Read a prescription file; the format follows the extension."""
    if text is None:
        data = Path(path).read_bytes()
        text = (data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff")
                else data.decode("utf-8-sig", errors="replace"))
    fmt = (fmt or Path(str(path)).suffix.lstrip(".")).lower()
    reader = {"json": read_json, "csv": read_csv, "zmx": read_zmx,
              "seq": read_seq}.get(fmt)
    if reader is None:
        raise PrescriptionError(f"unknown prescription format {fmt!r} "
                                "(json, csv, zmx, seq)")
    rx = reader(db, text)
    if not rx.name and path is not None:
        rx.name = Path(str(path)).stem
    return rx


def _checked(rx: Prescription) -> Prescription:
    if not rx.surfaces:
        raise PrescriptionError("the prescription has no surfaces")
    if rx.surfaces[-1].material is not None:
        raise PrescriptionError("the last surface must be followed by air")
    return rx


# ---------------------------------------------------------------------------
# Paraxial trace

def indices(db, rx: Prescription, wavelength_nm: float, t_c: float | None = None,
            p_pa: float | None = None) -> tuple:
    """Relative index of each medium (object space first) -> (list, reason).
    t_c None: catalog index (db.n_at)."""
    from glassmatch import thermal
    out, cache = [1.0], {}
    for s in rx.surfaces:
        g = s.material
        if g is None:
            out.append(1.0)
            continue
        if g not in cache:
            if t_c is None:
                v, _ = db.n_at(g, wavelength_nm)
                cache[g] = (v, None if v is not None else
                            f"{g}: no index at {wavelength_nm:g} nm")
            else:
                r = thermal.index_at(db, g, wavelength_nm, t_c,
                                     thermal.P0 if p_pa is None else p_pa)
                cache[g] = (r["n"], None if r["n"] is not None else
                            f"{g}: {r['reason']}")
        v, why = cache[g]
        if v is None:
            return None, why
        out.append(v)
    return out, None


def trace(rx: Prescription, n: list) -> dict:
    """y-nu marginal ray (y = 1 at the first surface) and the infinite-
    conjugate chief quantities: EFL, BFL, and the image distance for the
    prescription's object distance (from the last surface)."""
    def run(u0):
        y, nu = 1.0, n[0] * u0
        for i, s in enumerate(rx.surfaces):
            nu = nu - y * s.curvature * (n[i + 1] - n[i])
            if i < len(rx.surfaces) - 1:
                y = y + s.thickness * nu / n[i + 1]
        return y, nu / n[-1]
    y_last, u_last = run(0.0)
    if u_last == 0:
        efl = bfl = math.inf
    else:
        efl, bfl = -1.0 / u_last, -y_last / u_last
    if math.isinf(rx.object_distance):
        img = bfl
    else:
        y2, u2 = run(1.0 / rx.object_distance)
        img = math.inf if u2 == 0 else -y2 / u2
    petz = sum(s.curvature * (n[i + 1] - n[i]) / (n[i] * n[i + 1])
               for i, s in enumerate(rx.surfaces))
    return {"efl": efl, "bfl": bfl, "image_distance": img, "petzval_sum": petz}


def _scaled(db, rx: Prescription, t_c: float, mount_cte: float,
            allow_cte_extrapolation: bool = False) -> tuple:
    """Geometry at t_c: (prescription, notes). Outside the -30/+70 C range
    the catalog CTEs are means over, refuses (PrescriptionError) unless
    allow_cte_extrapolation, when the expansion is extrapolated linearly and
    the notes say so."""
    dt = t_c - T_REF
    notes, cte = [], {}
    for g in rx.glasses():
        v = db.property_value(g, "cte")
        if v is None:
            raise PrescriptionError(f"{g}: no CTE in the database")
        cte[g] = v * 1e-6
    if not (CTE_RANGE[0] <= t_c <= CTE_RANGE[1]):
        if not allow_cte_extrapolation:
            raise PrescriptionError(
                f"{t_c:g} C is outside the -30/+70 C range the catalog CTEs "
                "are means over; glass expansion is not linear that far, so "
                "the thermal shift is not given (allow CTE extrapolation to "
                "get a labelled linear estimate)")
        notes.append(f"EXTRAPOLATED: {t_c:g} C is outside the -30/+70 C range "
                     "the catalog CTEs are measured over; expansion is "
                     "extrapolated linearly from them, at your request")
    surfs = []
    for i, s in enumerate(rx.surfaces):
        after = s.material
        before = rx.surfaces[i - 1].material if i > 0 else None
        a_r = cte.get(after or before, mount_cte * 1e-6)
        a_t = cte[after] if after else mount_cte * 1e-6
        surfs.append(replace(s, radius=s.radius * (1 + a_r * dt),
                             thickness=s.thickness * (1 + a_t * dt)))
    return replace(rx, surfaces=surfs), notes


def analyse(db, rx: Prescription, primary: str = "d", short: str = "F",
            long: str = "C", extra: str = "g", t_c: float | None = None,
            mount_cte: float = 23.6, p_pa: float | None = None,
            allow_cte_extrapolation: bool = False) -> dict:
    """First-order figures of a prescription (mm). With t_c, also the
    thermal focus shift from 20 C to t_c with the given mount CTE (1e-6/K;
    23.6 = aluminium 6061)."""
    out = {"reason": None, "notes": [], "focus": {}}
    wls = {k: LINES_NM[k] for k in (primary, short, long, extra)}
    for k, wl in wls.items():
        n, why = indices(db, rx, wl)
        if n is None:
            out["reason"] = why
            return out
        out["focus"][k] = trace(rx, n)
    f = out["focus"]
    out.update({
        "efl": f[primary]["efl"], "bfl": f[primary]["bfl"],
        "image_distance": f[primary]["image_distance"],
        "petzval_sum": f[primary]["petzval_sum"],
        "axial_colour": f[short]["image_distance"] - f[long]["image_distance"],
        "secondary_spectrum": f[primary]["image_distance"]
        - (f[short]["image_distance"] + f[long]["image_distance"]) / 2,
        "extra_line_focus": f[extra]["image_distance"] - f[primary]["image_distance"],
        "lines": wls})
    if t_c is not None:
        out["thermal"] = thermal_shift(db, rx, t_c, mount_cte, primary, p_pa,
                                       allow_cte_extrapolation)
    return out


def _index_changes(db, rx: Prescription, wavelength_nm: float, t_c: float,
                   p_pa: float | None) -> tuple:
    """Per glass, the change of its relative index from 20 C to t_c ->
    ({glass_id: dn}, reason, methods). At normal pressure this is the mean
    relative dn/dT over 20 ... t_c times the span (TD model, or the maker's
    measured table - no reference temperature needed); at another pressure
    it is the difference of n(lambda, T, p) at the two temperatures."""
    from glassmatch import thermal
    out, methods = {}, set()
    for g in rx.glasses():
        if t_c == T_REF:
            out[g] = 0.0
            continue
        if p_pa is None or p_pa == thermal.P0:
            r = thermal.dn_dt(db, g, wavelength_nm, T_REF, t_c, absolute=False)
            if r["dn_dt"] is None:
                return None, f"{g}: {r['reason']}", methods
            out[g] = r["dn_dt"] * 1e-6 * (t_c - T_REF)
            methods.add(f"{g}: {r['method']}")
        else:
            a = thermal.index_at(db, g, wavelength_nm, T_REF, p_pa)
            b = thermal.index_at(db, g, wavelength_nm, t_c, p_pa)
            if a["n"] is None or b["n"] is None:
                return None, f"{g}: {a['reason'] or b['reason']}", methods
            out[g] = b["n"] - a["n"]
            methods.add(f"{g}: {b['method']}")
    return out, None, methods


def thermal_shift(db, rx: Prescription, t_c: float, mount_cte: float = 23.6,
                  line: str = "d", p_pa: float | None = None,
                  allow_cte_extrapolation: bool = False) -> dict:
    """Focus and EFL change from 20 C to t_c (mm). The design is taken at
    20 C with catalog indices; each glass's index changes by its dn over
    20 ... t_c (see _index_changes)."""
    wl = LINES_NM[line]
    res = {"t_c": t_c, "mount_cte": mount_cte, "reason": None, "notes": [],
           "methods": []}
    n0, why = indices(db, rx, wl)
    if n0 is None:
        res["reason"] = why
        return res
    dn, why, methods = _index_changes(db, rx, wl, t_c, p_pa)
    if dn is None:
        res["reason"] = why
        return res
    res["methods"] = sorted(methods)
    try:
        rx_t, notes = _scaled(db, rx, t_c, mount_cte, allow_cte_extrapolation)
    except PrescriptionError as e:
        res["reason"] = str(e)
        return res
    res["notes"] += notes
    n_t = [n0[0]] + [n0[i + 1] + (dn[s.material] if s.material else 0.0)
                     for i, s in enumerate(rx.surfaces)]
    a, b = trace(rx, n0), trace(rx_t, n_t)
    dt = t_c - T_REF
    mount_len = a["image_distance"] * (1 + mount_cte * 1e-6 * dt)
    res.update({"efl_change": b["efl"] - a["efl"],
                "focus_shift": b["image_distance"] - mount_len,
                "defocus_per_k": ((b["image_distance"] - mount_len) / dt
                                  if dt else 0.0)})
    return res


# ---------------------------------------------------------------------------
# Glass replacement

def resolve_efl(db, rx: Prescription, surface: int, target_efl: float,
                line: str = "d") -> tuple:
    """Re-solve one surface's curvature so the EFL is target_efl again.
    -> (prescription, None) or (None, reason). Secant iteration on the
    curvature; paraxial power is linear in each curvature, so it converges
    in a few steps when a solution exists."""
    n, why = indices(db, rx, LINES_NM[line])
    if n is None:
        return None, why

    def err(c):
        return 1.0 / trace(rx.with_curvature(surface, c), n)["efl"] - 1.0 / target_efl
    c0 = rx.surfaces[surface].curvature
    c1 = c0 + 1e-4 if c0 == 0 else c0 * 1.001
    e0, e1 = err(c0), err(c1)
    for _ in range(30):
        if e1 == e0:
            break
        c0, c1, e0 = c1, c1 - e1 * (c1 - c0) / (e1 - e0), e1
        e1 = err(c1)
        if abs(e1) < 1e-12:
            return rx.with_curvature(surface, c1), None
    return None, "the EFL could not be restored with that surface"


def replacement_candidates(db, rx: Prescription, old: str, media=None,
                           tol_nd: float = 0.03, tol_vd: float = 8.0,
                           statuses=None, resolve_surface: int | None = None,
                           t_c: float | None = None, mount_cte: float = 23.6,
                           max_results: int = 25, efl_tol_pct: float | None = 1.0,
                           allow_cte_extrapolation: bool = False,
                           include_mirrors: bool = False):
    """Rank available glasses as a replacement for `old` in the design.

    Curvatures are kept (or one surface is re-solved for the original EFL).
    Each candidate's figures are compared with the original design's:
    EFL change, focus change at the primary line, and the change of the
    chromatic focus spread (each line's focus minus the primary's, worst
    of short / long / extra line) - the number the list is sorted by. With
    t_c, the change in thermal focus shift too. First-order screening only.
    """
    import pandas as pd

    from glassmatch.importers.agf import AVAILABLE_STATUSES
    statuses = statuses or AVAILABLE_STATUSES
    base = analyse(db, rx, t_c=t_c, mount_cte=mount_cte,
                   allow_cte_extrapolation=allow_cte_extrapolation)
    if base["reason"]:
        raise PrescriptionError(f"the original design cannot be traced: "
                                f"{base['reason']}")
    s = db.summary_frame()
    o = s[s["glass_id"] == old]
    if o.empty:
        raise PrescriptionError(f"{old} is not in the database")
    nd0, vd0 = float(o["nd"].iloc[0]), float(o["vd"].iloc[0])
    cand = s[(s["glass_id"] != old)
             & s["status"].isin(statuses)
             & ((s["nd"] - nd0).abs() <= tol_nd)
             & ((s["vd"] - vd0).abs() <= tol_vd)]
    if not include_mirrors and "data_tier" in cand.columns:
        # A replacement must be buyable: a glass known only from a mirror of
        # unknown date may no longer exist.
        cand = cand[cand["data_tier"] != "unverified_mirror"]

    def spread(a):
        f = a["focus"]
        p = f["d"]["image_distance"]
        return {k: f[k]["image_distance"] - p for k in f if k != "d"}
    sp0 = spread(base)
    from glassmatch.supply import supply_column
    supply = supply_column(cand)
    rows = []
    for r in cand.itertuples(index=False):
        new = rx.with_material(old, r.glass_id, media)
        note = ""
        if resolve_surface is not None:
            new, why = resolve_efl(db, new, resolve_surface, base["efl"])
            if new is None:
                continue
            note = f"surface {resolve_surface + 1} re-solved"
        a = analyse(db, new, t_c=t_c, mount_cte=mount_cte,
                    allow_cte_extrapolation=allow_cte_extrapolation)
        if a["reason"]:
            continue
        d_efl_pct = (a["efl"] - base["efl"]) / base["efl"] * 100.0
        if resolve_surface is None and efl_tol_pct is not None \
                and abs(d_efl_pct) > efl_tol_pct:
            continue
        sp = spread(a)
        row = {"glass_id": r.glass_id, "supply": supply.get(r.glass_id, ""),
               "manufacturer": r.manufacturer
               if hasattr(r, "manufacturer") else "", "status": r.status,
               "nd": r.nd, "vd": r.vd,
               "colour_change_mm": max(abs(sp[k] - sp0[k]) for k in sp0),
               "efl_change_pct": d_efl_pct,
               "focus_change_mm": a["image_distance"] - base["image_distance"],
               "axial_colour_mm": a["axial_colour"],
               "secondary_spectrum_mm": a["secondary_spectrum"],
               "note": note}
        if t_c is not None:
            th, th0 = a.get("thermal", {}), base.get("thermal", {})
            row["thermal_shift_change_mm"] = (
                th["focus_shift"] - th0["focus_shift"]
                if th.get("reason") is None and th0.get("reason") is None
                and "focus_shift" in th and "focus_shift" in th0 else None)
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("colour_change_mm").head(max_results)
    return base, df.reset_index(drop=True)
