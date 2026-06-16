"""Build site/demo/index.html from docstruct's discover.html.

Transforms applied:
  1. Strip the docstruct global nav/script include (replaced with our own header).
  2. Change <title> + add Lakshana branding chrome.
  3. Replace Step 1 (Upload) content with a static "Sample run" intro.
  4. Inject DEMO_MODE script that:
       - Stubs window.fetch for the few read paths still hit.
       - Replaces D.startAnalysis with an animated playback then jump to results.
       - Disables mutations (export, save, project create) with a toast.
       - On load, immediately calls _showResults(DEMO_DATA) and goes to step 3.
  5. Embed DEMO_DATA inline (from data.json that run_for_demo.py produced).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DOCSTRUCT_HTML = Path("/Users/mickydroch/Desktop/Air/Micky/Development/docstruct/src/static/discover.html")
DATA_JSON = HERE / "data.json"
OUT = HERE / "index.html"


SAMPLE_RUN_INTRO = """
  <!-- Step 1 (Demo) — Sample run intro -->
  <div class="page active" data-step="1">
    <div class="page-title">Sample run · Aircraft engineering reports</div>
    <div class="page-subtitle">A playback of what Lakshana discovered when run on 30 aerospace documents across 3 types. You're seeing the real output, just pre-computed.</div>

    <div style="background:linear-gradient(135deg,rgba(207,109,53,0.06),rgba(207,109,53,0.02));border:1px solid rgba(207,109,53,0.20);border-radius:var(--r-lg);padding:1.1rem 1.3rem;margin-bottom:1.25rem">
      <strong style="font-size:0.9rem;color:var(--text);display:block;margin-bottom:0.4rem">What's in this corpus</strong>
      <div style="font-size:0.85rem;color:var(--text-2);line-height:1.6">
        30 synthetic but realistic aerospace documents: Maintenance Inspection Reports (A/B/C/D-checks, ATA-chapter referenced), Flight Test Reports (CAR-23 / CS-25 acceptance tests), and Service Bulletins (manufacturer modification advisories). Fleet includes A320neo, A350-900, B787-8, ATR 72-600, and others.
        <br><br>
        Lakshana was given no labels. It clustered the documents into the 3 implicit types, named each one, inferred a schema per type, and verified field frequencies. The output you'll see across the next steps is what came out — UMAP coordinates, cluster cards, schemas, coverage, and the lot.
      </div>
    </div>

    <div class="card" style="display:flex;gap:1rem;align-items:center;justify-content:space-between;padding:0.9rem 1.2rem">
      <div>
        <div style="font-size:0.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em">Model used</div>
        <div style="font-weight:600;font-size:0.96rem;margin-top:0.1rem" id="demo-model-label">—</div>
      </div>
      <div>
        <div style="font-size:0.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em">Wall time</div>
        <div style="font-weight:600;font-size:0.96rem;margin-top:0.1rem" id="demo-time-label">—</div>
      </div>
      <div>
        <div style="font-size:0.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em">Documents</div>
        <div style="font-weight:600;font-size:0.96rem;margin-top:0.1rem" id="demo-doc-label">—</div>
      </div>
      <div>
        <div style="font-size:0.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em">Clusters found</div>
        <div style="font-weight:600;font-size:0.96rem;margin-top:0.1rem" id="demo-cluster-label">—</div>
      </div>
    </div>

    <div class="footer-bar">
      <button class="btn btn-primary btn-next" onclick="D.startAnalysis()">Play the analysis &#8594;</button>
      <button class="btn btn-secondary" onclick="D._jumpToResults()">Skip to results &#8594;</button>
    </div>
  </div>
"""


DEMO_SCRIPT = """
<script>
// === LAKSHANA DEMO MODE OVERRIDES ============================================
// Stub globals that the lifted code expects from docstruct-shortcuts / apikeys / nav.
// These are no-ops; the demo doesn't need their UI affordances.
window.DocstructShortcuts = {
  showSkeleton: () => {},
  showProgressiveStatus: () => {},
  confidenceDot: (v) => v != null ? `<span style="color:#888">●</span>` : '',
  confidencePill: (v) => `<span style="font-size:0.75rem;color:#666">${Math.round((v||0)*100)}%</span>`,
  init: () => {},
};
window.DocstructApiKeys = { render: () => {} };
window.DocstructNav = { init: () => {} };

