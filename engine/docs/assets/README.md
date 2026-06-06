# Assets

Provenance for visual assets in this folder.

| File | What | Origin | License |
|---|---|---|---|
| `mascot.svg` | "Codex" the bug-hunter mascot + `debugmaster` wordmark | Original hand-authored SVG (vector, no third-party clip-art) | MIT (this repo) |
| `social-preview.png` | 1280×640 social/hero image | Rendered from `mascot.svg` via `rsvg-convert` | MIT (this repo) |

No third-party fonts are embedded; the wordmark renders with the system sans-serif
(Helvetica Neue / Arial fallback). No external images, icons, or stock assets are used.

## Regenerate

```bash
rsvg-convert -w 1280 -h 640 docs/assets/mascot.svg -o docs/assets/social-preview.png
```

Target: GitHub/Gitea social preview — 1280×640, PNG, under 1 MB.
