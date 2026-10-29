"""`glassmatch` command line: search, inspect and export without the web app.

    glassmatch version
    glassmatch info N-BK7
    glassmatch n N-BK7 486.1 587.6 656.3 1064
    glassmatch search --nd 1.50:1.55 --vd 60:70 --top 10
    glassmatch search --nd 1.6:1.8 --band 0.4:0.7 --tmin 99 --thickness 10
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
    for wl in args.wavelengths_nm:
        v, basis = db.n_at(gid, float(wl))
        print(f"{gid} n({wl:g} nm) = "
              + (f"{v:.6f}  [{basis}]" if v is not None else
                 "unavailable (outside the source's stated range)"))
    return 0


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
    if args.band:
        from glassmatch.transmission import band_transmission
        lo, hi = _range(args.band)
        t_groups = {str(g): x for g, x in db.transmission.groupby("glass_id")}
        nk_groups = {str(g): x for g, x in db.spectral_nk.groupby("glass_id")}
        for gid in summary["glass_id"]:
            v, _ = band_transmission(db, gid, lo, hi, args.mode,
                                     t_groups=t_groups, nk_groups=nk_groups,
                                     thickness_mm=args.thickness)
            trans[gid] = v
        if args.tmin is not None:
            req["transmission_min"] = args.tmin
            req["transmission_mode"] = args.mode
    out = match_glasses(summary, req, DEFAULT_WEIGHTS, transmissions=trans,
                        require_data=args.require_data)
    keep = set(AVAILABLE_STATUSES) | ({"obsolete"} if args.include_obsolete else set())
    if args.preferred:
        keep = {"preferred"}
    out = out[out["status"].isin(keep)]
    if args.band:
        out = out.assign(transmission_pct=out["glass_id"].map(trans))
    cols = [c for c in ("glass_id", "status", "compatibility", "nd", "vd",
                        "density", "cte", "dn_dt", "transmission_pct")
            if c in out.columns]
    out = out[cols].head(args.top)
    if args.csv:
        out.to_csv(args.csv, index=False)
        print(f"wrote {len(out)} rows to {args.csv}")
    else:
        with pd.option_context("display.width", 140, "display.max_columns", 20):
            print(out.to_string(index=False))
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
    p = sub.add_parser("n", help="index at wavelengths (nm)")
    p.add_argument("glass")
    p.add_argument("wavelengths_nm", type=float, nargs="+")
    p.add_argument("--maker")
    p.set_defaults(func=cmd_n)
    p = sub.add_parser("search", help="rank glasses against requirements")
    p.add_argument("--nd", help="LO:HI")
    p.add_argument("--vd", help="LO:HI")
    p.add_argument("--density", help="LO:HI (g/cm3)")
    p.add_argument("--cte", help="LO:HI (1e-6/K)")
    p.add_argument("--dndt-max", type=float,
                   help="max |dn/dT|, d line, 20/40 C (1e-6/K)")
    p.add_argument("--band", help="transmission band LO:HI (um)")
    p.add_argument("--tmin", type=float, help="min transmission (%%) in band")
    p.add_argument("--mode", default="Average",
                   choices=["Average", "Minimum", "Entire range"])
    p.add_argument("--thickness", type=float, default=10.0,
                   help="sample thickness for transmission (mm)")
    p.add_argument("--maker", nargs="*")
    p.add_argument("--preferred", action="store_true",
                   help="only the makers' preferred glasses")
    p.add_argument("--include-obsolete", action="store_true")
    p.add_argument("--require-data", action="store_true")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--csv", help="write the results to this CSV file")
    p.set_defaults(func=cmd_search)
    p = sub.add_parser("export-agf", help="write glasses as a Zemax .agf")
    p.add_argument("glasses", nargs="+")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_export_agf)
    sub.add_parser("check", help="verify the data against MANIFEST.json"
                   ).set_defaults(func=cmd_check)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
