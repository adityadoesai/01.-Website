#!/usr/bin/env python3
"""
Build adityadave.in.

Pulls the Substack RSS feed, converts each post into a clean static page on the
site's own domain, and regenerates the home page, essay index, about page,
RSS feed and sitemap.

Standard library only - no pip install, no node_modules. Run with:

    python3 build/build.py

The last good feed is cached in build/cache/, so a network failure or a
Substack outage degrades to "site stays exactly as it was" rather than
"site loses all its essays".
"""

import html
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, format_datetime
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
SITE = os.path.join(ROOT, "site")
CACHE = os.path.join(BUILD, "cache")
TEMPLATES = os.path.join(BUILD, "templates")
CONTENT = os.path.join(ROOT, "content")

CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
DC_NS = "{http://purl.org/dc/elements/1.1/}creator"


# --------------------------------------------------------------------------
# Substack HTML cleaning
# --------------------------------------------------------------------------

# Tags we keep as-is.
KEEP = {
    "p", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "a",
    "strong", "em", "b", "i", "br", "hr", "img", "figure", "figcaption",
    "code", "pre", "table", "thead", "tbody", "tr", "th", "td", "sup", "sub",
    "del", "small",
}

# Tags whose own markup we drop but whose children we keep.
UNWRAP = {"div", "span", "section", "article", "header", "footer", "main", "font"}

# Tags dropped along with everything inside them.
DROP_SUBTREE = {"script", "style", "iframe", "form", "button", "svg", "noscript"}

# Substack chrome: if a class name contains any of these, drop the subtree.
DROP_CLASSES = (
    "subscription-widget", "subscribe-widget", "button-wrapper", "share-dialog",
    "poll-embed", "paywall", "digest-post-embed", "footer-substack",
    "comments-page-link", "post-ufi", "audio-player", "gift-", "pencraft-cta",
)

ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}

VOID = {"br", "hr", "img"}


