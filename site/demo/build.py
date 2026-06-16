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

    <div class="card" style="margin-top:1.1rem;padding:1.1rem 1.3rem">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.65rem">
        <strong style="font-size:0.95rem;color:var(--text)">Browse the corpus</strong>
        <span style="font-size:0.78rem;color:var(--muted)">Click any document to read it. These are the raw files Lakshana saw.</span>
      </div>
      <div id="demo-doc-browser" style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.85rem">
        <!-- populated by _renderSampleDocBrowser() -->
      </div>
    </div>

    <div class="footer-bar">
      <button class="btn btn-primary btn-next" onclick="D.startAnalysis()">Play the analysis &#8594;</button>
      <button class="btn btn-secondary" onclick="D._jumpToResults()">Skip to results &#8594;</button>
    </div>
  </div>

  <!-- Doc preview modal (lives outside the wizard pages) -->
  <div id="demo-doc-modal" class="hidden" style="position:fixed;inset:0;background:rgba(26,22,17,0.55);z-index:1000;align-items:flex-start;justify-content:center;padding:4rem 1.5rem;overflow-y:auto;display:none">
    <div style="background:var(--surface,white);border-radius:14px;max-width:780px;width:100%;box-shadow:0 24px 60px -16px rgba(0,0,0,0.3);overflow:hidden">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:0.85rem 1.2rem;border-bottom:1px solid var(--border)">
        <div>
          <div id="demo-doc-modal-title" style="font-family:'JetBrains Mono','SF Mono',monospace;font-size:0.92rem;font-weight:600;color:var(--text)">document</div>
          <div id="demo-doc-modal-type" style="font-size:0.75rem;color:var(--muted);margin-top:0.15rem">ground-truth doc type</div>
        </div>
        <button onclick="_demoCloseModal()" style="background:none;border:0;cursor:pointer;font-size:1.3rem;color:var(--muted);padding:0.3rem 0.5rem;line-height:1">&times;</button>
      </div>
      <pre id="demo-doc-modal-body" style="margin:0;padding:1.1rem 1.4rem;max-height:60vh;overflow-y:auto;font-family:'JetBrains Mono','SF Mono',monospace;font-size:0.82rem;line-height:1.65;color:var(--text-2);white-space:pre-wrap;background:#fafaf7"></pre>
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

// Render a per-type document browser on the Sample step.
// Groups docs by their ground-truth doc_type (read from doc_cluster_ids
// + cluster names) so users can scan what's in each pile.
function _renderSampleDocBrowser(data) {
  const root = document.getElementById('demo-doc-browser');
  if (!root || !data.doc_names) return;
  const clustersById = {};
  (data.clusters || []).forEach(c => { clustersById[String(c.id)] = c; });

  // group doc indices by their cluster id
  const byCluster = {};
  (data.doc_cluster_ids || []).forEach((cid, idx) => {
    const k = String(cid);
    (byCluster[k] = byCluster[k] || []).push(idx);
  });

  const groupHtml = Object.entries(byCluster).map(([cid, indices]) => {
    const cluster = clustersById[cid] || { name: 'Cluster ' + cid };
    const items = indices.map(idx => {
      const name = (data.doc_names[idx] || ('doc_' + idx)).replace(/^.*\//, '');
      return `<button class="demo-doc-item" data-idx="${idx}" data-type="${esc(cluster.name)}"
        style="text-align:left;background:var(--surface,white);border:1px solid var(--border);border-radius:6px;padding:0.4rem 0.55rem;cursor:pointer;font-family:'JetBrains Mono','SF Mono',monospace;font-size:0.74rem;color:var(--text-2);transition:all 0.12s">
        ${esc(name)}
      </button>`;
    }).join('');
    return `
      <div class="demo-doc-group">
        <div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.45rem">
          <span style="font-weight:600;font-size:0.82rem;color:var(--text)">${esc(cluster.name)}</span>
          <span style="font-size:0.72rem;color:var(--muted)">${indices.length} docs</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:0.3rem">${items}</div>
      </div>
    `;
  }).join('');

  root.innerHTML = groupHtml;

  root.querySelectorAll('.demo-doc-item').forEach(btn => {
    btn.addEventListener('mouseenter', () => {
      btn.style.background = 'var(--accent-g,#fdf4ed)';
      btn.style.borderColor = 'var(--accent,#cf6d35)';
      btn.style.color = 'var(--accent,#cf6d35)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.background = 'var(--surface,white)';
      btn.style.borderColor = 'var(--border,#ddd2c4)';
      btn.style.color = 'var(--text-2,#564c40)';
    });
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx, 10);
      _demoOpenModal(idx, btn.dataset.type);
    });
  });
}

