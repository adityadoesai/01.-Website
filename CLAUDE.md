# Working on this repo

Static site for adityadave.in. Essays live on Substack and are mirrored here as
static HTML by `build/build.py`.

## Ground rules

- **Never hand-edit anything under `site/` except `site/assets/`.** Every HTML
  file in `site/` is generated; `build/build.py` overwrites it on the next run.
  Assets (`css`, `js`, `img`, `_headers`, `_redirects`) are hand-maintained and
  are never touched by the build.
- **Standard library only.** No pip installs, no npm, no build toolchain. This is
  deliberate: the site must still build years from now with no dependency drift.
- **After changing anything, run `python3 build/build.py`** and commit the
  regenerated `site/` along with the source change. Cloudflare Pages serves the
  committed output directly and does not run a build.

## Where things live

| Concern | File |
|---|---|
| Site copy: tagline, hero, email, links | `build/config.json` |
| About page prose | `content/about.html` |
| Home page intro paragraph | `content/intro.html` |
| The hero illustration | `build/templates/hero.svg` |
| Page shell, `<head>`, nav, footer | `build/templates/base.html` |
| Home / essays-index / essay / 404 markup | the `build_*` functions in `build/build.py` |
| Substack HTML sanitising | `SubstackCleaner` in `build/build.py` |
| All visual design | `site/assets/css/main.css` |

## Design system

Editorial and reading-first. Paper `#FBF9F5`, ink `#1A1815`, accent deep rust
`#9A3B24`, with a warm dark-mode palette via `prefers-color-scheme`. Newsreader
(serif) for headlines, Inter for body at 19px / 1.75 / 68ch measure.

One trap worth knowing: prose flow spacing in `main.css` is expressed as
`.prose > * + *` style rules deliberately kept at (0,1,1) specificity, because an
earlier `.prose p { margin: 0 }` at (0,1,1) silently beat a (0,1,0) flow rule and
collapsed every paragraph gap. Do not reintroduce bare element margins there.

## The hero illustration

`build/templates/hero.svg` is hand-authored and inlined into the home page by
`build_home()`, rather than referenced as an `<img>`, so it can be styled from
the page. Two things to know before editing it:

- It carries **no `id` attributes**. Inlined SVG shares an id namespace with the
  page, so ids here can collide with page ids. Keep it that way.
- Its colours are deliberately literal rather than tokens: it is an illustration,
  not UI chrome. Dark mode dims it slightly instead of recolouring it.
- On narrow screens it is deliberately cropped rather than scaled, because the
  full scene shrinks to about 128px tall on a phone and the face disappears. That
  crop needs `max-width: none` to defeat the base `svg { max-width: 100% }` reset.

## Safety rails

`build/build.py` exits non-zero rather than publishing if the feed is
unreachable, or if it reports zero essays when essays were previously published.
`build/cache/essays.json` is the manifest of what was last published and **must
stay committed** — the rails and the prune step both depend on it. Override with
`FORCE_BUILD=1` only when a mass-unpublish is genuinely intended.