const DEMO_DATA = __DEMO_DATA__;
const DEMO_LOG_LINES = [
  "Parsing 30 documents (PDFs / text / OCR fallback)…",
  "Building hybrid embeddings — structural fingerprint + semantic vector…",
  "UMAP projecting 384-dim embeddings → 2D + 3D…",
  "HDBSCAN clustering (min_cluster_size = 3)…",
  "Discovered 3 clusters. Sizes: 10 / 10 / 10",
  "Labelling clusters via LLM…",
  "  Cluster 0 — naming and keywords…",
  "  Cluster 1 — naming and keywords…",
  "  Cluster 2 — naming and keywords…",
  "Inferring schema for each cluster (iterative field discovery)…",
  "  cluster 0: 9 fields proposed",
  "  cluster 1: 11 fields proposed",
  "  cluster 2: 10 fields proposed",
  "Verifying field frequency across documents (LLM grounded)…",
  "Deduplicating semantically similar fields…",
  "Grouping fields into semantic categories…",
  "Done."
];

document.addEventListener('DOMContentLoaded', () => {
  // Populate intro stats
  const model = (DEMO_DATA.model || 'openai/gpt-4o-mini').replace('openai/', '').replace('groq/', '');
  document.getElementById('demo-model-label').textContent = model;
  document.getElementById('demo-time-label').textContent = (DEMO_DATA.elapsed_seconds || DEMO_DATA.stats?.duration_s || '—') + ' s';
  document.getElementById('demo-doc-label').textContent = DEMO_DATA.stats?.total_docs || (DEMO_DATA.doc_names||[]).length || '—';
  document.getElementById('demo-cluster-label').textContent = DEMO_DATA.stats?.clusters || (DEMO_DATA.clusters||[]).length || '—';
});

// Override fetch — return canned shapes so any leftover call resolves harmlessly.
const _origFetch = window.fetch;
window.fetch = function(url, opts={}) {
  if (typeof url !== 'string') return _origFetch.call(this, url, opts);
  if (url.includes('/api/settings/llm-keys')) {
    return Promise.resolve({ok:true, json:()=>Promise.resolve({models:[
      {id:'openai/gpt-4o-mini', name:'GPT-4o mini', provider:'openai', provider_label:'OpenAI'}
    ]})});
  }
  if (url.includes('/api/projects') && !opts.method) {
    return Promise.resolve({ok:true, json:()=>Promise.resolve({projects:[]})});
  }
  if (url.includes('/api/schema-templates') && (opts.method === undefined || opts.method === 'GET')) {
    return Promise.resolve({ok:true, json:()=>Promise.resolve({templates:[]})});
  }
  // Block writes
  return Promise.resolve({ok:false, status:403, json:()=>Promise.resolve({detail:'Disabled in demo'})});
};

