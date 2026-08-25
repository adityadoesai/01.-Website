# adityadave.in — project brief

Context document for planning the next iteration. Written 25 August 2026.
Everything described here is built, deployed and verified live unless explicitly
marked otherwise.

---

## 1. What this is

A personal essay site for **Aditya Dave** — a doctor who moved into strategy and
investing (Boston Consulting Group, B Capital, Accenture Strategy) and now writes
about investing, healthcare and AI in India.

The site's single job is to be a good home for long-form essays, on his own
domain, that he does not have to maintain. He is not technical and does not want
to be. He explicitly does not want to touch hosting control panels.

**Live at:** https://adityadave.in

### What it replaced

A near-empty WordPress install on Hostinger: one post whose body was the
placeholder text `Content goes here`, one page, an About page sitting in the
trash, an undesigned default-theme homepage, and 21 known plugin
vulnerabilities. All of it is gone; the WordPress files were moved outside the
web root and the database is dormant.

---

## 2. Current state

### What exists

| Page | Path | Notes |
|---|---|---|
| Home | `/` | Illustrated hero, tagline, first-person intro, latest essays, subscribe, topics |
| Essays index | `/essays/` | Chronological list; currently an empty state |
| Individual essay | `/essays/<slug>/` | Generated per Substack post. **Zero exist right now** |
| About | `/about/` | Aditya's own bio copy, with portrait |
| 404 | `/404.html` | Custom |
| Feed | `/feed.xml` | The site's own RSS |
| Sitemap, robots | `/sitemap.xml`, `/robots.txt` | |

### The blocking content problem

**His Substack has zero published posts.** The site is a fully working vessel
with nothing in it. The essays index shows an empty state; the homepage shows a
"first essays are being written" message.

This is the single most important fact for planning. Any feature work that
assumes a corpus of essays (search, tags, related posts, archives, series) has
nothing to operate on yet.

### Verified working

- All pages, assets and feeds return 200
- Deployed files are byte-identical to the repository
- Old WordPress URLs 301-redirect to sensible destinations
- Custom 404, security headers, HTTP→HTTPS all active
- Email DNS untouched throughout the migration
- Light and dark themes both render correctly

---

## 3. Architecture

```
Aditya publishes on Substack
            │
            │  polled every 6 hours (also on any push, or manually)
            ▼
    GitHub Actions  ──  runs build/build.py
            │           fetches the Substack RSS feed,
            │           converts each post to a static page
            │
            ├──▶ commits regenerated site/ to `main`      (history)
            │
            └──▶ force-pushes packaged site to `deploy`   (deployment)
                          │
                          │  GitHub webhook
                          ▼
                 Hostinger pulls `deploy` into public_html
                          │
                          ▼
                    adityadave.in
```

### The two-branch split

Hostinger's Git integration deploys **a whole branch**, never a subfolder. The
repository mixes source (build scripts, templates, copy) with output (`site/`),
so the site cannot simply live at `site/` on `main`.

- **`main`** — source plus the generated `site/`. Real history. Never deployed.
- **`deploy`** — the finished site at the branch root, `.htaccess` included.
  Rebuilt from scratch and force-pushed on every publish; its history is
  disposable. This is the only branch Hostinger sees.

Rebuilding `deploy` fresh each time guarantees deleted files actually disappear
from the server rather than lingering.

### Hosting

| Layer | Where | Notes |
|---|---|---|
| Hosting | Hostinger shared, LiteSpeed/Apache, PHP 8.2 | **Prepaid through 2029** — sunk cost, deliberately kept |
| Repository | GitHub `adityadoesai/01.-Website` | **Private** |
| CI | GitHub Actions | ~85 of 2,000 free monthly minutes used |
| Newsletter | Substack `adityadave832741.substack.com` | Free tier |
| DNS | Hostinger nameservers (`ns1/ns2.dns-parking.com`) | |
| Domain registrar | **Not Hostinger** — actual registrar unidentified | |
| TLS | Let's Encrypt via Hostinger | Valid to 4 Oct 2026 |

