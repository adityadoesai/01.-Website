# Source images

Masters, kept so the web versions can be regenerated without hunting for the
original.

- `hero-original.png` — the full 1024x1024 illustration, as generated.
  `site/assets/img/hero.jpg` is a centred 1024x820 crop of it at JPEG quality 80.

To recut the hero (macOS, no extra tools needed):

```bash
sips -c <height> 1024 source/hero-original.png --out /tmp/crop.png
sips -s format jpeg -s formatOptions 80 /tmp/crop.png --out site/assets/img/hero.jpg
```

`sips` always crops from the centre. It can read WebP but cannot write it, so
JPEG is the practical output format here.
