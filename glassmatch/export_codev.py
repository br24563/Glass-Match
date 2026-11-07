"""Export a selection of glasses as a CODE V private glass catalog.

CODE V defines private glasses with a PRV block in a sequence (.seq) file:

    PRV
    PWL 1013.98 656.2725 587.5618 ...        wavelengths, nm
    'SCHOTT_N-BK7' 1.5075 1.5143 1.5168 ...   index at each wavelength
    END

Each index is CALCULATED by GlassMatch from the glass's verified dispersion
fit (or its tabulated literature n), at a wavelength inside the range the
source states. A glass that cannot give an index at every listed wavelength
is skipped and reported - nothing is extrapolated. CODE V interpolates
between the listed wavelengths, so list enough of them to cover the band you
design in.

Names are MAKER_NAME ('HOYA_E-FD5'), deliberately different from CODE V's
own catalog spelling ('E-FD5_HOYA'), so a private copy is never mistaken for
the maker's catalog entry. Run the file in CODE V (IN filename) before
referring to the glasses.
"""
from __future__ import annotations

import datetime as _dt

# t, C, d, e, F, g, h lines (nm)
DEFAULT_WAVELENGTHS_NM = (1013.98, 656.2725, 587.5618, 546.074, 486.1327,
                          435.8343, 404.6561)


def private_name(db, glass_id: str) -> str:
    row = db.glasses[db.glasses["glass_id"] == glass_id]
    if row.empty:
        return glass_id
    name = str(row["glass_name"].iloc[0])
    maker = str(row["manufacturer_id"].iloc[0])
    if maker == "RII":                       # crystals: the id is the name
        return glass_id.upper()
    return f"{maker}_{name}".replace(" ", "_").replace("'", "").upper()


def export_codev(db, glass_ids, wavelengths_nm=DEFAULT_WAVELENGTHS_NM,
                 today: _dt.date | None = None) -> tuple:
    """-> (text, exported {private name: glass_id}, skipped [(glass_id, why)])."""
    from glassmatch import __version__
    from glassmatch.manifest import data_version
    today = today or _dt.date.today()
    wls = [float(w) for w in wavelengths_nm]
    exported, skipped, rows = {}, [], []
    for gid in dict.fromkeys(glass_ids):
        if not (db.glasses["glass_id"] == gid).any():
            skipped.append((gid, "not in the database"))
            continue
        ns, kinds = [], set()
        for wl in wls:
            v, kind = db.n_at(gid, wl)
            if v is None:
                break
            ns.append(v)
            kinds.add(kind)
        if len(ns) != len(wls):
            skipped.append((gid, f"no index at {wl:g} nm inside the source's "
                                 "stated range (not extrapolated)"))
            continue
        name = private_name(db, gid)
        if name in exported:
            skipped.append((gid, f"name {name} already used by {exported[name]}"))
            continue
        exported[name] = gid
        rows.append((name, ns, gid, kinds))
    lines = [f"! GlassMatch {__version__} CODE V private glass catalog, "
             f"{today.isoformat()}, data version {data_version()}.",
             "! Indices are CALCULATED from each glass's verified dispersion fit "
             "(or tabulated literature n),",
             "! only inside the wavelength range its source states.",
             "! Glass: source glass id"]
    lines += [f"!   {name}: {gid}" for name, _, gid, _ in rows]
    if skipped:
        lines.append(f"! Not exported ({len(skipped)}):")
        lines += [f"!   {gid}: {why}" for gid, why in skipped]
    if rows:
        lines += ["PRV", "PWL " + " ".join(f"{w:.10g}" for w in wls)]
        lines += [f"'{name}' " + " ".join(f"{n:.6f}" for n in ns)
                  for name, ns, _, _ in rows]
        lines.append("END")
    return "\n".join(lines) + "\n", exported, skipped