class SubstackCleaner(HTMLParser):
    """Rewrite Substack's post HTML into clean, semantic, class-free markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip_depth = 0
        self.skip_tag = None
        self.stack = []

    # -- helpers --
    def _classes(self, attrs):
        for k, v in attrs:
            if k == "class" and v:
                return v.lower()
        return ""

    def _should_drop(self, tag, attrs):
        if tag in DROP_SUBTREE:
            return True
        cls = self._classes(attrs)
        return any(marker in cls for marker in DROP_CLASSES)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if self.skip_depth:
            if tag == self.skip_tag and tag not in VOID:
                self.skip_depth += 1
            return

        if self._should_drop(tag, attrs):
            if tag not in VOID:
                self.skip_depth = 1
                self.skip_tag = tag
            return

        # Substack wraps post images in a link to the full-size asset.
        if tag == "a" and "image-link" in self._classes(attrs):
            self.stack.append(("a", False))
            return

        if tag == "h1":
            tag = "h2"

        if tag in UNWRAP:
            self.stack.append((tag, False))
            return

        if tag not in KEEP:
            self.stack.append((tag, False))
            return

        allowed = ATTRS.get(tag, set())
        rendered = []
        for k, v in attrs:
            k = k.lower()
            if k in allowed and v:
                rendered.append('%s="%s"' % (k, html.escape(v, quote=True)))

        if tag == "img":
            # Substack frequently omits alt text. An explicit empty alt marks the
            # image as decorative, which screen readers handle correctly; a
            # missing alt leaves them reading out the filename instead.
            if not any(r.startswith("alt=") for r in rendered):
                rendered.append('alt=""')
            rendered.append('loading="lazy"')
            rendered.append('decoding="async"')

        if tag == "a":
            has_href = any(r.startswith("href=") for r in rendered)
            if not has_href:
                self.stack.append((tag, False))
                return
            rendered.append('rel="noopener"')

        attr_str = (" " + " ".join(rendered)) if rendered else ""
        self.out.append("<%s%s>" % (tag, attr_str))

        if tag not in VOID:
            self.stack.append((tag, True))

    def handle_endtag(self, tag):
        tag = tag.lower()

        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return

        if tag in VOID:
            return

        if self.stack:
            open_tag, emitted = self.stack.pop()
            if emitted:
                self.out.append("</%s>" % ("h2" if open_tag == "h1" else open_tag))

    def handle_data(self, data):
        if self.skip_depth:
            return
        self.out.append(html.escape(data, quote=False))

    def result(self):
        # Close anything the source left dangling.
        while self.stack:
            open_tag, emitted = self.stack.pop()
            if emitted:
                self.out.append("</%s>" % open_tag)
        return "".join(self.out)


def clean_html(raw):
    cleaner = SubstackCleaner()
    cleaner.feed(raw or "")
    out = cleaner.result()

    # Collapse the empty shells left behind by unwrapping Substack's divs.
    out = re.sub(r"<p>\s*</p>", "", out)
    out = re.sub(r"<(h[2-6])>\s*</\1>", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def strip_tags(markup):
    text = re.sub(r"<[^>]+>", " ", markup or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


# --------------------------------------------------------------------------
# Feed
# --------------------------------------------------------------------------

def fetch_feed(url):
    """Return feed XML, preferring the network and falling back to cache."""
    os.makedirs(CACHE, exist_ok=True)
    cached = os.path.join(CACHE, "feed.xml")

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "adityadave.in site builder"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        ET.fromstring(data)  # reject malformed responses before caching them
        with open(cached, "wb") as fh:
            fh.write(data)
        print("  fetched feed: %d bytes" % len(data))
        return data
    except (urllib.error.URLError, ET.ParseError, OSError, ValueError) as exc:
        print("  ! feed fetch failed (%s)" % exc)
        if os.path.exists(cached):
            print("  using cached feed")
            with open(cached, "rb") as fh:
                return fh.read()
        print("  no cache available - building with zero essays")
        return None


def slug_from_link(link, fallback):
    path = re.sub(r"[?#].*$", "", link or "").rstrip("/")
    tail = path.rsplit("/", 1)[-1] if path else ""
    tail = re.sub(r"[^a-z0-9-]+", "-", tail.lower()).strip("-")
    return tail or fallback


def parse_feed(data, cfg):
    if not data:
        return []

    root = ET.fromstring(data)
    channel = root.find("channel")
    if channel is None:
        return []

    posts = []
    for index, item in enumerate(channel.findall("item")):
        title = (item.findtext("title") or "Untitled").strip()
        link = (item.findtext("link") or "").strip()

        node = item.find(CONTENT_NS)
        raw = node.text if node is not None and node.text else (item.findtext("description") or "")
        body = clean_html(raw)
        text = strip_tags(body)

        words = len(text.split())
        minutes = max(1, round(words / cfg["words_per_minute"])) if words else 1

        pub = item.findtext("pubDate")
        try:
            date = parsedate_to_datetime(pub) if pub else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            date = datetime.now(timezone.utc)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        excerpt = (item.findtext("description") or "").strip()
        excerpt = strip_tags(excerpt) or text
        if len(excerpt) > 190:
            excerpt = excerpt[:190].rsplit(" ", 1)[0].rstrip(",.;:") + "…"

        posts.append({
            "title": title,
            "slug": slug_from_link(link, "essay-%d" % (index + 1)),
            "source": link,
            "body": body,
            "excerpt": excerpt,
            "words": words,
            "minutes": minutes,
            "date": date,
        })

    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


# --------------------------------------------------------------------------
# Durable archive
#
# Substack's feed is windowed: it returns only the most recent posts. Rendering
# straight from the feed therefore means the oldest essay silently drops off the
# site the moment it falls out of that window, and prune_removed_essays() would
# delete its page. For a site whose whole purpose is a durable archive, that is a
# slow, invisible data loss.
#
# So every successful fetch writes each post to content/essays/, committed to the
# repository, and the build renders the union of feed and archive. The feed wins
# on conflict - that is how edits made on Substack propagate - and the archive is
# updated to match.
#
# It also removes a single point of failure: a build can no longer be stopped by
# Substack being unreachable, because everything needed to render the site is
# already in the repository.
# --------------------------------------------------------------------------

ARCHIVE = os.path.join(CONTENT, "essays")

ARCHIVE_FIELDS = ("title", "subtitle", "slug", "source", "excerpt",
                  "words", "minutes", "cover", "tags")


def archive_post(post):
    """Write one essay to content/essays/ as body HTML plus a metadata sidecar."""
    os.makedirs(ARCHIVE, exist_ok=True)
    with open(os.path.join(ARCHIVE, post["slug"] + ".html"), "w", encoding="utf-8") as fh:
        fh.write(post["body"])
    meta = {k: post.get(k) for k in ARCHIVE_FIELDS}
    meta["date"] = post["date"].isoformat()
    with open(os.path.join(ARCHIVE, post["slug"] + ".json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def save_archive(posts):
    for post in posts:
        archive_post(post)


def load_archive():
    """Read every archived essay back into the same shape parse_feed produces."""
    if not os.path.isdir(ARCHIVE):
        return []
    out = []
    for name in sorted(os.listdir(ARCHIVE)):
        if not name.endswith(".json"):
            continue
        slug = name[:-5]
        body_path = os.path.join(ARCHIVE, slug + ".html")
        if not os.path.exists(body_path):
            print("  ! archive entry %s has no body; skipping" % slug)
            continue
        try:
            with open(os.path.join(ARCHIVE, name), encoding="utf-8") as fh:
                meta = json.load(fh)
            with open(body_path, encoding="utf-8") as fh:
                body = fh.read()
            meta["date"] = datetime.fromisoformat(meta["date"])
            meta["body"] = body
            meta.setdefault("slug", slug)
            out.append(meta)
        except (ValueError, OSError) as exc:
            print("  ! could not read archive entry %s (%s)" % (slug, exc))
    return out


def merge_posts(feed_posts, archived):
    """Union of feed and archive, newest first. Feed content wins on conflict."""
    by_slug = {p["slug"]: p for p in archived}
    by_slug.update({p["slug"]: p for p in feed_posts})
    merged = list(by_slug.values())
    merged.sort(key=lambda p: p["date"], reverse=True)
    return merged


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render(template, mapping):
    out = template
    for key, value in mapping.items():
        out = out.replace("{{%s}}" % key, str(value))
    return re.sub(r"\{\{[A-Z_]+\}\}", "", out)


def e(text):
    return html.escape(str(text), quote=True)


def social_links(cfg, root):
    """Footer social links. A blank config value renders nothing at all, so an
    unverified URL can never ship as a dead link (R-53)."""
    out = []
    if cfg.get("linkedin"):
        out.append('        <a href="%s" rel="noopener">LinkedIn</a>' % e(cfg["linkedin"]))
    return "\n".join(out)


def page(shell, cfg, *, content, title, desc, url, depth=0,
         og_type="website", og_title=None, canonical=None,
         nav="", head_extra="", progress=False, og_image=None):
    root = "../" * depth if depth else ""
    og_tag = ""
    if og_image:
        og_tag = ('<meta property="og:image" content="%s">\n'
                  '<meta name="twitter:image" content="%s">' % (e(og_image), e(og_image)))
    return render(shell, {
        "PAGE_TITLE": e(title),
        "PAGE_DESC": e(desc),
        "CANONICAL": e(canonical or url),
        "PAGE_URL": e(url),
        "OG_TYPE": og_type,
        "OG_TITLE": e(og_title or title),
        "SITE_TITLE": e(cfg["site_title"]),
        "AUTHOR": e(cfg["author"]),
        "TAGLINE": e(cfg["tagline"]),
        "BASE_URL": cfg["base_url"],
        "SUBSTACK_URL": cfg["substack_url"],
        "ROOT": root,
        "OG_IMAGE": og_tag,
        "THEME_LIGHT": cfg["theme_color_light"],
        "THEME_DARK": cfg["theme_color_dark"],
        "FOOTER_SOCIAL": social_links(cfg, root),
        "CONTENT": content,
        "HEAD_EXTRA": head_extra,
        "PROGRESS": '<div class="progress" aria-hidden="true"></div>' if progress else "",
        "NAV_ESSAYS": ' aria-current="page"' if nav == "essays" else "",
        "NAV_ABOUT": ' aria-current="page"' if nav == "about" else "",
    })


def chips(post):
    tags = post.get("tags") or []
    if not tags:
        return ""
    items = "".join('<li class="chip">%s</li>' % e(t) for t in tags)
    return '\n          <ul class="chips">%s</ul>' % items


def card_media(post, root):
    """Cover thumbnail, or a flat titled block when the essay has none, so the
    grid never collapses and no broken image can appear (R-22)."""
    cover = post.get("cover")
    if cover:
        return ('<div class="card__media"><img src="%scoverpath" alt="" loading="lazy" '
                'decoding="async"></div>').replace("%scoverpath", e(root + cover))
    return ('<div class="card__media card__media--fallback"><span>%s</span></div>'
            % e(post["title"]))


def essay_card(post, depth=0):
    root = "../" * depth if depth else ""
    return """      <li>
        <a class="card" href="{root}essays/{slug}/">
          {media}
          <div class="card__body">
            <p class="card__meta"><time datetime="{iso}">{stamp}</time> &middot; {mins} min read</p>
            <h3 class="card__title">{title}</h3>
            <p class="card__excerpt">{excerpt}</p>{chips}
          </div>
        </a>
      </li>""".format(
        root=root,
        slug=post["slug"],
        media=card_media(post, root),
        iso=post["date"].strftime("%Y-%m-%d"),
        stamp=post["date"].strftime("%d %b %Y").lstrip("0"),
        mins=post["minutes"],
        title=e(post["title"]),
        excerpt=e(post["excerpt"]),
        chips=chips(post),
    )


def subscribe_block(cfg, heading, body):
    """A styled link, not Substack's embed. The embed is an iframe on a pale
    ground that cannot be restyled cross-origin, which is exactly the kind of
    stray pale panel this design is trying to eliminate (D-1)."""
    return """  <section class="subscribe">
    <div class="shell">
      <h2 class="subscribe__title">{heading}</h2>
      <p class="subscribe__body">{body}</p>
      <a class="btn btn--primary" href="{sub}" rel="noopener">Subscribe on Substack</a>
      <p class="subscribe__note">Free. Essays arrive by email as they are published.</p>
    </div>
  </section>""".format(heading=e(heading), body=e(body), sub=cfg["substack_url"])


def person_schema(cfg):
    same_as = [u for u in (cfg.get("linkedin"), cfg.get("substack_url")) if u]
    data = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": cfg["author"],
        "url": cfg["base_url"],
        "description": cfg["description"],
    }
    if same_as:
        data["sameAs"] = same_as
    return data


def build_home(shell, cfg, posts):
    """Name, one descriptor line, the illustration, then the essays. The
    first-person introduction that used to sit here is the About page's job;
    content/intro.html is left in the repo, unreferenced (R-19)."""
    if posts:
        listing = """  <section class="section">
    <div class="shell">
      <div class="section__head">
        <p class="eyebrow">Latest essays</p>
        <a class="arrowlink" href="essays/">All essays <span>&rarr;</span></a>
      </div>
      <ul class="cards">
{items}
      </ul>
    </div>
  </section>""".format(items="\n".join(essay_card(post) for post in posts[:6]))
    else:
        listing = """  <section class="section">
    <div class="shell">
      <p class="empty">The first essays are being written.</p>
    </div>
  </section>"""

    head = """  <section class="home-head">
    <div class="shell">
      <h1 class="home-head__name">{name}</h1>
      <p class="home-head__line">{line}</p>
    </div>
  </section>

  <div class="shell">
    <div class="hero-frame">
      <img class="hero-art" src="assets/images/hero.png" alt="{alt}"
           fetchpriority="high" decoding="async">
    </div>
  </div>""".format(
        name=e(cfg["site_title"]),
        line=e(cfg["tagline"]),
        alt="Cartoon illustration of Aditya at his desk, laptop open, "
            "a whiteboard of sticky notes and a rising chart behind him.",
    )

    schema = """<script type="application/ld+json">%s</script>""" % json.dumps(
        person_schema(cfg), separators=(",", ":"))

    return page(
        shell, cfg,
        content=head + "\n" + listing + "\n" + subscribe_block(
            cfg, "Stay curious",
            "New essays on investing, healthcare and strategy in India."),
        title=cfg["home_title"],
        desc=cfg["description"],
        url=cfg["base_url"] + "/",
        head_extra=schema,
        og_image=cfg["base_url"] + "/assets/images/hero.png",
    )


def build_essays_index(shell, cfg, posts):
    if posts:
        body = """      <ul class="cards">
{items}
      </ul>""".format(items="\n".join(essay_card(post, depth=1) for post in posts))
        count = "%d essay%s" % (len(posts), "" if len(posts) == 1 else "s")
    else:
        body = """      <p class="empty">Nothing published yet.</p>"""
        count = "Coming soon"

    content = """  <section class="section">
    <div class="shell">
      <div class="section__head">
        <h1 class="page-title">Essays</h1>
        <p class="eyebrow">{count}</p>
      </div>
{body}
    </div>
  </section>
{sub}""".format(count=e(count), body=body,
                sub=subscribe_block(cfg, "Get the next one",
                                    "Essays arrive by email as they are published."))

    return page(
        shell, cfg,
        content=content,
        title="Essays — %s" % cfg["site_title"],
        desc="Long-form essays on investing, healthcare, AI and strategy in India.",
        url=cfg["base_url"] + "/essays/",
        depth=1, nav="essays",
    )


def build_about(shell, cfg):
    with open(os.path.join(CONTENT, "about.html"), encoding="utf-8") as fh:
        about_body = fh.read().strip()

    rows = []
    if cfg.get("linkedin"):
        rows.append('        <li><b>LinkedIn</b><span><a class="textlink" href="%s"'
                    ' rel="noopener">Connect with me</a></span></li>' % e(cfg["linkedin"]))
    rows.append('        <li><b>Newsletter</b><span><a class="textlink" href="%s"'
                ' rel="noopener">Subscribe on Substack</a></span></li>' % cfg["substack_url"])

    content = """  <section class="about">
    <div class="shell">
      <h1 class="page-title about__title">About</h1>
      <div class="about__layout">
        <div class="prose measure">
{body}
        </div>
        <figure style="margin:0">
          <img class="about__portrait" src="../assets/images/portrait.jpg"
               width="900" height="900" alt="Portrait of Aditya Dave" loading="lazy" decoding="async">
          <figcaption class="about__portrait-cap">Aditya Dave</figcaption>
        </figure>
      </div>
      <ul class="contact">
{rows}
      </ul>
    </div>
  </section>""".format(body=about_body, rows="\n".join(rows))

    schema = """<script type="application/ld+json">%s</script>""" % json.dumps(
        person_schema(cfg), separators=(",", ":"))

    return page(
        shell, cfg,
        content=content,
        title="About — %s" % cfg["site_title"],
        desc="Aditya Dave: doctor turned strategist and investor, writing on investing, healthcare and AI in India.",
        url=cfg["base_url"] + "/about/",
        depth=1, nav="about", og_type="profile", head_extra=schema,
    )


def build_essay(shell, cfg, post, prev_post=None, next_post=None):
    url = "%s/essays/%s/" % (cfg["base_url"], post["slug"])
    canonical = post["source"] if cfg.get("canonical_to_substack") and post["source"] else url

    cover_abs = None
    cover_block = ""
    if post.get("cover"):
        cover_abs = cfg["base_url"] + "/" + post["cover"].lstrip("/")
        cover_block = (
            '\n      <figure class="article__cover">'
            '\n        <img src="../../%s" alt="" decoding="async">'
            '\n      </figure>' % e(post["cover"])
        )

    schema_data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post["title"],
        "description": post["excerpt"],
        "datePublished": post["date"].isoformat(),
        "wordCount": post["words"],
        "author": {"@type": "Person", "name": cfg["author"], "url": cfg["base_url"]},
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
    }
    if cover_abs:
        schema_data["image"] = cover_abs
    schema = '<script type="application/ld+json">%s</script>' % json.dumps(
        schema_data, separators=(",", ":"))

    dek = ""
    if post.get("subtitle"):
        dek = '\n      <p class="article__dek">%s</p>' % e(post["subtitle"])

    adjacent = []
    if prev_post:
        adjacent.append(
            '        <a class="adjacent--prev" href="../%s/">\n'
            '          <p class="eyebrow">Previous</p><strong>%s</strong>\n'
            '        </a>' % (prev_post["slug"], e(prev_post["title"])))
    if next_post:
        adjacent.append(
            '        <a class="adjacent--next" href="../%s/">\n'
            '          <p class="eyebrow">Next</p><strong>%s</strong>\n'
            '        </a>' % (next_post["slug"], e(next_post["title"])))
    adjacent_block = ""
    if adjacent:
        adjacent_block = ('      <nav class="adjacent" aria-label="More essays">\n%s\n      </nav>\n'
                          % "\n".join(adjacent))

    source_line = ""
    if post["source"]:
        source_line = ('      <p class="postscript__source">Originally published on '
                       '<a href="%s" rel="noopener">Substack</a>.</p>' % e(post["source"]))

    content = (
        '  <article class="article">\n'
        '    <div class="shell">\n'
        '      <a class="article__back" href="../"><span>&larr;</span> All essays</a>\n'
        '      <p class="article__meta"><time datetime="{iso}">{stamp}</time> &middot; {mins} min read</p>\n'
        '      <h1 class="article__title">{title}</h1>{dek}{cover}\n'
        '      <hr class="rule article__divider">\n'
        '      <div class="prose">\n'
        '{body}\n'
        '      </div>\n'
        '      <div class="postscript">\n'
        '{adjacent}{source}\n'
        '      </div>\n'
        '    </div>\n'
        '  </article>\n'
        '{sub}'
    ).format(
        iso=post["date"].strftime("%Y-%m-%d"),
        stamp=post["date"].strftime("%d %B %Y").lstrip("0"),
        mins=post["minutes"],
        title=e(post["title"]),
        dek=dek,
        cover=cover_block,
        body=post["body"],
        adjacent=adjacent_block,
        source=source_line,
        sub=subscribe_block(cfg, "Enjoyed this?",
                            "Subscribe and the next essay arrives in your inbox."),
    )

    return page(
        shell, cfg,
        content=content,
        title="%s — %s" % (post["title"], cfg["site_title"]),
        desc=post["excerpt"],
        url=url, canonical=canonical,
        depth=2, nav="essays", og_type="article", progress=True,
        head_extra=schema, og_image=cover_abs,
    )


def build_404(shell, cfg):
    content = """  <section class="notfound">
    <div class="shell">
      <p class="eyebrow">Error 404</p>
      <h1>This page went looking for a better idea.</h1>
      <p>The link may be old, or the essay may have moved. The essays index below
      has everything that currently exists.</p>
      <div class="actions">
        <a class="btn btn--primary" href="/essays/">Read the essays</a>
        <a class="arrowlink" href="/">Back home <span>&rarr;</span></a>
      </div>
    </div>
  </section>"""
    return page(
        shell, cfg, content=content,
        title="Not found — %s" % cfg["site_title"],
        desc="This page could not be found.",
        url=cfg["base_url"] + "/404.html",
    )


# --------------------------------------------------------------------------
# Feeds and crawl files
# --------------------------------------------------------------------------

def build_rss(cfg, posts):
    # Derive lastBuildDate from the newest post, never from the clock. A
    # wall-clock timestamp changes on every build, so the feed would differ every
    # run even with nothing new - which defeats the "only commit when something
    # changed" check and would redeploy the site every six hours forever.
    last_build = format_datetime(posts[0]["date"]) if posts else ""
    items = []
    for post in posts[:20]:
        items.append("""  <item>
    <title>{title}</title>
    <link>{url}</link>
    <guid isPermaLink="true">{url}</guid>
    <pubDate>{date}</pubDate>
    <description>{excerpt}</description>
  </item>""".format(
            title=e(post["title"]),
            url="%s/essays/%s/" % (cfg["base_url"], post["slug"]),
            date=format_datetime(post["date"]),
            excerpt=e(post["excerpt"]),
        ))

    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{title}</title>
  <link>{base}/</link>
  <description>{desc}</description>
  <language>en</language>
{last_build}  <atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml"/>
{items}
</channel>
</rss>
""".format(title=e(cfg["site_title"]), base=cfg["base_url"],
           desc=e(cfg["description"]),
           last_build=("  <lastBuildDate>%s</lastBuildDate>\n" % last_build) if last_build else "",
           items="\n".join(items))