A Cloudflare Pages migration was designed and then abandoned mid-setup: Aditya
preferred to use hosting he had already paid for, and the nameserver change
carried avoidable risk to his email. The Cloudflare-specific files (`_headers`,
`_redirects`) still exist in `site/` and are stripped during packaging, so that
path remains open at no cost.

---

## 4. Repository layout

```
01. Website/
├── build/
│   ├── build.py              790 lines. The generator. Python 3 stdlib only.
│   ├── package-hostinger.py   93 lines. Wraps site/ for Apache: drops the
│   │                              Cloudflare files, injects .htaccess.
│   ├── serve.py               28 lines. Local preview on :4321.
│   ├── config.json            Site title, tagline, email, links, feed URL.
│   ├── htaccess.conf          Apache config. Single source of truth.
│   ├── templates/base.html    The page shell: head, nav, footer.
│   └── cache/
│       ├── feed.xml           Last good feed (gitignored). Outage insurance.
│       └── essays.json        Manifest of published slugs. MUST stay committed —
│                              the safety rails and prune step depend on it.
├── content/
│   ├── about.html             About page prose. Aditya's own words.
│   └── intro.html             Home page introduction paragraph.
├── source/
│   ├── hero-original.png      1024×1024 master of the hero illustration.
│   └── README.md              Commands to recut the crop.
├── site/                      GENERATED. Do not hand-edit, except assets/.
│   └── assets/                Hand-maintained: css, js, images, _headers,
│                              _redirects. The build never touches these.
├── .github/workflows/publish.yml
├── CLAUDE.md                  Working rules for AI agents on this repo.
├── README.md                  Human setup and deployment guide.
├── DNS-BACKUP.md              Pre-migration DNS records, for disaster recovery.
└── PROJECT-BRIEF.md           This file.
```

**Dependency policy: Python 3 standard library only.** No pip, no npm, no
`node_modules`, no build toolchain. This is deliberate — the site must still
build years from now without dependency drift. Any proposed feature that needs a
package should be weighed against this.

---

## 5. The build system

`build/build.py` — one file, no dependencies. Key components:

| Function | Role |
|---|---|
| `fetch_feed()` | Pulls the Substack RSS, caches the last good copy |
| `SubstackCleaner` | `HTMLParser` subclass. Allowlist-based sanitiser |
| `parse_feed()` | RSS → post objects (title, slug, body, excerpt, date, reading time) |
| `build_home/essays_index/about/essay/404()` | Page generators |
| `build_rss/sitemap()` | Feed and crawl files |
| `prune_removed_essays()` | Deletes only pages it previously generated |

### Substack HTML sanitising

Substack's `content:encoded` arrives full of platform chrome. `SubstackCleaner`
rewrites it against a tag allowlist, drops subtrees whose class names match known
widgets (subscription forms, share buttons, paywall markers), unwraps layout
divs, strips every `class`/`style`/`id`, and adds `loading="lazy"` plus a
fallback `alt=""` to images. Verified against a real 6-essay feed: output
contains zero Substack markup.

### Safety rails

The build **refuses to publish and exits non-zero** if either:

1. the feed cannot be fetched, there is no cache, and essays are currently
   published; or
2. the feed parses cleanly but reports zero essays when the last run had some.

Both are far more likely to be a Substack outage than a real deletion, and
publishing would silently wipe the site's essays. `FORCE_BUILD=1` overrides.
Both rails are tested.

### Other hardening worth knowing

- **RSS `lastBuildDate` derives from the newest post, not the clock.** A
  wall-clock timestamp made `feed.xml` differ on every run, defeating the "only
  commit when something changed" check — the job would have redeployed an
  unchanged site four times a day forever.
- **A monthly heartbeat commit** keeps the schedule alive: GitHub disables
  scheduled workflows after 60 days of repository inactivity, which would
  silently kill the mirror during any long gap between essays.
- **The publish push rebases and retries** if `main` moved underneath the job.

---

## 6. Design system

Editorial and reading-first. The brief was a writer's site, not a startup landing
page.

