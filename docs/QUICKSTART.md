# GlassMatch quickstart

Five common jobs, each in the web app and on the command line. Start the app
with `python -m streamlit run app.py` (or `start.bat` on Windows); the
command line is `glassmatch` (or `python -m glassmatch`).

Every number GlassMatch shows says where it came from: **manufacturer**
(the maker's catalog), **literature** (a published measurement) or
**calculated** (computed by GlassMatch from stored data, never outside the
range its source states). Missing data is shown as missing, not as a failure,
unless you tick *Require available data*.

## 1. Find a glass for a set of requirements

**App:** sidebar → set the n_d and V_d ranges, the wavelength band and the
minimum transmission, then read the *Search & Compare* tab (Ranked matches). The
*Compatibility Score* is a weighted match to your requirements (expand
*Score breakdown* on *Glass Detail* to see each part); the *supply* column
lists catalog facts that make a glass hard to buy (obsolete, made on request,
rarely melted, expensive).

**CLI:**

```text
glassmatch search --nd 1.5:1.55 --vd 60:70 --preferred --top 10
glassmatch info N-BK7 --maker SCHOTT          # every property with its source
```

Glasses known only from a third-party mirror of unknown date (Corning, LZOS,
RPO, several IR makers) are hidden by default: tick *Include unverified
mirrors* or pass `--include-mirrors` to see them.

## 2. Two wavelength bands at once (e.g. visible and LWIR)

**App:** sidebar → *Additional wavelength bands (all must be met)* → add
9000–10000 nm next to 400–700 nm. Tick *Require available data*: most oxide
glasses have no transmission data past ~2.5 µm and would otherwise appear as
"missing". Each band gets its own column; the transmission figure is the
worst band.

**CLI:**

```text
glassmatch search --band 0.4:0.7 --band 9:10 --tmin 80 --require-data
```

A band value needs at least two samples spanning half the band, and a
reflection-only (Fresnel) estimate is never counted as transmission.

## 3. Index at another temperature or in vacuum

**App:** *Glass Detail* → *Index at temperature n(λ, T, p)*: set the
temperature, the air pressure (0 = vacuum) and relative / absolute.

**CLI:**

```text
glassmatch n N-BK7 587.6 -T -20 --maker SCHOTT        # relative to air at -20 C
glassmatch n N-BK7 587.6 --pressure 0 --maker SCHOTT  # in vacuum
glassmatch dndt S-FPL51 1550 --t1 -20 --t2 0 --relative --maker OHARA
```

The SCHOTT dn/dT model is used inside its stated range (−100 … +140 °C,
365 … 1014 nm); elsewhere the maker's measured dn/dT table, when it covers
the span. Nothing is extrapolated, and a note appears when the maker's own
table disagrees with the model.

## 3b. Infrared: dispersion in your band

**App:** sidebar → *Dispersion band* → e.g. *LWIR (8 / 10 / 12 µm)*. The
*Glass Map* then plots n vs V_band and P_band vs V_band, and the *Pair Finder*
ranks doublets with that band's V and P. Set the sidebar wavelength band to
the same band so materials are judged by their transmission there; IR bands
are listed under *Bands that must have transmission data* by default, so
glasses with no data (most oxide glasses past 2.5 µm) are removed.

**CLI:**

```text
glassmatch band --preset LWIR
glassmatch band --triad 3000 4000 5000
glassmatch search --band 8:12 --tmin 50 --require-band-data
```

## 4. Doublet and athermal glass pairs

**App:** *Pair Finder* → rank by low element powers, low secondary spectrum,
apochromat candidates, or *Athermal (mount CTE)* with the mount's CTE and
whether the lens works in air or vacuum. These are thin-lens, first-order
starting points for a lens-design program, not designs.

## 5. Replace an obsolete glass in an existing lens

**App:** *Lens Glass Replacement* → upload the prescription (JSON, CSV, Zemax
.zmx, CODE V .seq). Read the first-order figures (EFL, BFL, axial colour,
secondary spectrum, thermal focus shift for the mount CTE), pick the glass to
replace and how the design adapts:

* **Keep each replaced element's power** (default) - the element is
  re-shaped so its own focal length is unchanged: both curvatures scaled for
  an element in air (its shape is kept), the air-side surface re-solved for
  a cemented one. Ray heights on the elements after it barely move.
* **Keep every curvature.**
* **Re-solve one surface for the system EFL** - restores the focal length,
  but every ray after that surface can move.

The table adds the Petzval change and the largest change of the paraxial
ray height on any surface (how far the rest of the lens is disturbed). Pick a
candidate and download the modified design: the original .zmx or .seq with
only the changed surfaces' curvature and glass lines rewritten, or JSON.

**CLI:**

```text
glassmatch lens docs/examples/triplet.json -T 60 --mount-cte 23.6
glassmatch replace docs/examples/triplet.json              # its obsolete glasses
glassmatch replace docs/examples/doublet.zmx N-SF5 --maker SCHOTT -T 60
glassmatch replace docs/examples/doublet.zmx N-SF5 --maker SCHOTT --use E-FD5 --use-maker HOYA -o new.zmx
glassmatch audit path/to/designs --csv obsolete.csv        # every obsolete glass in a folder
```

This is paraxial screening: it sees focal length, colour and thermal focus,
not spherical aberration, coma or astigmatism. Check any replacement in your
optical design program. Outside −30/+70 °C (the range the catalog CTEs are
measured over) no thermal shift is given unless you pass
`--allow-cte-extrapolation`.

## Exporting

CSV and JSON from the *Search & Compare* tab, a Zemax `.agf` of any selection
(`glassmatch export-agf SCHOTT-N-BK7 OHARA-S-BSL7 -o shortlist.agf`), or a
CODE V private catalog (`glassmatch export-codev N-BK7 E-FD5 -o private.seq`;
indices at the t, C, d, e, F, g, h lines, calculated inside each glass's
range). Every
export records the data version, so a design can cite exactly which numbers
it used. `glassmatch check` confirms the installed data matches its manifest.
