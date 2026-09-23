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
        "download_url": "https://www.hoya.co.jp/english/",
        "hint": "HOYA optics division publishes glass catalog data files.",
        "license": "redistribution-limited; re-download from HOYA",
        "material_class": "oxide_glass",
    },
    "CDGM": {
        "label": "CDGM optical glass",
        "download_url": "http://www.cdgmgd.com/",
        "hint": "CDGM publishes Zemax catalog files for H-series glasses.",
        "license": "redistribution-limited; re-download from CDGM",
        "material_class": "oxide_glass",
    },
    "SUMITA": {
        "label": "SUMITA optical glass",
        "download_url": "https://www.sumita-optical.co.jp/en/product/",
        "hint": "SUMITA publishes catalog data for K-series glasses.",
        "license": "redistribution-limited; re-download from SUMITA",
        "material_class": "oxide_glass",
    },
    "HIKARI": {
        "label": "HIKARI glass",
        "download_url": "https://www.hikari-glass.co.jp/",
        "hint": "HIKARI (Nippon Electric Glass) publishes E-series .agf data.",
        "license": "redistribution-limited; re-download from HIKARI",
        "material_class": "oxide_glass",
    },
    "LZOS": {
        "label": "LZOS / Shvabe glass",
        "download_url": "https://refractiveindex.info/?book=LZOS-optical",
        "hint": "LZOS catalog mirrored CC0 at refractiveindex.info.",
        "license": "CC0-1.0 (via refractiveindex.info mirror)",
        "material_class": "oxide_glass",
    },
}


def catalog_ids() -> list:
    return sorted(CATALOGS)