```
--paper     #FBF9F5   warm off-white ground
--ink       #1A1815   near-black text
--ink-soft  #4A453D   secondary text
--ink-mute  #7A7368   metadata, eyebrows
--rule      #E2DCD1   hairlines
--accent    #9A3B24   deep rust — links, underlines, small marks
```

- **Type:** Inter only, weights 400/500/600/700. No serif anywhere.
- **Body:** 1.25rem / 1.7 line-height across a **42rem measure**
- **Code:** system monospace stack, no webfont
- Full warm dark-mode palette via `prefers-color-scheme`, with `[data-theme]`
  overrides so a toggle could win in either direction
- Mobile nav, reading-progress bar on essays, skip link, visible focus states,
  `prefers-reduced-motion` respected
- Every colour and every type size is a token; no literal values outside `:root`
- Surfaces separated by hairline borders, never by lighter fills
- No framework, no build toolchain

### The hero

A generated cartoon illustration of Aditya at a cluttered desk — laptop,
pitch decks, coffee, whiteboard of sticky notes, a rising chart, a spreadsheet on
the monitor. Layout cue taken from gkoberger.com: wide illustrated scene, then a
short first-person introduction centred beneath it.

Held to a 40rem frame rather than full container width — the image is close to
square, and at full width it filled the entire first screen and pushed the
introduction below the fold.

---

## 7. Content model

**Aditya writes on Substack. That is the entire publishing workflow.**

Within six hours the scheduled job pulls the feed, generates
`site/essays/<slug>/index.html`, and the site updates itself. Slugs come from the
Substack post URL, so they survive a Substack subdomain change.

Canonical URLs currently point at **his own domain**, not Substack
(`canonical_to_substack: false` in config, and it is a one-line flip if the SEO
tradeoff should go the other way).

Substack also handles the email list and the subscribe form (embedded via
iframe). There is no separate mailing infrastructure and no backend of any kind —
the site is entirely static.

---

## 8. Open items and known gaps

These are the natural inputs to a next-iteration PRD.

### Content
- **No essays exist.** Everything downstream is theoretical until he publishes.
- Substack subdomain is the machine-generated `adityadave832741` — changing it
  is a settings toggle plus a two-line config update.

### Correctness
- **The LinkedIn URL is unverified** — carried over from the old site and never
  confirmed. If wrong, every social link on the site is dead.
- **`hello@adityadave.in` may not exist as a mailbox.** DNS is configured for
  Hostinger mail, but the hPanel still offers "set up free email", suggesting no
  mailbox was created. The site links to this address in several places.
- The hero illustration contains AI-generated gibberish text on the desk papers
  and book spines, legible on close inspection.

### Infrastructure
- **`.well-known/` was removed from `public_html`** during the WordPress
  cleanup. It is how Let's Encrypt validates domain ownership at renewal.
  Current certificate expires **4 October 2026**. Hostinger usually recreates
  the folder automatically, but this is unverified and time-bound.
- **No DMARC or DKIM records.** Nothing prevents spoofing of his domain in email.
  Pre-existing, not caused by the migration.
- The domain registrar is unidentified — relevant only if DNS ever moves.

### Deliberately absent
Worth knowing so a PRD does not treat these as oversights:

- No search, tags, categories, or related-posts — nothing to index yet
- No comments — Substack owns that conversation
- No analytics of any kind
- No CMS or admin UI — Substack is the editor
- No JavaScript framework, no build toolchain, no runtime
- No image pipeline — images are hand-optimised with macOS `sips`

---

## 9. Constraints to design within

1. **Aditya is not technical and does not want to be.** Anything requiring him to
   operate a control panel regularly will not survive.
2. **The only manual step in the loop is a single "Push" click** in GitHub
   Desktop, and that is deliberate — it is the consent gate before anything
   reaches the live site.
3. **No new recurring costs.** Everything sits inside free tiers; Hostinger is
   prepaid to 2029.
4. **Standard library only.** No dependency chain to rot.
5. **`site/` is generated.** Only `site/assets/` is hand-maintained.
6. **Writing happens on Substack.** Any proposal that moves authoring elsewhere
   is a much bigger change than it first appears — it would take the email list,
   the subscriber relationship and the editor with it.
