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
# Rendering
# --------------------------------------------------------------------------

def render(template, mapping):
    out = template
    for key, value in mapping.items():
        out = out.replace("{{%s}}" % key, str(value))
    return re.sub(r"\{\{[A-Z_]+\}\}", "", out)


def e(text):
    return html.escape(str(text), quote=True)


def page(shell, cfg, *, content, title, desc, url, depth=0,
         og_type="website", og_title=None, canonical=None,
         nav="", head_extra="", progress=False):
    root = "../" * depth if depth else ""
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
        "LINKEDIN": cfg["linkedin"],
        "EMAIL": cfg["email"],
        "ROOT": root,
        "CONTENT": content,
        "HEAD_EXTRA": head_extra,
        "PROGRESS": '<div class="progress" aria-hidden="true"></div>' if progress else "",
        "NAV_ESSAYS": ' aria-current="page"' if nav == "essays" else "",
        "NAV_ABOUT": ' aria-current="page"' if nav == "about" else "",
    })


def essay_list_item(post, depth=0):
    root = "../" * depth if depth else ""
    return """      <li>
        <a class="essay-item" href="{root}essays/{slug}/">
          <p class="essay-item__meta"><time datetime="{iso}">{stamp}</time> <i>&middot;</i> {mins} min read</p>
          <h3 class="essay-item__title">{title}</h3>
          <p class="essay-item__excerpt">{excerpt}</p>
        </a>
      </li>""".format(
        root=root,
        slug=post["slug"],
        iso=post["date"].strftime("%Y-%m-%d"),
        stamp=post["date"].strftime("%b %Y").upper(),
        mins=post["minutes"],
        title=e(post["title"]),
        excerpt=e(post["excerpt"]),
    )


def subscribe_block(cfg, heading, body):
    return """  <section class="subscribe">
    <div class="shell">
      <h2 class="subscribe__title">{heading}</h2>
      <p class="subscribe__body">{body}</p>
      <iframe class="subscribe__embed" src="{sub}/embed" title="Subscribe by email"
              loading="lazy" scrolling="no" frameborder="0"></iframe>
      <p class="subscribe__note">Delivered by Substack. No spam, and one click to leave.</p>
    </div>
  </section>""".format(heading=e(heading), body=e(body), sub=cfg["substack_url"])


def build_home(shell, cfg, posts):
    if posts:
        listing = """  <section class="section">
    <div class="shell">
      <div class="section__head">
        <p class="eyebrow">Latest essays</p>
        <a class="arrowlink" href="essays/">All essays <span>&rarr;</span></a>
      </div>
      <ul class="essays">
{items}
      </ul>
    </div>
  </section>""".format(items="\n".join(essay_list_item(p) for p in posts[:5]))
    else:
        listing = """  <section class="section">
    <div class="shell">
      <div class="empty">
        <h2 class="empty__title">The first essays are being written.</h2>
        <p class="empty__body">I would rather publish three pieces worth your time than
        thirty worth mine. Leave your email and the first one will find you.</p>
      </div>
    </div>
  </section>"""

    topics = """  <section class="section">
    <div class="shell">
      <div class="section__head"><p class="eyebrow">What I write about</p></div>
      <ul class="topics" style="margin-top:2.5rem">
        <li>
          <h3>Investing</h3>
          <p>What the Indian healthcare opportunity actually looks like from inside
          an investment committee, rather than from a pitch deck.</p>
        </li>
        <li>
          <h3>Healthcare</h3>
          <p>Why the system resists scale, written by someone who practised medicine
          before ever building a model about it.</p>
        </li>
        <li>
          <h3>AI &amp; strategy</h3>
          <p>Where the technology genuinely changes unit economics, and where it is
          an expensive way to do what a spreadsheet already did.</p>
        </li>
      </ul>
    </div>
  </section>"""

    hero = """  <section class="hero">
    <div class="shell">
      <h1 class="hero__title">{tagline}</h1>
      <p class="hero__sub">{sub}</p>
      <div class="hero__actions">
        <a class="btn btn--primary" href="{sub_url}" rel="noopener">Subscribe</a>
        <a class="arrowlink" href="about/">About me <span>&rarr;</span></a>
      </div>
    </div>
  </section>""".format(
        tagline=e(cfg["tagline"]),
        sub=e(cfg["hero_subtitle"]),
        sub_url=cfg["substack_url"],
    )

    schema = """<script type="application/ld+json">%s</script>""" % json.dumps({
        "@context": "https://schema.org",
        "@type": "Person",
        "name": cfg["author"],
        "url": cfg["base_url"],
        "email": "mailto:" + cfg["email"],
        "jobTitle": "Investor and strategist",
        "sameAs": [cfg["linkedin"], cfg["substack_url"]],
    }, separators=(",", ":"))

    return page(
        shell, cfg,
        content=hero + "\n" + listing + "\n" + subscribe_block(
            cfg, "Stay curious",
            "New essays on investing, healthcare and strategy in India, sent straight to your inbox."
        ) + "\n" + topics,
        title="%s — %s" % (cfg["site_title"], cfg["tagline"]),
        desc=cfg["description"],
        url=cfg["base_url"] + "/",
        head_extra=schema,
    )


