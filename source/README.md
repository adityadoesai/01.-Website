# Source images

Masters, kept so the web versions can be regenerated without hunting for the
original.

- `hero-original.png` — the full 1024x1024 illustration, as generated.

## Replacing the hero illustration

The hero lives at exactly one path:

```
site/assets/images/hero.png
```

**Swapping it is a single file copy.** No code change, no config edit, no
rebuild-script change. Drop the new file at that path, commit, push.

Three things to get right in the new file:

**Proportions do not matter.** The layout caps width at 40rem and lets height
follow, so 16:9, 3:2, square or portrait all work without touching CSS. Tested.

**The background must be transparent, or matted to `#FBF9F5`.** This is the one
real constraint. The current illustration's top-left corner is `#FFFFFD` —
near-white, because the whiteboard runs to the edge — which reads as a pale slab
against the site's warm ground. It is currently contained with a hairline
border. A transparent PNG needs no such workaround.

**Keep it under about 400KB.** It is the first thing a visitor loads. The
current file is 833KB, which is heavier than ideal; a smaller replacement is a
straight win.

## Recutting the current master

`sips` ships with macOS, so no extra tools are needed. It always crops from the
centre, and it can read WebP but cannot write it, so PNG or JPEG are the
practical outputs.

```bash
sips -c <height> 1024 source/hero-original.png --out /tmp/crop.png
cp /tmp/crop.png site/assets/images/hero.png
```
