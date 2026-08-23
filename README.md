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

## How publishing works

```
   you write on Substack
            |
   GitHub Actions (every 6h, or on any push)
            |
      builds site/  ->  pushes the "deploy" branch
            |
   Hostinger pulls "deploy" into public_html
            |
      adityadave.in
```

Two branches, two different jobs:

- **`main`** holds everything: build scripts, templates, your About copy, and the
  generated `site/`. This is the history.
- **`deploy`** holds only the finished site, at the branch root, with `.htaccess`
  included. Its history is disposable and rewritten on every publish. Hostinger
  watches this branch and nothing else.

The split exists because Hostinger deploys a whole branch, not a subfolder, so
the site cannot simply live in `site/` on `main`.

## Deploying (one-time setup)

**1. Push to GitHub**

Public is simplest - it lets Hostinger clone without credentials, and GitHub
Actions minutes are unlimited on public repositories. Nothing secret lives here.

```bash
git remote add origin https://github.com/<your-username>/adityadave.in.git
git push -u origin main
```

Then run the workflow once (repo -> **Actions** -> **Publish site** -> **Run
workflow**) so the `deploy` branch exists before Hostinger looks for it.

**2. Connect Hostinger to the repo**

In hPanel, open your website, then **Advanced -> GIT**:

| Field | Value |
|---|---|
| Repository | `https://github.com/<your-username>/adityadave.in.git` |
| Branch | `deploy` |
| Directory | leave empty (means `public_html`) |

`public_html` must be empty before the first pull, or Hostinger will refuse.

**3. Turn on automatic deployment**

Hostinger shows a **webhook URL** next to the connected repository. Copy it,
then in GitHub go to **Settings -> Webhooks -> Add webhook**, paste it as the
Payload URL, set content type to `application/json`, and leave it on "just the
push event".

From then on: any push to `deploy` triggers Hostinger to pull it. Since the
scheduled build pushes `deploy` whenever a new essay appears, new writing
reaches the site on its own.

**4. Verify**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://adityadave.in/
curl -s -o /dev/null -w "%{http_code}\n" https://adityadave.in/hello-world/   # expect 301
```

The second one only returns 301 if `.htaccess` deployed correctly.

## Making a change to the site

Edit the source, then:

```bash
python3 build/build.py
git add -A && git commit -m "..." && git push
```

That is the whole loop. The push triggers the build, the build pushes `deploy`,
the webhook triggers Hostinger, and the site updates. No file manager, no zips,
no uploads.

## A note on the Substack subdomain

The feed currently points at `adityadave832741.substack.com` — an auto-generated
handle. You can change it under Substack **Settings → Basics → Subdomain** to
something like `adityadave`. If you do, update `substack_feed` and
`substack_url` in `build/config.json` to match, then rebuild. Essay URLs on this
site are unaffected.
