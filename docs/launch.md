# Lakshana — launch sequence (draft)

> **Status:** Draft, not posted anywhere. Review and edit before going live.
> **Owner:** Micky (@mickyaero)
> **Last updated by:** Claude

---

## Pre-launch checklist

Block on these before posting anywhere:

- [ ] **IP clearance.** Confirm your employment agreement allows OSSing this. If unsure, get a one-line email ack from your manager: *"Micky retains rights to docstruct and its components."* This is the single biggest risk.
- [ ] **Flip repo to public.** `gh repo edit mickyaero/lakshana --visibility public --accept-visibility-change-consequences`
- [ ] **Watch CI on the public repo for 24h** — make sure no secrets leaked in commits (none should have, but check `git log -p | grep -iE 'key|token|secret'`).
- [ ] **Star the repo yourself + ask 3-5 friends to star** before T+0 so the count isn't at 0. Coordinate by Slack/WhatsApp the day before.
- [ ] **Pin a demo GIF/video** to the repo (top of README and as the social preview image). The single highest-leverage asset for star conversion.
- [ ] **Author Twitter/X account is warm** (not a brand-new handle). Use @mickyaero.
- [ ] **Set up GitHub repo social preview image** — Settings → Social preview. 1280x640 PNG.
- [ ] **GitHub repo description + topics set** — keywords: `document-extraction`, `schema-discovery`, `clustering`, `umap`, `hdbscan`, `llm`, `pdf`.

---

## T+0: Tuesday 8:00am PT (Show HN window)

**Why this time:** Highest HN traffic, Asia is asleep so the West-coast morning peak gets unbroken time on the front page.

### Show HN post

**Title (max 80 chars):**
> Show HN: Lakshana – Zero-config schema discovery for any folder of documents

**Body:**
```
Hi HN — I've been building a document extraction stack at docstruct.com for the
last few months, and pulled out one piece I think stands on its own.

Lakshana takes a folder of mixed PDFs/images/text — invoices, contracts,
statements, whatever — and figures out:

  1) which document TYPES are in there (clusters them with UMAP + HDBSCAN over
     a hybrid structural+semantic embedding)
  2) what FIELDS each type has (asks an LLM to infer a schema, then verifies
     field frequency across the cluster)
  3) a clean JSON Schema per type, ready to drive your extraction pipeline

The "tell me what I have" step that every doc-extraction tool skips —
because they all assume you already know your schema. Real-world data
doesn't work that way.

Quickstart:

    pip install lakshana
    export GROQ_API_KEY=...  # free tier works
    lakshana analyze ./my_docs --output schema.json

Things I'm proud of:

  - CPU only, no GPU
  - Multi-LLM: Anthropic, OpenAI, Groq, Cerebras, Ollama, Google, OpenRouter
  - Reproducible benchmark in-repo: `python benchmarks/run.py` — bundles
    50 synthetic docs across 5 types AND 35 Indian BFSI samples across 7 types
  - 77 unit tests, CI green on Python 3.10/3.11/3.12

Things I want feedback on:

  - The field-grouping LLM prompt is fragile across model providers — would
    welcome eyes on it
  - Right now everything happens in-process; a hosted version is on my mind
    but I want to ship the library first
  - Naming: "Lakshana" is Sanskrit for "defining characteristic / marker."
    Curious whether that lands or alienates non-Indian devs

GitHub: https://github.com/mickyaero/lakshana
MIT licensed.
```

**HN posting playbook:**
- Post yourself, not via a friend. The "show" prefix matters.
- Don't ask people to upvote in chat. HN will detect ring-voting and bury the post. Coordinate stars on GitHub, not HN upvotes.
- First 90 min are decisive. Stay at your desk; reply to every comment in under 10 min. Replies bump the post.
- Don't be defensive. If someone says "this looks like X" — agree it shares X's shape, then explain the wedge.

---

## T+0 (same day, 4 hours later): X/Twitter

**Thread template (each tweet ≤280 chars):**

```
1/ I open-sourced Lakshana — give it a folder of mixed PDFs/images,
   it figures out what document types are in there and what fields each
   type has. Returns a clean JSON Schema per type.

   No training. No labels. CPU only.

   github.com/mickyaero/lakshana
   [PIN A 30-SEC DEMO GIF HERE — UMAP forming + schema unfolding]

2/ The pipeline:

   parse → embed (structural + semantic) → cluster (UMAP+HDBSCAN)
   → LLM schema infer → verify field frequency → export.

   Each step has a fallback. Each export format is real: JSON Schema,
   CSV headers, Markdown, structure entities.

3/ Why I built it: every "AI document extraction" tool assumes you
   already know your schema. Real-world data is messier than that —
   you get a hard drive of receipts and contracts and ??? and you
   have to figure out the shape before you can extract anything.

   Lakshana is the discovery step. Then your pipeline can be simple.

4/ Bundled benchmark: 50 synthetic docs across 5 doc types
   (invoice/memo/contract/resume/report) + 35 Indian BFSI docs
   across 7 types (GST invoice, ITR, Form 26AS, bank stmt, etc.)

   `python benchmarks/run.py` — reproducible by anyone in <2 min.

5/ Stack: numpy, scikit-learn, umap-learn, sentence-transformers,
   pdfplumber, pytesseract.

   LLM provider is your choice — Groq's free tier is the default
   so the quickstart actually costs $0.

6/ MIT licensed. Drop a star if you find it useful, drop an issue
   if you don't.

   github.com/mickyaero/lakshana
```

