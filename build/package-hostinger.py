#!/usr/bin/env python3
"""
Package the built site for upload to Hostinger.

Cloudflare Pages reads _headers and _redirects; Apache/LiteSpeed does not, and
needs an .htaccess instead. This produces a zip whose contents drop straight
into public_html.

    python3 build/build.py              # regenerate the site
    python3 build/package-hostinger.py  # wrap it for Hostinger
"""

import os
import shutil
import tempfile
import zipfile

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD_DIR)
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(ROOT, "hostinger-upload.zip")
OUT_DIR = os.path.join(ROOT, "_upload-to-public_html")

# Cloudflare-only control files; meaningless to Apache.
SKIP = {"_headers", "_redirects", ".DS_Store"}

HTACCESS_FILE = os.path.join(BUILD_DIR, "htaccess.conf")


def read_htaccess():
    with open(HTACCESS_FILE, encoding="utf-8") as fh:
        return fh.read()



def main():
    if not os.path.isdir(SITE):
        raise SystemExit("site/ not found - run python3 build/build.py first")

    staged = tempfile.mkdtemp(prefix="hostinger-")
    try:
        count = 0
        for root, dirs, files in os.walk(SITE):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for name in files:
                if name in SKIP:
                    continue
                src = os.path.join(root, name)
                rel = os.path.relpath(src, SITE)
                dst = os.path.join(staged, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                count += 1

        with open(os.path.join(staged, ".htaccess"), "w", encoding="utf-8") as fh:
            fh.write(read_htaccess())
        count += 1

        # Finder and most file managers hide names beginning with a dot, so the
        # .htaccess is easy to leave behind during a drag-and-drop upload - and
        # nothing visibly breaks when you do. Ship a visible twin that can be
        # uploaded and renamed on the server instead.
        with open(os.path.join(staged, "htaccess-RENAME-ME.txt"), "w", encoding="utf-8") as fh:
            fh.write(read_htaccess())
        count += 1

        if os.path.exists(OUT):
            os.remove(OUT)
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(staged):
                for name in files:
                    path = os.path.join(root, name)
                    zf.write(path, os.path.relpath(path, staged))

        # Also emit a plain folder. Hostinger's File Manager can upload a folder
        # directly, which skips the extract step - a step that is easy to miss
        # and fails silently when it is.
        if os.path.isdir(OUT_DIR):
            shutil.rmtree(OUT_DIR)
        shutil.copytree(staged, OUT_DIR)

        size = os.path.getsize(OUT) / 1024
        print("Packaged %d files." % count)
        print("  zip    -> %s (%.0f KB)" % (os.path.basename(OUT), size))
        print("  folder -> %s/" % os.path.basename(OUT_DIR))
        print("\nUpload EITHER: drag the folder's contents into public_html,")
        print("or upload the zip into public_html and extract it there.")
    finally:
        shutil.rmtree(staged, ignore_errors=True)


if __name__ == "__main__":
    main()
