"""`glassmatch` command line: search, inspect and export without the web app.

    glassmatch version
    glassmatch info N-BK7
    glassmatch n N-BK7 486.1 587.6 656.3 1064
    glassmatch search --nd 1.50:1.55 --vd 60:70 --top 10
    glassmatch search --nd 1.6:1.8 --band 0.4:0.7 --tmin 99 --thickness 10
    glassmatch search --vd 55:75 --where athermal_gamma_air=-1:1 --sort athermal_gamma_air
    glassmatch search --nd 1.5:1.6 --columns gvd,group_index --wavelength 800
    glassmatch columns                       # every sortable column
    glassmatch n2 --material CaF2            # nonlinear index measurements
    glassmatch export-agf SCHOTT-N-BK7 OHARA-S-BSL7 -o shortlist.agf
    glassmatch check

Every number printed carries the same provenance rules as the app: catalog
values are the manufacturer's, computed ones say so, nothing is extrapolated.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd


def _range(text):
    """'1.5:1.6' -> (1.5, 1.6); '1.5:' or ':1.6' leave one side open."""
    lo, _, hi = str(text).partition(":")
    return (float(lo) if lo.strip() else None, float(hi) if hi.strip() else None)


def _resolve(db, name: str, maker: str | None = None) -> str:
    """A glass_id from an id or a glass name; errors on no or several hits."""
    g = db.glasses
    if (g["glass_id"] == name).any():
        return name
    hit = g[g["glass_name"].astype(str).str.upper() == name.upper()]
    if maker:
        hit = hit[hit["manufacturer_id"].astype(str).str.upper() == maker.upper()]
    if hit.empty:
        raise SystemExit(f"no glass named {name!r}"
                         + (f" from {maker}" if maker else ""))
    if len(hit) > 1:
        raise SystemExit(f"{name!r} is ambiguous: "
                         + ", ".join(hit["glass_id"]) + " (use the id or --maker)")
    return str(hit["glass_id"].iloc[0])


def _db():
    from glassmatch.database import load_default_database
    return load_default_database()


def cmd_version(args) -> int:
    from glassmatch import __version__
    from glassmatch.manifest import data_version, read_manifest
    from glassmatch.database import DEFAULT_DATA_DIR
    m = read_manifest(DEFAULT_DATA_DIR) or {}
    print(f"glassmatch {__version__}, data {data_version()}")
    for k, v in (m.get("summary") or {}).items():
        print(f"  {k}: {v}")
    print(f"  data directory: {DEFAULT_DATA_DIR}")
    return 0


def cmd_info(args) -> int:
    from glassmatch.database import PROPERTY_LABELS
    from glassmatch.spectra import describe_row
    db = _db()
    gid = _resolve(db, args.glass, args.maker)
    row = db.get_glass_row(gid)
    print(f"{gid}  ({row['glass_name']}, {row['manufacturer_id']}, "
          f"status: {row.get('status', 'standard')})")
    from glassmatch.supply import supply_flags
    srow = db.summary_frame().set_index("glass_id").loc[gid].to_dict()
    srow["glass_id"] = gid
    for level, text in supply_flags(srow):
        print(f"  supply ({level}): {text}")
    fit = db.sellmeier_for(gid, sellmeier_only=True)
    if fit is not None:
        lo, hi = db.dispersion_range(gid, fit)
        rng = f", valid {lo:g}-{hi:g} um" if lo is not None else ""
        print(f"  dispersion: verified {describe_row(fit)}{rng}")
    else:
        print("  dispersion: no verified fit (never evaluated)")
    for prop, label in PROPERTY_LABELS.items():
        for r in db.property_provenance(gid, prop):
            unit = r.get("unit") or ""
            unit = "" if unit != unit else unit
            print(f"  {label}: {r['value']} {unit}  [{r['data_type']}, "
                  f"{r['source_id']}]")
    return 0


def cmd_n(args) -> int:
    db = _db()
    gid = _resolve(db, args.glass, args.maker)
    if args.temperature is None and args.pressure is None and not args.absolute:
        for wl in args.wavelengths_nm:
            v, basis = db.n_at(gid, float(wl))
            print(f"{gid} n({wl:g} nm) = "
                  + (f"{v:.6f}  [{basis}]" if v is not None else
                     "unavailable (outside the source's stated range)"))
        return 0
    from glassmatch import thermal
    t = 20.0 if args.temperature is None else args.temperature
    p = thermal.P0 if args.pressure is None else args.pressure
    status = 0
    for wl in args.wavelengths_nm:
        r = thermal.index_at(db, gid, wl, t, p, absolute=args.absolute)
        head = f"{gid} n({wl:g} nm, {t:g} C) = "
        if r["n"] is None:
            print(head + f"unavailable: {r['reason']}")
            status = 1
            continue
        print(head + f"{r['n']:.6f}  [{r['basis']}; calculated]")
        print(f"   catalog n = {r['n_catalog']:.6f} at T0 = {r['t0_c']:g} C; "
              f"{r['method']}")
        for note in r["notes"]:
            print(f"   note: {note}")
    return status


def cmd_dndt(args) -> int:
    db = _db()
    gid = _resolve(db, args.glass, args.maker)
    from glassmatch import thermal
    status = 0
    for wl in args.wavelengths_nm:
        r = thermal.dn_dt(db, gid, wl, args.t1, args.t2,
                          absolute=not args.relative)
        head = (f"{gid} dn/dT({wl:g} nm, {args.t1:g} ... {args.t2:g} C, "
                f"{r['basis']}) = ")
        if r["dn_dt"] is None:
            print(head + f"unavailable: {r['reason']}")
            status = 1
            continue
        print(head + f"{r['dn_dt']:.3f}e-6/K  [{r['method']}]")
        for note in r["notes"]:
            print(f"   note: {note}")
    return status


def cmd_search(args) -> int:
    from glassmatch.importers.agf import AVAILABLE_STATUSES
    from glassmatch.matching import DEFAULT_WEIGHTS, match_glasses
    db = _db()
    summary = db.summary_frame()
    if args.maker:
        makers = {m.upper() for m in args.maker}
        summary = summary[summary["manufacturer_id"].str.upper().isin(makers)]
    req = {}
    for key, text in (("nd", args.nd), ("vd", args.vd),
                      ("density", args.density), ("cte", args.cte)):
        if text:
            req[f"{key}_min"], req[f"{key}_max"] = _range(text)
    if args.dndt_max is not None:
        req["dndt_abs_max"] = args.dndt_max
    trans = {}
    per_band = {}
    if args.band:
        from glassmatch.transmission import band_label, multi_band_transmission
        bands = [_range(b) for b in args.band]
        if any(lo is None or hi is None or lo >= hi for lo, hi in bands):
            raise SystemExit("--band needs LO:HI with LO < HI (um)")
        t_groups = {str(g): x for g, x in db.transmission.groupby("glass_id")}
        nk_groups = {str(g): x for g, x in db.spectral_nk.groupby("glass_id")}
        for gid in summary["glass_id"]:
            v, _, per = multi_band_transmission(
                db, gid, bands, args.mode, t_groups=t_groups,
                nk_groups=nk_groups, thickness_mm=args.thickness)
            trans[gid] = v
            if len(bands) > 1:
                for lo, hi, bv, _b in per:
                    per_band.setdefault(f"T_{band_label(lo, hi)}".replace(" ", ""),
                                        {})[gid] = bv
        if args.tmin is not None:
            req["transmission_min"] = args.tmin
            req["transmission_mode"] = args.mode
        if args.require_band_data:
            # No value in a band = removed, not "missing".
            summary = summary[summary["glass_id"].map(
                lambda g: trans.get(g) is not None)]
    out = match_glasses(summary, req, DEFAULT_WEIGHTS, transmissions=trans,
                        require_data=args.require_data)
    keep = set(AVAILABLE_STATUSES) | ({"obsolete"} if args.include_obsolete else set())
    if args.preferred:
        keep = {"preferred"}
    out = out[out["status"].isin(keep)]
    if not args.include_mirrors:
        out = out[out["data_tier"] != "unverified_mirror"]
    if args.band:
        out = out.assign(transmission_pct=out["glass_id"].map(trans),
                         **{c: out["glass_id"].map(v) for c, v in per_band.items()})
    cols = [c for c in ("glass_id", "status", "compatibility", "nd", "vd",
                        "density", "cte", "dn_dt", "transmission_pct",
                        *per_band)
            if c in out.columns]
    extra = [c.strip() for c in (args.columns or "").split(",") if c.strip()]
    where = {}
    for w in args.where or []:
        col, _, rng = w.partition("=")
        col, _, maker = col.strip().partition("@")
        where[col] = _range(rng) + ((maker,) if maker else ())
    wanted = list(dict.fromkeys(extra + list(where)
                                + ([args.sort] if args.sort else [])))
    wanted = [c for c in wanted if c not in out.columns]
    if wanted:
        from glassmatch import columns as gm_columns
        known = gm_columns.labels()
        bad = [c for c in wanted if c not in known]
        if bad:
            raise SystemExit("unknown column(s): " + ", ".join(bad)
                             + " (see `glassmatch columns`)")
        t_groups = None
        if any(c.startswith(("uv_edge_int", "t_")) and c.endswith(
                ("_calc", "355", "532", "1064", "1550")) for c in wanted):
            t_groups = {str(g): x for g, x in db.transmission.groupby("glass_id")}
        table = gm_columns.columns(db, summary, t_groups, args.thickness,
                                   args.wavelength)
        out = out.join(table[[c for c in wanted if c in table.columns]],
                       on="glass_id")
        if where:
            try:
                mask = gm_columns.range_filter(
                    out.set_index("glass_id"), where,
                    keep_missing=not args.require_data,
                    makers=out["manufacturer_id"].to_numpy())
            except ValueError as e:
                raise SystemExit(f"{e} (e.g. --where {next(iter(where))}@OHARA=LO:HI)")
            out = out[mask.to_numpy()]
    if args.sort:
        out = out.sort_values(args.sort, ascending=not args.desc,
                              na_position="last", kind="stable")
    cols += [c for c in dict.fromkeys(extra + list(where)
                                      + ([args.sort] if args.sort else []))
             if c in out.columns and c not in cols]
    out = out[cols].head(args.top)
    if args.csv:
        out.to_csv(args.csv, index=False)
        print(f"wrote {len(out)} rows to {args.csv}")
    else:
        with pd.option_context("display.width", 140, "display.max_columns", 20):
            print(out.to_string(index=False))
    return 0


def cmd_columns(args) -> int:
    from glassmatch import columns as gm_columns
    from glassmatch.database import MAKER_SCALE_COLUMNS
    rows = [{"column": c, "meaning": lab, "unit": unit,
             "note": "maker's own scale" if c in MAKER_SCALE_COLUMNS else ""}
            for c, (lab, unit) in gm_columns.labels().items()]
    with pd.option_context("display.width", 160, "display.max_colwidth", 70,
                           "display.max_rows", 500):
        print(pd.DataFrame(rows).to_string(index=False))
    return 0


def cmd_n2(args) -> int:
    db = _db()
    t = db.nonlinear_n2
    if t.empty:
        raise SystemExit("no n2 data (run scripts/merge_refractiveindex.py)")
    if args.material:
        t = t[t["material"].str.upper() == args.material.upper()]
    t = t.assign(n2_1e20=t["n2_m2_per_w"] * 1e20).sort_values(
        "n2_m2_per_w", kind="stable")
    with pd.option_context("display.width", 160):
        print(t[["material", "wavelength_um", "n2_1e20", "pulse_duration_s",
                 "method", "source_id"]].rename(
            columns={"n2_1e20": "n2 (1e-20 m2/W)"}).to_string(index=False))
    return 0


def _rx(db, path):
    from glassmatch import lens
    try:
        return lens.read_prescription(db, path)
    except (lens.PrescriptionError, OSError, ValueError, KeyError) as e:
        raise SystemExit(f"cannot read {path}: {e}")


def _mm(v):
    return "n/a" if v is None or v != v else f"{v:+.5f} mm"


def _design_band(args):
    """(short, mid, long) nm from --design-band (a preset name such as LWIR,
    or SHORT:MID:LONG in nm), or None for the visible F / d / C / g lines."""
    v = getattr(args, "design_band", None)
    if not v:
        return None
    from glassmatch import band
    if ":" in v:
        try:
            t = tuple(float(x) for x in v.split(":"))
        except ValueError:
            raise SystemExit("--design-band SHORT:MID:LONG takes numbers in nm")
        if len(t) != 3 or not (t[0] < t[1] < t[2]):
            raise SystemExit("--design-band needs SHORT < MID < LONG (nm)")
        return t
    key = next((k for k in band.PRESETS if k.upper().startswith(v.upper())), None)
    if key is None:
        raise SystemExit(f"unknown band {v!r}: " + ", ".join(band.PRESETS))
    return None if key.startswith("Visible") else band.PRESETS[key]


def _lines_label(tri) -> tuple:
    """Labels for the primary line, axial colour and secondary spectrum."""
    if tri is None:
        return "d line", "F-C", "d-(F+C)/2"
    s, m, lo = (f"{w / 1000:g}" for w in tri)
    return f"{m} um", f"{s}-{lo} um", f"{m}-({s}+{lo})/2 um"


def cmd_lens(args) -> int:
    from glassmatch import lens
    db = _db()
    rx = _rx(db, args.file)
    tri = _design_band(args)
    a = lens.analyse(db, rx, t_c=args.temperature, mount_cte=args.mount_cte,
                     allow_cte_extrapolation=args.allow_cte_extrapolation,
                     band=tri)
    prim, ax, sec = _lines_label(tri)
    status = dict(zip(db.glasses["glass_id"], db.glasses["status"]))
    print(f"{rx.name or args.file}: {len(rx.surfaces)} surfaces, glasses "
          + ", ".join(f"{g} [{status.get(g, '')}]" for g in rx.glasses()))
    if a["reason"]:
        print(f"cannot trace: {a['reason']}"
              + ("  (an IR design? try --design-band MWIR or LWIR)"
                 if tri is None else ""))
        return 1
    print(f"  EFL {a['efl']:.5f} mm   BFL {a['bfl']:.5f} mm   "
          f"Petzval sum {a['petzval_sum']:.6f} 1/mm  ({prim})")
    print(f"  primary axial colour {ax} {_mm(a['axial_colour'])}   secondary "
          f"spectrum {sec} {_mm(a['secondary_spectrum'])}"
          + (f"   g-d {_mm(a['extra_line_focus'])}" if tri is None else ""))
    th = a.get("thermal")
    if th:
        if th["reason"]:
            print(f"  thermal: unavailable - {th['reason']}")
        else:
            print(f"  thermal 20 -> {args.temperature:g} C (mount CTE "
                  f"{args.mount_cte:g}e-6/K): focus shift "
                  f"{_mm(th['focus_shift'])}, EFL change {_mm(th['efl_change'])}")
            for n in th["notes"]:
                print(f"    note: {n}")
    print("  First-order (paraxial) screening only: no aberrations beyond "
          "first order.")
    return 0


def cmd_replace(args) -> int:
    from glassmatch import lens
    db = _db()
    rx = _rx(db, args.file)
    status = dict(zip(db.glasses["glass_id"], db.glasses["status"]))
    if args.glass:
        try:
            old = [lens.resolve_glass(db, args.glass,
                                      [args.maker] if args.maker else
                                      sorted({g.split("-")[0] for g in rx.glasses()}))]
        except lens.PrescriptionError as e:
            raise SystemExit(str(e))
        if old[0] not in rx.glasses():
            raise SystemExit(f"{old[0]} is not used in {args.file}")
    else:
        old = [g for g in rx.glasses() if status.get(g) == "obsolete"]
        if not old:
            print("no obsolete glass in this design; name one to replace")
            return 0
    from glassmatch.importers.agf import AVAILABLE_STATUSES
    mode = "efl" if args.resolve_surface else args.mode
    tri = _design_band(args)
    line = tri[1] if tri else "d"
    ax = _lines_label(tri)[1]
    if args.use:
        # Write the design with one chosen replacement, nothing else changed.
        if len(old) != 1:
            raise SystemExit("--use needs exactly one glass to replace "
                             "(name it)")
        try:
            new_id = lens.resolve_glass(db, args.use, [args.use_maker]
                                        if args.use_maker else ())
            base = lens.analyse(db, rx, band=tri)
            new_rx, note = lens.replace_glass(
                db, rx, old[0], new_id, mode,
                resolve_surface=(args.resolve_surface - 1
                                 if args.resolve_surface else None),
                target_efl=base.get("efl"), line=line)
            if new_rx is None:
                raise SystemExit(f"cannot replace: {note}")
            text, ext, enc = lens.export_prescription(
                db, new_rx, "json" if args.output.lower().endswith(".json")
                else None)
        except lens.PrescriptionError as e:
            raise SystemExit(str(e))
        with open(args.output, "w", encoding=enc, newline="") as f:
            f.write(text)
        a = lens.analyse(db, new_rx, band=tri)
        print(f"wrote {args.output} ({ext}): {old[0]} -> {new_id}; {note or 'curvatures kept'}")
        print(f"  EFL {base['efl']:.5f} -> {a['efl']:.5f} mm, {ax} "
              f"{_mm(base['axial_colour'])} -> {_mm(a['axial_colour'])}")
        print("First-order (paraxial) screening only: verify the new design "
              "in an optical design program.")
        return 0
    for g in old:
        try:
            base, df = lens.replacement_candidates(
                db, rx, g, tol_nd=args.tol_nd, tol_vd=args.tol_vd,
                statuses=(None if not args.all_statuses else
                          AVAILABLE_STATUSES + ("obsolete",)),
                resolve_surface=(args.resolve_surface - 1
                                 if args.resolve_surface else None),
                t_c=args.temperature, mount_cte=args.mount_cte,
                allow_cte_extrapolation=args.allow_cte_extrapolation,
                max_results=args.top, efl_tol_pct=args.efl_tol,
                include_mirrors=args.include_mirrors, mode=mode, band=tri,
                tol_v_pct=args.tol_v_pct)
        except lens.PrescriptionError as e:
            raise SystemExit(str(e))
        print(f"Replacing {g} [{status.get(g, '')}] - design EFL "
              f"{base['efl']:.4f} mm, {ax} {_mm(base['axial_colour'])}")
        if df.empty:
            print("  no candidate within the tolerances")
            continue
        if args.csv:
            df.to_csv(sys.stdout, index=False, lineterminator="\n")
        else:
            show = [c for c in ("glass_id", "status", "nd", "vd",
                                "colour_change_mm", "efl_change_pct",
                                "petzval_change", "ray_height_change_pct",
                                "thermal_shift_change_mm", "supply", "note")
                    if c in df.columns]
            with pd.option_context("display.width", 250,
                                   "display.max_columns", 20,
                                   "display.max_colwidth", 60):
                print(df[show].round(5).to_string(index=False))
    print("First-order (paraxial) screening only: verify any replacement in "
          "an optical design program.")
    return 0


def cmd_audit(args) -> int:
    """Every obsolete glass in a folder of lens files, with candidates."""
    from pathlib import Path

    from glassmatch import lens
    db = _db()
    status = dict(zip(db.glasses["glass_id"], db.glasses["status"]))
    files = sorted(f for ext in ("zmx", "seq", "json", "csv")
                   for f in Path(args.directory).rglob(f"*.{ext}"))
    if not files:
        raise SystemExit(f"no .zmx / .seq / .json / .csv files in {args.directory}")
    rows, problems = [], 0
    for f in files:
        try:
            rx = lens.read_prescription(db, f)
        except (lens.PrescriptionError, ValueError, KeyError, OSError) as e:
            print(f"{f}: not read - {e}")
            problems += 1
            continue
        obs = [g for g in rx.glasses() if status.get(g) == "obsolete"]
        print(f"{f}: {len(rx.surfaces)} surfaces, "
              + (f"obsolete: {', '.join(obs)}" if obs else "no obsolete glass"))
        for g in obs:
            try:
                _, df = lens.replacement_candidates(
                    db, rx, g, tol_nd=args.tol_nd, tol_vd=args.tol_vd,
                    max_results=args.top, mode=args.mode,
                    band=_design_band(args), tol_v_pct=args.tol_v_pct)
            except lens.PrescriptionError as e:
                print(f"   {g}: {e}")
                problems += 1
                continue
            cands = (", ".join(f"{r.glass_id} ({r.colour_change_mm:.4f} mm)"
                               for r in df.itertuples()) if not df.empty
                     else "none within the tolerances")
            print(f"   {g} -> {cands}")
            for r in df.itertuples():
                rows.append({"file": str(f), "obsolete": g,
                             "candidate": r.glass_id,
                             "colour_change_mm": r.colour_change_mm,
                             "efl_change_pct": r.efl_change_pct,
                             "ray_height_change_pct": r.ray_height_change_pct,
                             "supply": r.supply})
    if args.csv:
        pd.DataFrame(rows).to_csv(args.csv, index=False)
        print(f"wrote {len(rows)} rows to {args.csv}")
    print("Each obsolete glass is ranked on its own with the others kept; "
          "first-order (paraxial) screening only.")
    return 1 if problems else 0


def cmd_band(args) -> int:
    """n, V and P for a wavelength band, every material that can give them."""
    from glassmatch import band
    db = _db()
    if args.triad:
        triad = tuple(args.triad)
    else:
        key = next((k for k in band.PRESETS if k.upper().startswith(args.preset.upper())), None)
        if key is None:
            raise SystemExit(f"unknown preset {args.preset!r}: "
                             + ", ".join(band.PRESETS))
        triad = band.PRESETS[key]
    try:
        bt = band.band_table(db, triad)
    except ValueError as e:
        raise SystemExit(str(e))
    s = db.summary_frame().set_index("glass_id")
    bt = bt.join(s[["glass", "status", "data_tier"]], on="glass_id")
    if not args.include_mirrors:
        bt = bt[bt["data_tier"] != "unverified_mirror"]
    if not args.include_obsolete:
        bt = bt[bt["status"] != "obsolete"]
    if not args.all_temperatures:
        bt = bt[bt["glass"].map(band.at_room_temperature)]
    bt = bt.sort_values("v_band", ascending=False).head(args.top)
    print(f"{band.triad_label(triad)}: V = (n_mid - 1)/(n_short - n_long), "
          "P = (n_mid - n_long)/(n_short - n_long) - calculated")
    if args.csv:
        bt.to_csv(args.csv, index=False)
        print(f"wrote {len(bt)} rows to {args.csv}")
    else:
        with pd.option_context("display.width", 200, "display.max_columns", 12):
            print(bt[["glass_id", "glass", "n_mid", "v_band", "p_band", "n_basis"]]
                  .round(5).to_string(index=False))
    return 0


def cmd_export_codev(args) -> int:
    from glassmatch.export_codev import DEFAULT_WAVELENGTHS_NM, export_codev
    db = _db()
    ids = [_resolve(db, g) for g in args.glasses]
    text, exported, skipped = export_codev(
        db, ids, args.wavelengths or DEFAULT_WAVELENGTHS_NM)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print(f"wrote {len(exported)} private glass(es) to {args.output}")
    for gid, why in skipped:
        print(f"  skipped {gid}: {why}")
    return 0


def cmd_export_agf(args) -> int:
    from glassmatch.export_agf import export_agf
    db = _db()
    ids = [_resolve(db, g) for g in args.glasses]
    res = export_agf(db, ids)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        f.write(res.text)
    print(f"wrote {len(res.exported)} glass(es) to {args.output}")
    for gid, why in res.skipped:
        print(f"  skipped {gid}: {why}")
    return 0


def cmd_check(args) -> int:
    from glassmatch.database import DEFAULT_DATA_DIR
    from glassmatch.manifest import data_version, stale_files
    bad = stale_files(DEFAULT_DATA_DIR)
    if bad:
        print("data differs from MANIFEST.json: " + ", ".join(bad))
        return 1
    print(f"data {data_version()} matches its manifest")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="glassmatch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="package and data version").set_defaults(
        func=cmd_version)
    p = sub.add_parser("info", help="one glass, every property with its source")
    p.add_argument("glass")
    p.add_argument("--maker")
    p.set_defaults(func=cmd_info)
    p = sub.add_parser("n", help="index at wavelengths (nm), optionally at "
                       "another temperature / pressure")
    p.add_argument("glass")
    p.add_argument("wavelengths_nm", type=float, nargs="+")
    p.add_argument("--maker")
    p.add_argument("--temperature", "-T", type=float,
                   help="glass and air temperature, C (default: catalog)")
    p.add_argument("--pressure", type=float,
                   help="air pressure, Pa (default 101325; 0 = vacuum)")
    p.add_argument("--absolute", action="store_true",
                   help="absolute index (vacuum) instead of relative to air")
    p.set_defaults(func=cmd_n)
    p = sub.add_parser("dndt", help="mean dn/dT over a temperature interval")
    p.add_argument("glass")
    p.add_argument("wavelengths_nm", type=float, nargs="+")
    p.add_argument("--t1", type=float, default=20.0)
    p.add_argument("--t2", type=float, default=40.0)
    p.add_argument("--relative", action="store_true",
                   help="relative to air at normal pressure (default absolute)")
    p.add_argument("--maker")
    p.set_defaults(func=cmd_dndt)
    p = sub.add_parser("search", help="rank glasses against requirements")
    p.add_argument("--nd", help="LO:HI")
    p.add_argument("--vd", help="LO:HI")
    p.add_argument("--density", help="LO:HI (g/cm3)")
    p.add_argument("--cte", help="LO:HI (1e-6/K)")
    p.add_argument("--dndt-max", type=float,
                   help="max |dn/dT|, d line, 20/40 C (1e-6/K)")
    p.add_argument("--band", action="append",
                   help="transmission band LO:HI (um); repeat for several "
                        "bands that must all be met (transmission_pct is "
                        "then the worst band)")
    p.add_argument("--tmin", type=float,
                   help="min transmission (%%), in every band")
    p.add_argument("--require-band-data", action="store_true",
                   help="remove glasses with no transmission value in a "
                        "band, instead of listing them as missing")
    p.add_argument("--mode", default="Average",
                   choices=["Average", "Minimum", "Entire range"])
    p.add_argument("--thickness", type=float, default=10.0,
                   help="sample thickness for transmission (mm)")
    p.add_argument("--maker", nargs="*")
    p.add_argument("--preferred", action="store_true",
                   help="only the makers' preferred glasses")
    p.add_argument("--include-obsolete", action="store_true")
    p.add_argument("--include-mirrors", action="store_true",
                   help="include glasses known only from third-party mirrors "
                        "of unknown date (hidden by default)")
    p.add_argument("--require-data", action="store_true")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--columns", help="extra columns, comma-separated "
                                     "(see `glassmatch columns`)")
    p.add_argument("--where", action="append", metavar="COL=LO:HI",
                   help="range filter on any column; repeatable. Maker-scale "
                        "columns (chemical classes, abrasion, grindability) "
                        "need the maker: COL@MAKER=LO:HI")
    p.add_argument("--sort", help="sort by this column (ascending)")
    p.add_argument("--desc", action="store_true", help="sort descending")
    p.add_argument("--wavelength", type=float, default=1064.0,
                   help="wavelength (nm) for n_at, dn_dlambda, group_index, gvd")
    p.add_argument("--csv", help="write the results to this CSV file")
    p.set_defaults(func=cmd_search)
    sub.add_parser("columns", help="every sortable column, with its meaning"
                   ).set_defaults(func=cmd_columns)
    p = sub.add_parser("n2", help="nonlinear index n2 measurements (crystals)")
    p.add_argument("--material", help="e.g. CaF2, SiO2, ZnSe")
    p.set_defaults(func=cmd_n2)
    p = sub.add_parser("lens", help="first-order analysis of a lens file "
                       "(.json .csv .zmx .seq)")
    p.add_argument("file")
    p.add_argument("--temperature", "-T", type=float,
                   help="also the thermal focus shift from 20 C to T")
    p.add_argument("--allow-cte-extrapolation", action="store_true",
                   help="outside -30/+70 C, extrapolate the catalog CTEs "
                        "linearly (labelled) instead of refusing")
    p.add_argument("--mount-cte", type=float, default=23.6,
                   help="mount CTE, 1e-6/K (default 23.6, aluminium 6061)")
    p.add_argument("--design-band",
                   help="trace at another band: a preset (NIR, SWIR, MWIR, "
                        "LWIR) or SHORT:MID:LONG in nm; default visible F/d/C/g")
    p.set_defaults(func=cmd_lens)
    p = sub.add_parser("replace", help="rank replacements for a glass in a "
                       "lens design (default: its obsolete glasses)")
    p.add_argument("file")
    p.add_argument("glass", nargs="?")
    p.add_argument("--maker")
    p.add_argument("--resolve-surface", type=int,
                   help="re-solve this surface's curvature (1-based) to keep "
                        "the EFL")
    p.add_argument("--tol-nd", type=float, default=0.03)
    p.add_argument("--tol-vd", type=float, default=8.0)
    p.add_argument("--efl-tol", type=float, default=1.0,
                   help="max EFL change, %% (without --resolve-surface)")
    p.add_argument("--temperature", "-T", type=float,
                   help="also compare the thermal focus shift at T")
    p.add_argument("--mount-cte", type=float, default=23.6)
    p.add_argument("--allow-cte-extrapolation", action="store_true",
                   help="outside -30/+70 C, extrapolate the catalog CTEs "
                        "linearly (labelled) instead of refusing")
    p.add_argument("--include-mirrors", action="store_true",
                   help="also consider glasses known only from third-party "
                        "mirrors of unknown date")
    p.add_argument("--all-statuses", action="store_true",
                   help="include obsolete glasses as candidates")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--csv", action="store_true")
    p.add_argument("--mode", choices=("element", "curvatures"), default="element",
                   help="element (default): each replaced element keeps its "
                        "own power; curvatures: every curvature kept")
    p.add_argument("--use", metavar="NEW_GLASS",
                   help="write the design with this replacement (needs -o)")
    p.add_argument("--use-maker")
    p.add_argument("-o", "--output",
                   help="with --use: the file to write (same format as the "
                        "input, only changed lines touched; or .json)")
    p.add_argument("--design-band",
                   help="trace at another band: a preset (NIR, SWIR, MWIR, "
                        "LWIR) or SHORT:MID:LONG in nm; default visible F/d/C/g")
    p.add_argument("--tol-v-pct", type=float, default=25.0,
                   help="with --design-band: V_band window, %% of the "
                        "replaced glass's value")
    p.set_defaults(func=cmd_replace)
    p = sub.add_parser("audit", help="find obsolete glasses in a folder of "
                       "lens files and rank replacements")
    p.add_argument("directory")
    p.add_argument("--mode", choices=("element", "curvatures"), default="element")
    p.add_argument("--tol-nd", type=float, default=0.03)
    p.add_argument("--tol-vd", type=float, default=8.0)
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--csv", help="write every candidate to this CSV")
    p.add_argument("--design-band",
                   help="trace at another band: a preset (NIR, SWIR, MWIR, "
                        "LWIR) or SHORT:MID:LONG in nm; default visible F/d/C/g")
    p.add_argument("--tol-v-pct", type=float, default=25.0,
                   help="with --design-band: V_band window, %% of the "
                        "replaced glass's value")
    p.set_defaults(func=cmd_audit)
    p = sub.add_parser("band", help="n, V and P in any wavelength band "
                       "(e.g. LWIR), from verified fits")
    p.add_argument("--preset", default="LWIR",
                   help="Visible, NIR, SWIR, MWIR or LWIR (default LWIR)")
    p.add_argument("--triad", type=float, nargs=3, metavar=("SHORT", "MID", "LONG"),
                   help="your own wavelengths, nm")
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--include-mirrors", action="store_true")
    p.add_argument("--include-obsolete", action="store_true")
    p.add_argument("--all-temperatures", action="store_true",
                   help="include crystal measurements away from room temperature")
    p.add_argument("--csv")
    p.set_defaults(func=cmd_band)
    p = sub.add_parser("export-codev", help="write glasses as a CODE V "
                       "private catalog (.seq)")
    p.add_argument("glasses", nargs="+")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--wavelengths", type=float, nargs="+",
                   help="nm (default: t C d e F g h lines)")
    p.set_defaults(func=cmd_export_codev)
    p = sub.add_parser("export-agf", help="write glasses as a Zemax .agf")
    p.add_argument("glasses", nargs="+")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_export_agf)
    sub.add_parser("check", help="verify the data against MANIFEST.json"
                   ).set_defaults(func=cmd_check)
    return ap


def main(argv=None) -> int:
    # Labels use symbols (−, γ, ³) a legacy Windows console code page cannot
    # print; degrade them rather than crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