def build_essays_index(shell, cfg, posts):
    if posts:
        body = """      <ul class="essays">
{items}
      </ul>""".format(items="\n".join(essay_list_item(p, depth=1) for p in posts))
        count = "%d essay%s" % (len(posts), "" if len(posts) == 1 else "s")
    else:
        body = """      <div class="empty">
        <h2 class="empty__title">Nothing published yet.</h2>
        <p class="empty__body">Essays will appear here automatically as they go out
        to subscribers. Subscribing is the surest way to catch the first one.</p>
      </div>"""
        count = "Coming soon"

    content = """  <section class="section">
    <div class="shell">
      <div class="section__head">
        <h1 class="about__title" style="margin-bottom:0">Essays</h1>
        <p class="eyebrow">{count}</p>
      </div>
{body}
    </div>
  </section>
{sub}""".format(count=e(count), body=body,
                sub=subscribe_block(cfg, "Get the next one",
                                    "Essays land in your inbox the moment they are published."))

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

    content = """  <section class="about">
    <div class="shell">
      <h1 class="about__title">About</h1>
      <div class="about__layout">
        <div class="prose measure">
{body}
        </div>
        <figure style="margin:0">
          <img class="about__portrait" src="../assets/img/portrait.jpg"
               width="900" height="900" alt="Portrait of Aditya Dave" loading="lazy" decoding="async">
          <figcaption class="about__portrait-cap">Aditya Dave</figcaption>
        </figure>
      </div>
      <ul class="contact">
        <li><b>Email</b><span><a class="textlink" href="mailto:{email}">{email}</a></span></li>
        <li><b>LinkedIn</b><span><a class="textlink" href="{linkedin}" rel="noopener">Connect with me</a></span></li>
        <li><b>Newsletter</b><span><a class="textlink" href="{sub}" rel="noopener">Subscribe on Substack</a></span></li>
      </ul>
    </div>
  </section>""".format(
        body=about_body, email=cfg["email"],
        linkedin=cfg["linkedin"], sub=cfg["substack_url"],
    )

    return page(
        shell, cfg,
        content=content,
        title="About — %s" % cfg["site_title"],
        desc="Aditya Dave: doctor turned strategist and investor, writing on investing, healthcare and AI in India.",
        url=cfg["base_url"] + "/about/",
        depth=1, nav="about", og_type="profile",
    )


