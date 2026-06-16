# Lakshana marketing site

Single-file static landing page. No build step. Drop `index.html` on any static host.

## Local preview

```bash
python -m http.server -d site 8000
# → http://localhost:8000
```

## Deploy options (when you're ready)

- **Cloudflare Pages** — free, fast CDN. Just point at this repo, set output dir to `site/`.
- **GitHub Pages** — free, simpler. Repo settings → Pages → source = `main` branch, folder = `/site`. URL: `mickyaero.github.io/lakshana`.
- **Vercel / Netlify** — also free for static. Pick whichever you already have an account on.

## What's deliberate

- **No JS framework.** Just one inline `<script>` block. Loads instantly, works offline, ages well.
- **No images.** All demo output is real text from a real Groq run, captured as static HTML. No "loading…" spinners, no broken thumbnails.
- **Pre-canned demo data.** Field lists in the demo panel are from an actual `python benchmarks/run.py` execution. The visitor doesn't burn LLM cost on every visit, and the page never breaks because an API key expired.
- **Brand consistency with docstruct.** Same orange/cream palette, same Inter/Fira Code typography, so docstruct → Lakshana feels like one family.

## What's missing (future iterations)

- A 30-second demo GIF of the UMAP scatter forming + clusters auto-labeling. *This is the single biggest star-conversion lever.* Record it from `discover.html` in docstruct, drop in the hero.
- An OG/social preview image (1280×640 PNG) for X/LinkedIn link previews. Settings → Social preview on GitHub repo too.
- Analytics. Add Plausible or PostHog (privacy-respecting) so you know what's converting.
- A live "try it" CTA — a hosted version where someone uploads a folder and sees results. Out of scope for v0.1 (cost + abuse risk), but worth doing if traction lands.
- Hindi-language version of the BFSI tab copy. Builds Indian SEO + signals authenticity.

## When you change demo data

If you re-run the benchmark with a different LLM or dataset, update the cluster names and field chips inside the `<div class="demo-panel">` blocks in `index.html`. Keep the numbers in `.demo-meta` honest — what was actually measured, not aspirational.
