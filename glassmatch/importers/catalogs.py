"""Per-manufacturer .agf download config — adding a maker = add an entry, not code."""
from __future__ import annotations

CATALOGS = {
    "SCHOTT": {
        "label": "SCHOTT optical glass",
        "download_url": "https://www.schott.com/en-us/products/optical-glass-p1000267/downloads",
        "hint": "Download 'SCHOTT Zemax catalog (.agf)' from SCHOTT Advanced Optics downloads.",
        "license": "redistribution-limited; re-download from SCHOTT",
        "material_class": "oxide_glass",
    },
    "OHARA": {
        "label": "OHARA optical glass",
        "download_url": "https://oharacorp.com/catalog/",
        "hint": "OHARA publishes Zemax-format catalog files on its download page.",
        "license": "redistribution-limited; re-download from OHARA",
        "material_class": "oxide_glass",
    },
    "HOYA": {
        "label": "HOYA optical glass",
        "download_url": "https://www.hoya-opticalworld.com/english/datadownload/",
        "hint": "Data Download -> 'ZEMAX (agf file)(include obsolete glasses)' "
                "(HOYA20260707_include_obsolete.agf as of 2026-10).",
        "license": "redistribution-limited; re-download from HOYA",
        "material_class": "oxide_glass",
    },
    "CDGM": {
        "label": "CDGM optical glass",
        "download_url": "https://www.cdgmgd.com/go.htm?k=ge_lei_xia_zai&url=downList",
        "hint": "Downloads page (各类下载) -> 'zemax格式文档' "
                "(CDGM-ZEMAX202609.AGF as of 2026-10).",
        "license": "redistribution-limited; re-download from CDGM",
        "material_class": "oxide_glass",
    },
    "SUMITA": {
        "label": "SUMITA optical glass",
        "download_url": "https://www.sumita-opt.co.jp/en/download/",
        "hint": "Downloads -> Optical Glass Data -> 'Zemax (all glasses "
                "including the discontinued ones)' (zip; 2026-08-26 as of "
                "2026-10).",
        "license": "redistribution-limited; re-download from SUMITA",
        "material_class": "oxide_glass",
    },
    "HIKARI": {
        "label": "HIKARI glass (Nikon group)",
        "download_url": "https://www.hikari-g.co.jp/optical_glass/catalog/",
        "hint": "HIKARI publishes no Zemax file: download 'HIKARI All Catalog "
                "Data' (Excel) and merge it with scripts/merge_agf.py, or use "
                "Nikon's Zemax data (see NIKON) for an .agf.",
        "license": "redistribution-limited; re-download from HIKARI",
        "material_class": "oxide_glass",
    },
    "NIKON": {
        "label": "Nikon / HIKARI Zemax data",
        "download_url": "https://www.nikon.com/business/components/downloads/",
        "hint": "'Zemax Data: AGF format in Zip file' (NIKON-HIKARI_201911.AGF, "
                "last updated Nov 2019).",
        "license": "redistribution-limited; re-download from Nikon",
        "material_class": "oxide_glass",
    },
    "LZOS": {
        "label": "LZOS / Shvabe glass",
        "download_url": "https://github.com/nzhagen/zemaxglass/tree/master/src/ZemaxGlass/AGF_files",
        "hint": "No official LZOS download was found (checked 2026-10); "
                "GlassMatch uses a third-party mirror of unknown vintage.",
        "license": "mirror-vintage-unknown; verify vs manufacturer catalog",
        "material_class": "oxide_glass",
    },
}


def catalog_ids() -> list:
    return sorted(CATALOGS)