def build_essay(shell, cfg, post):
    url = "%s/essays/%s/" % (cfg["base_url"], post["slug"])
    canonical = post["source"] if cfg.get("canonical_to_substack") and post["source"] else url

    schema = """<script type="application/ld+json">%s</script>""" % json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "description": post["excerpt"],
        "datePublished": post["date"].isoformat(),
        "wordCount": post["words"],
        "author": {"@type": "Person", "name": cfg["author"], "url": cfg["base_url"]},
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
    }, separators=(",", ":"))

    source_link = ""
    if post["source"]:
        source_link = '<a class="textlink" href="%s" rel="noopener">Read it on Substack</a>' % e(post["source"])

    content = """  <article class="article">
    <div class="shell">
      <a class="article__back" href="../"><span>&larr;</span> All essays</a>
      <p class="article__meta">
        <time datetime="{iso}">{stamp}</time> <i>&middot;</i> {mins} min read
      </p>
      <h1 class="article__title">{title}</h1>
      <hr class="rule article__divider">
      <div class="prose">
{body}
      </div>
      <div class="postscript">
        <span>Written by {author}</span>
        <span>{source}</span>
      </div>
    </div>
  </article>
{sub}""".format(
        iso=post["date"].strftime("%Y-%m-%d"),
        stamp=post["date"].strftime("%d %B %Y").lstrip("0").upper(),
        mins=post["minutes"],
        title=e(post["title"]),
        body=post["body"],
        author=e(cfg["author"]),
        source=source_link,
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
        head_extra=schema,
    )


def build_404(shell, cfg):
    content = """  <section class="notfound">
    <div class="shell">
      <p class="eyebrow">Error 404</p>
      <h1>This page went looking for a better idea.</h1>
      <p>The link may be old, or the essay may have moved. The essays index below
      has everything that currently exists.</p>
      <div class="hero__actions">
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
    now = format_datetime(datetime.now(timezone.utc))
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
  <lastBuildDate>{now}</lastBuildDate>
  <atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml"/>
{items}
</channel>
</rss>
""".format(title=e(cfg["site_title"]), base=cfg["base_url"],
           desc=e(cfg["description"]), now=now, items="\n".join(items))


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

    for slug in previous:
        if slug in current_slugs:
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
    data = fetch_feed(cfg["substack_feed"])

    # Safety rail 1: never publish an empty site because the network blipped.
    if data is None and known and not force:
        print("\nREFUSING TO BUILD: the feed could not be fetched and there is no\n"
              "cache, but %d essay(s) are currently published. Publishing now would\n"
              "delete them. The existing site/ is untouched.\n"
              "Override with FORCE_BUILD=1 if this is really what you want."
              % len(known))
        return 1

    posts = parse_feed(data, cfg)
    print("  essays: %d" % len(posts))

    # Safety rail 2: a feed that suddenly reports zero posts is far more often a
    # Substack hiccup than a deliberate mass-unpublish.
    if known and not posts and not force:
        print("\nREFUSING TO BUILD: the feed parsed cleanly but returned zero essays,\n"
              "while %d were published on the last run. That is far more likely to be\n"
              "a Substack glitch than a real deletion, so site/ is untouched.\n"
              "Override with FORCE_BUILD=1 if you genuinely unpublished everything."
              % len(known))
        return 1

    write(os.path.join(SITE, "index.html"), build_home(shell, cfg, posts))
    write(os.path.join(SITE, "essays", "index.html"), build_essays_index(shell, cfg, posts))
    write(os.path.join(SITE, "about", "index.html"), build_about(shell, cfg))
    write(os.path.join(SITE, "404.html"), build_404(shell, cfg))

    for post in posts:
        write(os.path.join(SITE, "essays", post["slug"], "index.html"),
              build_essay(shell, cfg, post))
        print("  essay: /essays/%s/ (%d words, %d min)"
              % (post["slug"], post["words"], post["minutes"]))

    prune_removed_essays({p["slug"] for p in posts})

    write(os.path.join(SITE, "feed.xml"), build_rss(cfg, posts))
    write(os.path.join(SITE, "sitemap.xml"), build_sitemap(cfg, posts))
    write(os.path.join(SITE, "robots.txt"),
          "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % cfg["base_url"])

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