// Wait until D exists, then patch behaviour
function _wirePatch() {
  if (typeof D === 'undefined') { setTimeout(_wirePatch, 30); return; }

  D.projectId = 'demo';
  D._createdProjectId = 'demo';

  // Animated playback then jump to results
  D.startAnalysis = function() {
    this._unlockStep(2); this.goToStep(2);
    const bar = document.getElementById('d-progress-bar');
    const status = document.getElementById('d-progress-status');
    const log = document.getElementById('d-live-log');
    log.innerHTML = '';
    let i = 0;
    const total = DEMO_LOG_LINES.length;
    const tick = () => {
      if (i >= total) {
        bar.style.width = '100%';
        status.textContent = 'Complete';
        setTimeout(() => {
          D._showResults(DEMO_DATA);
          D._unlockStep(3); D.goToStep(3);
        }, 350);
        return;
      }
      const line = DEMO_LOG_LINES[i];
      D._addLog(line);
      status.textContent = line;
      bar.style.width = `${Math.round((i+1)/total*100)}%`;
      i++;
      setTimeout(tick, 260);
    };
    tick();
  };

  // Instant jump (no playback) for impatient viewers
  D._jumpToResults = function() {
    D._unlockStep(2);
    D._unlockStep(3);
    D._showResults(DEMO_DATA);
    D.goToStep(3);
  };

  // Disable mutation actions
  const _disabledMsg = 'Demo only — action disabled. Clone the repo to run lakshana locally.';
  ['saveSchema','exportFormat','exportToStructure','rediscoverSchema','launchPipeline','startPipeline','saveAsTemplate','deleteTemplate','loadTemplates','testLLMKey'].forEach(fn => {
    if (typeof D[fn] === 'function') {
      D[fn] = function(){ D.toast(_disabledMsg, 'info'); };
    }
  });

  // On load: auto-play after a beat
  setTimeout(() => {
    if (D.currentStep === 1) {
      // Pre-fill the model label and let the user click play; do nothing automatic
    }
  }, 200);
}
_wirePatch();
</script>
"""


def main() -> int:
    if not DATA_JSON.exists():
        print(f"data.json not found at {DATA_JSON}; run benchmarks/data/aircraft/run_for_demo.py first", file=sys.stderr)
        return 1
    if not DOCSTRUCT_HTML.exists():
        print(f"source discover.html not found: {DOCSTRUCT_HTML}", file=sys.stderr)
        return 1

    html = DOCSTRUCT_HTML.read_text()

    # 1. Update <title> + favicon
    html = html.replace(
        '<title>docstruct — Discover (Template Discovery)</title>',
        '<title>Lakshana — Discover (live demo replay)</title>',
    )
    html = html.replace(
        '<link rel="icon" href="/static/logo.svg" type="image/svg+xml">',
        '<link rel="icon" href="../favicon.svg" type="image/svg+xml">',
    )
    # docstruct.css won't resolve here — strip the link and provide minimal fallback styles
    html = html.replace(
        '<link rel="stylesheet" href="/static/docstruct-ui.css">',
        '<link rel="stylesheet" href="demo.css">',
    )

    # 2. Strip every docstruct-internal script include + the init() blocks
    # that depend on them. The pre-script stubs (added in DEMO_SCRIPT) provide
    # no-op fallbacks for DocstructShortcuts / DocstructApiKeys / DocstructNav.
    html = re.sub(
        r'<script[^>]+src="/static/(docstruct-[a-z-]+\.js|keyboard-shortcuts\.js)"[^>]*></script>',
        '',
        html,
    )
    html = re.sub(
        r'DocstructNav\.init\([^)]*\(?[^)]*\)?[^)]*\);?',
        '',
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'DocstructShortcuts\.init\([^)]*\);?',
        '',
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r"DocstructApiKeys\.render\('[^']*'\);?",
        '',
        html,
    )

    # 3. Replace Step 1 (Upload) content with the sample-run intro.
    # We match the `<!-- Step 1: Upload -->` block up to (but not including) `<!-- Step 2:`.
    step1_pattern = re.compile(
        r'<!--\s*Step 1: Upload\s*-->.*?(?=<!--\s*Step 2:)',
        re.DOTALL,
    )
    if not step1_pattern.search(html):
        print("WARN: could not find Step 1 block to replace; skipping", file=sys.stderr)
    else:
        html = step1_pattern.sub(SAMPLE_RUN_INTRO + "\n  ", html)

    # 4. Replace the step-bar wizard nav — remove Upload, rename Analyze to "Playback"
    html = html.replace(
        '<div class="step-item active" data-step="1" onclick="D.goToStep(1)"><span class="step-num">1</span> Upload</div>',
        '<div class="step-item active" data-step="1" onclick="D.goToStep(1)"><span class="step-num">1</span> Sample</div>',
    )
    html = html.replace(
        '<div class="step-item disabled" data-step="2" onclick="D.goToStep(2)"><span class="step-num">2</span> Analyze</div>',
        '<div class="step-item disabled" data-step="2" onclick="D.goToStep(2)"><span class="step-num">2</span> Playback</div>',
    )

    # 5. Inject DEMO_MODE script with embedded DEMO_DATA right before </body>
    data = DATA_JSON.read_text()
    demo_script = DEMO_SCRIPT.replace('__DEMO_DATA__', data)
    html = html.replace('</body>', demo_script + '\n</body>')

    OUT.write_text(html)
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