function _demoOpenModal(idx, typeName) {
  const m = document.getElementById('demo-doc-modal');
  if (!m) return;
  const name = (DEMO_DATA.doc_names[idx] || ('doc_' + idx)).replace(/^.*\//, '');
  document.getElementById('demo-doc-modal-title').textContent = name;
  document.getElementById('demo-doc-modal-type').textContent = typeName || '';
  document.getElementById('demo-doc-modal-body').textContent =
    DEMO_DATA.doc_snippets?.[idx] || 'No preview available.';
  m.classList.remove('hidden');
  m.style.display = 'flex';
}

function _demoCloseModal() {
  const m = document.getElementById('demo-doc-modal');
  if (!m) return;
  m.classList.add('hidden');
  m.style.display = 'none';
}

// Close modal on Esc + on backdrop click
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') _demoCloseModal(); });
document.addEventListener('click', (e) => {
  const m = document.getElementById('demo-doc-modal');
  if (m && e.target === m) _demoCloseModal();
});

// Override fetch — catch ALL /api/* calls so the browser never logs a 404.
// Returns a permissive shape that's enough to keep docstruct's code paths happy.
const _origFetch = window.fetch;
window.fetch = function(url, opts) {
  if (typeof url === 'string' && url.includes('/api/')) {
    const u = url;
    // Return the right canned shape per endpoint pattern
    let body = {};
    if (u.includes('/api/settings/llm-keys')) {
      body = { models: [{ id: 'openai/gpt-4o-mini', name: 'GPT-4o mini', provider: 'openai', provider_label: 'OpenAI' }] };
    } else if (u.includes('/api/projects')) {
      body = { projects: [], project_id: 'demo' };
    } else if (u.includes('/api/schema-templates')) {
      body = { templates: [] };
    } else if (u.includes('/discover/progress')) {
      body = { pct: 100, status: 'complete', message: 'Complete', logs: [] };
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(JSON.stringify(body)),
    });
  }
  return _origFetch.call(this, url, opts);
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

  // Quiet auto-firing toasts (e.g. "Discovery complete!" from _showResults).
  // Action-triggered toasts still work — we only suppress noisy navigation
  // events the page would otherwise broadcast on every step transition.
  const _origToast = D.toast.bind(D);
  const _suppress = new Set([
    'Discovery complete!',
    'Discovery complete',
    'Saved',
    'Loading projects...',
  ]);
  D.toast = function(msg, type) {
    if (typeof msg === 'string' && _suppress.has(msg.trim())) return;
    return _origToast(msg, type);
  };

  // Silent no-ops for auto-loaders that hit non-existent endpoints
  ['loadProjects','loadModels','loadTemplates','loadProject','_loadProviders'].forEach(fn => {
    if (typeof D[fn] === 'function') D[fn] = function(){ return Promise.resolve(); };
  });

  // Disable mutation actions with a clear toast (these only fire on click)
  const _disabledMsg = 'Demo only — clone the repo to run lakshana locally.';
  ['saveSchema','exportFormat','exportToStructure','rediscoverSchema','launchPipeline','startPipeline','saveAsTemplate','deleteTemplate','testLLMKey'].forEach(fn => {
    if (typeof D[fn] === 'function') {
      D[fn] = function(){ D.toast(_disabledMsg, 'info'); };
    }
  });

  // Populate the Sample-step document browser from DEMO_DATA, and wire
  // each doc-name to a modal that shows its text. Lets users actually
  // read the corpus before watching the analysis.
  _renderSampleDocBrowser(DEMO_DATA);

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

    # 2. Strip the entire bottom-script block that wires up docstruct's global
    # nav, shortcuts, and API key manager. It's two <script> tags + their
    # init() calls (which span multi-line config objects, so regex over the
    # call alone leaves orphan braces). We delete from the `<!-- Unified nav`
    # comment to the matching closing `</script>` that immediately precedes
    # our DEMO_SCRIPT injection.
    nav_marker = '<!-- Unified nav + shortcuts + API key manager -->'
    if nav_marker in html:
        idx = html.index(nav_marker)
        # find the last </script> before </body>
        end = html.rindex('</script>', idx, html.index('</body>')) + len('</script>')
        html = html[:idx] + html[end:]
    # In case the comment isn't present (older docstruct revisions), also
    # strip any standalone external script includes that we don't ship.
    html = re.sub(
        r'<script[^>]+src="/static/(docstruct-[a-z-]+\.js|keyboard-shortcuts\.js)"[^>]*></script>',
        '',
        html,
    )

    # The lifted step-bar was positioned `top:52px` to clear docstruct's
    # global navbar, which we stripped. Without that nav, it leaves a
    # 52px empty cream gap above the wizard. Anchor it to top:0 instead.
    html = html.replace('#step-bar{position:fixed;top:52px;', '#step-bar{position:fixed;top:0;')

    # Strip auto-init calls that race ahead of our fetch override
    # (e.g. `D.checkApiKey();D.loadProjects();D.loadModels();` at the end
    # of the D <script> block). These hit /api/* before our window.fetch
    # patch lands, producing 404s in the console.
    html = re.sub(
        r'D\.checkApiKey\(\);\s*D\.loadProjects\(\);\s*D\.loadModels\(\);?',
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