def build_sitemap(cfg, posts):
    urls = [(cfg["base_url"] + "/", "1.0"),
            (cfg["base_url"] + "/essays/", "0.9"),
            (cfg["base_url"] + "/about/", "0.8")]
    urls += [("%s/essays/%s/" % (cfg["base_url"], p["slug"]), "0.7") for p in posts]

    body = "\n".join(
        "  <url><loc>%s</loc><priority>%s</priority></url>" % (u, pr)
        for u, pr in urls
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            '%s\n</urlset>\n' % body)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def prune_removed_essays(current_slugs):
    """Delete only essay folders this script generated on a previous run."""
    manifest_path = os.path.join(CACHE, "essays.json")
    previous = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                previous = json.load(fh)
        except (ValueError, OSError):
            previous = []

    archived_slugs = {n[:-5] for n in os.listdir(ARCHIVE)
                      if n.endswith(".json")} if os.path.isdir(ARCHIVE) else set()
    for slug in previous:
        # Absence from the feed alone is not grounds for deletion: the feed is
        # windowed, so an older essay leaves it while remaining perfectly valid.
        if slug in current_slugs or slug in archived_slugs:
            continue
        stale = os.path.join(SITE, "essays", slug)
        if os.path.isdir(stale):
            shutil.rmtree(stale)
            print("  removed unpublished essay: %s" % slug)

    os.makedirs(CACHE, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(sorted(current_slugs), fh, indent=2)


def previously_published():
    """Slugs written by the last successful run, per the manifest."""
    manifest_path = os.path.join(CACHE, "essays.json")
    if not os.path.exists(manifest_path):
        return []
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return []


def main():
    with open(os.path.join(BUILD, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    with open(os.path.join(TEMPLATES, "base.html"), encoding="utf-8") as fh:
        shell = fh.read()

    force = os.environ.get("FORCE_BUILD") == "1"
    known = previously_published()

    print("Building %s" % cfg["base_url"])

    archived = load_archive()
    print("  archived essays: %d" % len(archived))

    data = fetch_feed(cfg["substack_feed"])
    feed_posts = parse_feed(data, cfg) if data else []
    if data:
        print("  feed essays: %d" % len(feed_posts))
        save_archive(feed_posts)
        archived = load_archive()
    else:
        print("  feed unavailable; rendering from the archive alone")

    posts = merge_posts(feed_posts, archived)
    print("  rendering: %d essay(s)" % len(posts))

    # Safety rail. With the archive in place a failed fetch is no longer fatal -
    # everything needed to render is already in the repository - so the only
    # case worth refusing is one where the site would lose essays it previously
    # published and cannot recover them from anywhere.
    if known and not posts and not force:
        print("\nREFUSING TO BUILD: %d essay(s) were published on the last run, but\n"
              "neither the Substack feed nor content/essays/ can supply any now.\n"
              "Publishing this would delete them, so site/ is untouched.\n"
              "Override with FORCE_BUILD=1 if you genuinely unpublished everything."
              % len(known))
        return 1

    missing = [slug for slug in known if slug not in {p["slug"] for p in posts}]
    if missing and not force:
        print("\nREFUSING TO BUILD: %d previously published essay(s) are missing from\n"
              "both the feed and the archive: %s\n"
              "site/ is untouched. Override with FORCE_BUILD=1 if this is intended."
              % (len(missing), ", ".join(missing)))
        return 1

    write(os.path.join(SITE, "index.html"), build_home(shell, cfg, posts))
    write(os.path.join(SITE, "essays", "index.html"), build_essays_index(shell, cfg, posts))
    write(os.path.join(SITE, "about", "index.html"), build_about(shell, cfg))
    write(os.path.join(SITE, "404.html"), build_404(shell, cfg))

    for index, post in enumerate(posts):
        # posts are newest-first, so the chronologically previous essay is the
        # next item in the list, not the previous one.
        older = posts[index + 1] if index + 1 < len(posts) else None
        newer = posts[index - 1] if index > 0 else None
        write(os.path.join(SITE, "essays", post["slug"], "index.html"),
              build_essay(shell, cfg, post, prev_post=older, next_post=newer))
        print("  essay: /essays/%s/ (%d words, %d min)"
              % (post["slug"], post.get("words") or 0, post.get("minutes") or 1))

    prune_removed_essays({p["slug"] for p in posts})

    write(os.path.join(SITE, "feed.xml"), build_rss(cfg, posts))
    write(os.path.join(SITE, "sitemap.xml"), build_sitemap(cfg, posts))
    write(os.path.join(SITE, "robots.txt"),
          "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % cfg["base_url"])

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
