# adityadave.in

A static, reading-first personal site. Essays are written on Substack and mirrored
onto this domain as real, indexable HTML pages.

```
content/about.html      ← the About page copy. Edit this to change what it says.
build/config.json       ← name, tagline, email, links, Substack feed URL.
build/build.py          ← fetches the Substack feed, generates the site.
build/templates/        ← the page shell (header, footer, meta tags).
site/                   ← THE GENERATED SITE. This is what Cloudflare serves.
                          Do not hand-edit; the next build overwrites it.
.github/workflows/      ← rebuilds every 6 hours so new essays appear on their own.
_archive/               ← the old WordPress-era site, kept as a backup.
```

## Publishing an essay

Write and publish it on Substack. That is the whole workflow.

Within six hours the scheduled job pulls the feed, generates
`site/essays/<slug>/index.html`, and Cloudflare deploys it. To make it appear
immediately, go to the repo's **Actions** tab → **Publish site** → **Run workflow**.

## Changing the words on the site

| To change | Edit |
|---|---|
| About page | `content/about.html` |
| Tagline, hero subtitle, email, links | `build/config.json` |
| "What I write about" blurbs | `build_home()` in `build/build.py` |
| Header, footer, meta tags | `build/templates/base.html` |
| Colours, type, spacing | `site/assets/css/main.css` |

Then run `python3 build/build.py`, commit, and push. Cloudflare deploys the push.

Note: `main.css` lives in `site/` but is written by hand, not generated — the
build never overwrites it.

## Working locally

```bash
python3 build/build.py          # regenerate the site
python3 build/serve.py          # preview at http://127.0.0.1:4321
```

No dependencies. Python 3's standard library only — nothing to install, no
`node_modules`, no build toolchain to rot.

## Safety rails

The build refuses to publish and exits non-zero if:

1. the Substack feed cannot be fetched, there is no cached copy, and essays are
   currently published; or
2. the feed parses fine but reports zero essays when the last run had some.

Both cases are far more likely to be a Substack outage than a real deletion, and
publishing would silently wipe the essays. `site/` is left untouched. If you
genuinely did unpublish everything, re-run with `FORCE_BUILD=1`.

## Deploying (one-time setup)

**1. Push to GitHub**

```bash
git remote add origin https://github.com/<your-username>/adityadave.in.git
git push -u origin main
```

**2. Connect Cloudflare Pages**

At `dash.cloudflare.com` → **Workers & Pages** → **Create** → **Pages** →
**Connect to Git**, pick the repo, then set:

| Setting | Value |
|---|---|
| Framework preset | None |
| Build command | *(leave empty)* |
| Build output directory | `site` |

Cloudflare serves the pre-built `site/` folder as-is — GitHub Actions does the
building, so there is no build step here to misconfigure or time out.

**3. Point the domain at it**

In the new Pages project → **Custom domains** → add `adityadave.in` and
`www.adityadave.in`. Cloudflare will walk you through adding the domain to its
DNS, which ends with changing the nameservers at Hostinger to the two Cloudflare
gives you.

That nameserver change is the only time you need to open Hostinger again. DNS
usually propagates within an hour, occasionally up to 24.

**4. Afterwards**

Once the site is confirmed live on Cloudflare, the Hostinger hosting plan is no
longer doing anything and can be cancelled at renewal. Keep the domain
registration wherever it is — only the nameservers matter.

## A note on the Substack subdomain

The feed currently points at `adityadave832741.substack.com` — an auto-generated
handle. You can change it under Substack **Settings → Basics → Subdomain** to
something like `adityadave`. If you do, update `substack_feed` and
`substack_url` in `build/config.json` to match, then rebuild. Essay URLs on this
site are unaffected.