**Tagging:** @huggingface @umap_learn @groqinc — sparingly. One per thread, in the most relevant tweet.

---

## T+1 (Wednesday): Reddit

Three subreddits, three DIFFERENT posts (not copy-paste, mods flag it):

### r/MachineLearning (academic angle)
**Title:** `[P] Lakshana: unsupervised schema discovery for document collections via UMAP+HDBSCAN + LLM verification`

Body emphasizes: hybrid embedding (structural + semantic), the cluster purity benchmark, the field frequency verification step. Link to benchmark results JSON in the repo.

### r/LocalLLaMA (local/free angle)
**Title:** `Open-sourced a doc analyzer that runs end-to-end on Groq free tier — no API costs`

Body emphasizes: Ollama support, the free-tier default, no GPU required. Show the actual cost ($0) of running the benchmark.

### r/dataengineering (workflow angle)
**Title:** `Tired of guessing schemas for messy document folders — built a tool that infers them`

Body emphasizes: the "what's in this folder" problem, integration with downstream extraction (JSON Schema export), the OpenAPI/tool-use angle.

---

## T+2 (Thursday): DEV.to + LinkedIn

### DEV.to long-form post
**Title:** "How we got 92% cluster purity on document type discovery without labels"

(Or whatever the *actual* measured number is — link to `benchmarks/results/` in the repo.)

Outline:
1. The problem: schemas don't fall from the sky
2. Why supervised approaches fail in practice (no labels, drift, long tail)
3. The pipeline: parse, embed, cluster, infer, verify
4. The "hybrid embedding" trick — structural fingerprint + semantic embedding
5. Why HDBSCAN over k-means
6. The frequency verification step that makes the schema trustworthy
7. Where it falls down (low-doc-count clusters, noisy OCR)
8. Roadmap

This ranks on Google forever. Worth 4-6 hours to write properly.

### LinkedIn post
**Hook:** *"I just open-sourced a piece of an internal tool that I wish existed when I started building document extraction pipelines."*

Then: the problem, the link, one screenshot, a soft CTA for hiring/consulting if you're open to it. Keep it under 1000 chars or LinkedIn truncates.

---

## T+7: ProductHunt (only if HN/X went well)

Skip ProductHunt if HN was a dud. PH demands a sustained launch effort that only pays off with momentum.

If launching: schedule for Tuesday 12:01am PT. Title: "Lakshana — Find the shape of any folder of documents." Tagline emphasizes the developer audience.

---

## Friendly-fire ping list

People to DM/email *before* posting publicly so they can star/comment in the first hour:

- [ ] **Anyone you know at HuggingFace** — embedding angle resonates
- [ ] **Indian dev community contacts** — IndieHackers India, Pesto, Lobster
- [ ] **Folks who starred docstruct** — they're warm leads
- [ ] **Anyone who tweeted about Unstract or LlamaParse** — relevant audience
- [ ] **5 close friends** — they star and comment regardless

Coordinated WhatsApp message the night before:
> *"Open-sourcing a small tool tomorrow morning at 8am PT. If you're around, would mean a lot if you could ⭐ on GitHub when you see my X post. github.com/mickyaero/lakshana — no pressure if you're busy."*

---

## What to NOT do

- ❌ **Don't post on multiple platforms simultaneously.** Stagger by 4+ hours so you can engage on each one individually.
- ❌ **Don't fake stars.** GitHub detects bot accounts and the consequences are bad.
- ❌ **Don't argue with critics in public.** Acknowledge, ask a clarifying question, and move the conversation to GitHub issues.
- ❌ **Don't ship the launch hot-fixes from your phone.** Pre-write any 0.1.1 patch before posting. If a bug surfaces during launch, you want to fix it from your laptop in under 30 min.
- ❌ **Don't compare yourself to specific competitors by name in launch copy** unless they're significantly bigger than you. Punching up reads well; punching across reads petty.

---

## Success metrics (review at T+7 and T+30)

| Metric | T+7 target | T+30 target | Honest baseline |
|---|---|---|---|
| GitHub stars | 50 | 200 | Most "Show HN" libraries get 20-50 in week one |
| Issues filed | 3 | 10 | A sign of real usage |
| PyPI downloads (week) | 100 | 500 | Once published to PyPI |
| External blog mentions | 0 | 1-2 | Anyone writing about you = compounding |
| Stars/day at T+30 | — | 2-5/day | Indicates sustained interest |

If you're below baseline at T+30, the answer is almost always: the demo isn't compelling enough, or the README first impression is weak. Iterate on those before relaunching.

---

## After-launch sustaining motion (first 90 days)

The OSS projects that win aren't the ones with the best launch — they're the ones whose maintainer answers issues in <24h for the first 3 months.

Block a 30-min daily slot. Triage issues, respond to comments, merge small PRs. After 90 days you can ease off; before that, you can't.
