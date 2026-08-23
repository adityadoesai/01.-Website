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
| The hero illustration | `site/assets/img/hero.jpg` (master in `source/`) |
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

`site/assets/img/hero.jpg` is a centred 1024x820 crop of `source/hero-original.png`,
a 1024x1024 generated illustration. `source/README.md` has the two `sips` commands
to recut it.

It is deliberately held to a 40rem frame rather than the full container width:
the image is close to square, so at full width it fills the whole first screen
and pushes the introduction below the fold, which is the opposite of what a
hero should do.

An earlier hand-authored SVG version lives in the git history if it is ever
wanted back.

## Safety rails

`build/build.py` exits non-zero rather than publishing if the feed is
unreachable, or if it reports zero essays when essays were previously published.
`build/cache/essays.json` is the manifest of what was last published and **must
stay committed** — the rails and the prune step both depend on it. Override with
`FORCE_BUILD=1` only when a mass-unpublish is genuinely intended.
