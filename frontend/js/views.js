/* All screen renderers — theme + screens follow the approved wireframe 1:1.
   Pure functions from state to HTML strings; interaction is wired through
   data-act / data-edit attributes handled in main.js. */

import {
  CONFIRM_KEYS, FIELDS, ICON, INSURERS, MINI_FIELDS, POLICY_OPTIONS, STEPS,
} from './constants.js';
import { esc, monthLabel, proj, state } from './state.js';

/* ── Cell helpers (shared with the export payload builder) ───────────── */
export function cellValue(p, col, field) {
  if (field.key === 'type') {
    return (col.data.type && col.data.type.value !== undefined) ? col.data.type.value : p.policyType;
  }
  if (field.key === 'debt') {
    return (col.data.debt && col.data.debt.value !== undefined) ? col.data.debt.value : (col.debt || '');
  }
  const sv = col.data[field.key];
  return sv ? (sv.value || '') : '';
}
function cellPage(col, field) {
  const sv = col.data[field.key];
  return sv && sv.page ? sv.page : null;
}
function cellUncertain(col, field) {
  const sv = col.data[field.key];
  return !!(sv && sv.conf === 'uncertain' && sv.value);
}
function cellBg(p, col, field) {
  if (col.id === p.recommended) return 'var(--rec)';
  if (field.set) return 'var(--set-soft)';
  // Key rows are always tinted: amber until confirmed, green once the
  // broker selects/confirms them — so the selection is visible.
  if (field.confirm) return p.confirmed[field.confirm] ? 'var(--ok-soft)' : 'var(--warn-soft)';
  if (cellUncertain(col, field)) return 'var(--warn-soft)';
  return 'transparent';
}
export function allConfirmed(p) { return CONFIRM_KEYS.every(k => p.confirmed[k]); }
function confirmLabel(k) {
  return { premium: 'Premium', indemnity: 'Indemnity', excess: 'Excess', maxLiability: 'Max liability' }[k];
}

/* ── Step gating (a step must be complete before the next one opens) ── */
export function gateReason(p, screenId) {
  const target = STEPS.findIndex(s => s[0] === screenId);
  if (target <= 0) return null;                       // Setup is always open
  if (!(p.clientName || '').trim()) {
    return 'Complete Setup first — enter the client name.';
  }
  if (target <= 1) return null;                       // Upload needs only Setup
  // Review is reachable once ANY document has been extracted — a quote or
  // a credit-limit schedule both count (a schedule makes no comparison
  // column, so requiring a column here would trap a schedule-only upload).
  // A manually added free-format column also counts.
  const hasUpload = (p.files || []).some(f => f.status === 'extracted');
  if (!hasUpload && !p.columns.length) {
    return 'Upload at least one document first.';
  }
  if (target <= 2) return null;                       // Review is now reachable
  // Credit limits, Recommendation and Generate need a comparison to work
  // on: at least one insurer column, and the expiring policy for a renewal.
  if (p.projectType === 'renewal' && !p.columns.some(c => c.expiring)) {
    return 'Renewal project — upload the expiring policy on the Upload step first (BRD: it is the comparison baseline).';
  }
  if (!p.columns.length) {
    return 'Add at least one insurer quote before continuing — upload a quote, or add a free-format column on the Review step.';
  }
  // The four-value confirmation gate belongs on EXPORT only (BRD 2.5:
  // "Export stays disabled until confirmed"). Credit limits and
  // Recommendation are reachable without it; only Generate needs it — and
  // the server enforces the same gate on the export request.
  if (screenId === 'export' && !allConfirmed(p)) {
    return 'Confirm the four key values on the Review step before generating — estimated annual premium, indemnity, excess and max annual liability.';
  }
  return null;
}

/* ── Shared fragments ────────────────────────────────────────────────── */
function screenHeader(title, sub) {
  return `
    <h1 style="font-size:26px;margin:0 0 6px;font-weight:700;letter-spacing:-.4px">${title}</h1>
    <p style="color:var(--ink2);font-size:13.5px;margin:0 0 24px">${sub}</p>`;
}

function navFooter(backScreen, nextLabel, nextScreen) {
  return `
    <div style="display:flex;justify-content:space-between;gap:10px;margin-top:22px">
      <button class="btn btn-secondary" data-act="go" data-arg="${backScreen}">← Back</button>
      <button class="btn btn-primary" data-act="go" data-arg="${nextScreen}">${nextLabel} →</button>
    </div>`;
}

function removeX(colId, title) {
  return `<span data-act="removeColumn" data-arg="${colId}" title="${title}" style="flex:none;cursor:pointer;color:var(--ink3);font-size:15px;line-height:1">×</span>`;
}

/* ═══════════════════════════ RENDERERS ═════════════════════════════ */

let lastScreen = null;

export function render() {
  const app = document.getElementById('app');
  // The entrance fade must play only on a real screen change — otherwise it
  // replays on every in-place re-render (a confirm click, a cell edit) and
  // the whole content area blinks.
  const animate = state.screen !== lastScreen;
  let html = '';
  if (state.screen === 'login') {
    html = renderLogin();
  } else {
    html = '<div style="height:100vh;display:flex;flex-direction:column;overflow:hidden">'
      + renderTopbar()
      + (state.screen === 'projects' ? renderProjects(animate) : renderWizard(animate))
      + '</div>';
  }
  html += renderSourceModal();
  html += renderNotice();
  app.innerHTML = html;
  lastScreen = state.screen;
}

/* Themed replacement for the browser's alert() — matches the app font
   and colours instead of the plain grey browser dialog. */
export function notify(message) {
  state.notice = message;
  render();
}

function renderNotice() {
  if (!state.notice) return '';
  return `
  <div class="modal-overlay" data-act="dismissNotice">
    <div data-act="modalCard" style="width:420px;max-width:calc(100% - 40px);background:var(--surface);border-radius:14px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.3)">
      <div style="padding:22px 24px 6px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
          <div class="logo-mark" style="width:26px;height:26px;font-size:13px;border-radius:7px">U</div>
          <span style="font-weight:600;font-size:14px">UK Insurance</span>
        </div>
        <div style="font-size:13.5px;line-height:1.6;color:var(--ink2)">${esc(state.notice).replace(/\n/g, '<br>')}</div>
      </div>
      <div style="display:flex;justify-content:flex-end;padding:14px 20px 18px">
        <button class="btn btn-primary" data-act="dismissNotice" style="padding:9px 24px">OK</button>
      </div>
    </div>
  </div>`;
}

/* ── S1 Login ──────────────────────────────────────────────────────── */
function renderLogin() {
  return `
  <div class="login-grid">
    <div class="login-hero">
      <div style="display:flex;align-items:center;gap:12px">
        <div class="logo-mark" style="width:34px;height:34px;font-size:17px">U</div>
        <span style="font-weight:600;letter-spacing:.2px">UK Insurance</span>
      </div>
      <div style="max-width:440px">
        <div class="mono" style="font-size:13px;font-weight:500;color:#8fa2c9;letter-spacing:1px;text-transform:uppercase;margin-bottom:18px">Internal tool</div>
        <h1 style="font-size:42px;line-height:1.08;margin:0 0 18px;font-weight:700;letter-spacing:-.9px">Turn insurer quotes into a client comparison in under five minutes.</h1>
        <p style="color:#b9c4d6;font-size:15px;line-height:1.6;margin:0">Upload the quotes, review the extracted terms, pick your recommendation, and generate the presentation — proofread and send.</p>
      </div>
    </div>
    <div style="display:grid;place-items:center;padding:40px">
      <div style="width:100%;max-width:340px">
        <h2 style="font-size:22px;margin:0 0 6px;font-weight:600">Sign in</h2>
        <p style="color:var(--ink2);font-size:13.5px;margin:0 0 28px">Use your brokerage email account.</p>
        <label class="field-label">Email</label>
        <input id="login-email" class="input" style="padding:11px 13px;margin-bottom:16px" placeholder="broker@ukcib.co.uk">
        <label class="field-label">Password</label>
        <input id="login-pass" type="password" class="input" style="padding:11px 13px;margin-bottom:22px">
        <button class="btn btn-primary" style="width:100%;padding:12px;font-size:14.5px" data-act="signIn">Sign in</button>
        <p style="text-align:center;color:var(--ink3);font-size:12px;margin:22px 0 0">No self-registration. Accounts are provisioned by the administrator.</p>
      </div>
    </div>
  </div>`;
}

/* ── Topbar ────────────────────────────────────────────────────────── */
function renderTopbar() {
  const p = proj();
  const inWizard = state.screen !== 'projects' && p;
  const u = state.user || { email: '', initials: 'AB' };
  const name = u.email ? u.email.split('@')[0] : 'Broker';
  return `
  <header class="topbar">
    <div style="display:flex;align-items:center;gap:26px">
      <div data-act="toProjects" style="display:flex;align-items:center;gap:10px;cursor:pointer">
        <div class="logo-mark" style="width:28px;height:28px;font-size:14px;border-radius:7px">U</div>
        <span style="font-weight:600;font-size:15px">UK Insurance</span>
      </div>
      ${inWizard ? `
      <div style="display:flex;align-items:center;gap:9px;font-size:13px;color:var(--ink2)">
        <span data-act="toProjects" style="cursor:pointer">Projects</span>
        <span style="color:var(--ink3)">/</span>
        <span style="color:var(--ink);font-weight:500">${esc(p.clientName || 'New project')}</span>
        <span class="mono" style="font-size:11px;font-weight:500;color:var(--ink2);background:var(--panel);border:1px solid var(--line);padding:2px 7px;border-radius:5px">${esc(p.ref)}</span>
      </div>` : ''}
    </div>
    <div style="display:flex;align-items:center;gap:14px">
      <div style="text-align:right;line-height:1.2">
        <div style="font-size:13px;font-weight:500">${esc(name)}</div>
        <div style="font-size:11px;color:var(--ink3)">Underwriting desk</div>
      </div>
      <div style="position:relative">
        <div data-act="userMenu" title="Account" style="width:32px;height:32px;border-radius:50%;background:var(--set-soft);color:var(--set);display:grid;place-items:center;font-weight:600;font-size:13px;cursor:pointer">${esc(u.initials)}</div>
        ${state.userMenu ? `
        <div style="position:absolute;top:40px;right:0;background:var(--surface);border:1px solid var(--line);border-radius:10px;box-shadow:0 10px 28px rgba(15,23,41,.14);min-width:210px;z-index:60;overflow:hidden">
          <div style="padding:12px 14px;border-bottom:1px solid var(--line2)">
            <div style="font-size:13px;font-weight:600">${esc(name)}</div>
            <div style="font-size:12px;color:var(--ink3)">${esc(u.email)}</div>
          </div>
          <div data-act="signOut" style="padding:11px 14px;font-size:13px;font-weight:500;color:var(--warn);cursor:pointer">Sign out</div>
        </div>` : ''}
      </div>
    </div>
  </header>`;
}

/* ── S2 Projects ───────────────────────────────────────────────────── */
export function projectRowsHtml() {
  const q = state.projSearch.toLowerCase();
  const typeLabelOf = p => p.projectType === 'renewal' ? 'Renewal' : 'New business';
  const list = state.projects.filter(p =>
    (!q || (p.clientName || '').toLowerCase().includes(q)) &&
    (state.projFilter === 'All' || typeLabelOf(p) === state.projFilter));
  if (!list.length) {
    return `<div style="padding:40px;text-align:center;color:var(--ink3);font-size:13.5px">
      No projects${q || state.projFilter !== 'All' ? ' match' : ' yet — start one with “New project”'}.</div>`;
  }
  const stMap = { ready: ['var(--accent-soft)', 'var(--accent)', 'Ready'], draft: ['#eef1f5', 'var(--ink2)', 'Draft'], sent: ['var(--ok-soft)', 'var(--ok)', 'Sent'] };
  return list.map(p => {
    const [bg, fg, label] = stMap[p.status] || stMap.draft;
    return `
    <div data-act="openProject" data-arg="${p.id}" style="display:grid;grid-template-columns:2.2fr 1fr 1.1fr 1.4fr 1fr 0.9fr;align-items:center;padding:15px 18px;border-bottom:1px solid var(--line2);cursor:pointer;font-size:13.5px">
      <div>
        <div style="font-weight:600">${esc(p.clientName || 'Untitled')}</div>
        <div class="mono" style="font-size:11.5px;color:var(--ink3)">${esc(p.ref)}</div>
      </div>
      <span style="color:var(--ink2)">${typeLabelOf(p)}</span>
      <span style="color:var(--ink2)">${esc(p.policyType)}</span>
      <span><span style="display:inline-block;font-size:12px;font-weight:500;padding:3px 10px;border-radius:20px;background:${bg};color:${fg}">${label}</span></span>
      <span style="color:var(--ink2);font-size:12.5px">${esc(p.updated)}</span>
      <span class="mono" style="text-align:right;color:var(--ink3);font-size:11px;font-weight:500">${p.exported
        ? `<a data-act="noopLink" href="/projects/${p.id}/exports/pptx" style="color:var(--accent);text-decoration:none">PPT</a> · <a data-act="noopLink" href="/projects/${p.id}/exports/pdf" style="color:var(--accent);text-decoration:none">PDF</a>`
        : '—'}</span>
    </div>`;
  }).join('');
}

function renderProjects(animate) {
  const filters = ['All', 'New business', 'Renewal'].map(f => `
    <span data-act="setFilter" data-arg="${f}" style="font-size:12.5px;padding:9px 13px;background:var(--surface);border:1px solid var(--line);border-radius:9px;cursor:pointer;color:${state.projFilter === f ? 'var(--ink)' : 'var(--ink2)'};font-weight:${state.projFilter === f ? '500' : '400'}">${f}</span>`).join('');
  return `
  <main class="${animate ? 'fade' : ''}" style="flex:1;min-height:0;overflow:auto;padding:34px 26px 60px"><div style="max-width:1100px;width:100%;margin:0 auto">
    <div style="display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:22px">
      <div>
        <h1 style="font-size:27px;margin:0 0 6px;font-weight:700;letter-spacing:-.5px">Projects</h1>
        <p style="color:var(--ink2);font-size:13.5px;margin:0">Client comparisons prepared on this desk.</p>
      </div>
      <button class="btn btn-primary" style="padding:10px 16px" data-act="newProject">${ICON.plus}New project</button>
    </div>
    <div style="display:flex;gap:10px;margin-bottom:16px">
      <div style="flex:1;display:flex;align-items:center;gap:9px;background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:9px 13px">
        <span style="color:var(--ink3);display:flex">${ICON.search}</span>
        <input id="proj-search" data-edit="search" placeholder="Search by client name" value="${esc(state.projSearch)}" style="border:none;background:none;font-size:13.5px;color:var(--ink);width:100%">
      </div>
      <div style="display:flex;gap:6px">${filters}</div>
    </div>
    <div class="card" style="overflow:hidden">
      <div style="display:grid;grid-template-columns:2.2fr 1fr 1.1fr 1.4fr 1fr 0.9fr;padding:12px 18px;border-bottom:1px solid var(--line);font:500 11px 'IBM Plex Mono';letter-spacing:.5px;text-transform:uppercase;color:var(--ink3);background:var(--panel)">
        <span>Client</span><span>Type</span><span>Policy</span><span>Status</span><span>Updated</span><span style="text-align:right">Files</span>
      </div>
      <div id="proj-rows">${projectRowsHtml()}</div>
    </div>
  </div></main>`;
}

/* ── Stepper + wizard shell ────────────────────────────────────────── */
function renderStepper(p) {
  const cur = STEPS.findIndex(s => s[0] === state.screen);
  return `
  <div style="background:var(--surface);border-bottom:1px solid var(--line);padding:20px 26px">
    <div style="max-width:960px;margin:0 auto;display:flex;align-items:center;overflow-x:auto">
      ${STEPS.map(([id, label], i) => {
        const st = i < cur ? 'done' : i === cur ? 'current' : 'todo';
        const locked = i > cur && gateReason(p, id);
        const numBg = st === 'current' ? 'var(--accent)' : st === 'done' ? 'var(--accent-soft)' : '#fff';
        const numFg = st === 'current' ? '#fff' : st === 'done' ? 'var(--accent)' : 'var(--ink3)';
        const numBorder = st === 'current' ? 'var(--accent)' : st === 'done' ? 'var(--accent-soft)' : 'var(--line)';
        const shadow = st === 'current' ? '0 2px 8px rgba(79,70,229,.4)' : 'none';
        return (i > 0 ? `<span style="flex:1;min-width:16px;height:2px;background:${i <= cur ? 'var(--accent)' : 'var(--line)'};margin:0 10px"></span>` : '')
        + `<div data-act="go" data-arg="${id}" ${locked ? `title="${esc(locked)}"` : ''} style="display:flex;align-items:center;gap:9px;cursor:${locked ? 'not-allowed' : 'pointer'};flex:none;white-space:nowrap;opacity:${locked ? '.45' : '1'}">
            <span style="width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-size:12.5px;font-weight:700;background:${numBg};color:${numFg};border:1.5px solid ${numBorder};box-shadow:${shadow}">${st === 'done' ? '✓' : i + 1}</span>
            <span style="font-size:12.5px;font-weight:${st === 'current' ? 700 : 500};color:${st === 'todo' ? 'var(--ink3)' : 'var(--ink)'}">${label}</span>
          </div>`;
      }).join('')}
    </div>
  </div>`;
}

function renderWizard(animate) {
  const p = proj();
  if (!p) { state.screen = 'projects'; return renderProjects(animate); }
  const inner = {
    setup: renderSetup, upload: renderUpload, review: renderReview,
    limits: renderLimits, recommend: renderRecommend, export: renderExport,
  }[state.screen] || renderSetup;
  return `
  <div style="flex:1;min-height:0;display:flex;flex-direction:column">
    ${renderStepper(p)}
    <main style="flex:1;min-height:0;overflow:auto">
      <div class="${animate ? 'fade' : ''}" style="max-width:1180px;margin:0 auto;padding:30px 26px 40px">${inner(p)}</div>
    </main>
  </div>`;
}

/* ── S3 Setup ──────────────────────────────────────────────────────── */
function renderSetup(p) {
  const isRen = p.projectType === 'renewal';
  const typeCard = (id, on, title, sub) => `
    <div data-act="setType" data-arg="${id}" style="flex:1;padding:14px 16px;border:1.5px solid ${on ? 'var(--accent)' : 'var(--line)'};background:${on ? 'var(--accent-soft)' : '#fff'};border-radius:10px;cursor:pointer">
      <div style="font-weight:600;font-size:14px;margin-bottom:2px">${title}</div>
      <div style="font-size:12px;color:var(--ink2)">${sub}</div>
    </div>`;
  return `
  <div>
    ${screenHeader('New project', 'Set up the client and choose which insurers were approached.')}
    <div style="display:grid;grid-template-columns:1.35fr 1fr;gap:20px;align-items:start">
      <div class="card" style="padding:26px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:24px">
          <div>
            <label class="field-label">Client name</label>
            <input class="input" data-edit="proj" data-part="clientName" value="${esc(p.clientName)}" placeholder="e.g. Aldgate Timber Ltd">
          </div>
          <div>
            <label class="field-label">Reference</label>
            <input class="input mono" data-edit="proj" data-part="ref" value="${esc(p.ref)}">
          </div>
        </div>
        <label class="field-label" style="margin-bottom:8px">Project type</label>
        <div style="display:flex;gap:10px;margin-bottom:${isRen ? '18px' : '24px'}">
          ${typeCard('new', !isRen, 'New business', 'Front page: “Credit Insurance Presentation”')}
          ${typeCard('renewal', isRen, 'Renewal', 'Compares against the expiring policy')}
        </div>
        ${isRen ? `<p style="font-size:12.5px;color:var(--warn);background:var(--warn-soft);border-radius:7px;padding:9px 12px;margin:0 0 24px">Renewal selected — the expiring policy must be uploaded on the next step as the comparison baseline.</p>` : ''}
        <label class="field-label" style="margin-bottom:8px">Policy type <span style="color:var(--ink3);font-weight:400">— applies to every insurer column, overridable at review</span></label>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px">
          ${POLICY_OPTIONS.map(opt => {
            const on = p.policyType === opt;
            return `<div data-act="setPolicy" data-arg="${opt}" style="text-align:center;padding:11px 8px;border:1.5px solid ${on ? 'var(--accent)' : 'var(--line)'};background:${on ? 'var(--accent-soft)' : '#fff'};border-radius:9px;cursor:pointer;font-size:13px;font-weight:${on ? 600 : 500};color:${on ? 'var(--accent)' : 'var(--ink2)'}">${opt}</div>`;
          }).join('')}
        </div>
      </div>
      <div class="card" style="padding:26px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px">
          <label style="font-size:12.5px;font-weight:500;color:var(--ink2);white-space:nowrap">Insurers approached</label>
          <span class="mono" style="font-size:11px;font-weight:500;color:var(--accent);background:var(--accent-soft);padding:2px 8px;border-radius:5px;white-space:nowrap;flex:none">${p.approached.length} of 10</span>
        </div>
        <p style="font-size:12px;color:var(--ink3);margin:0 0 14px">From the standing list — up to 10. Ticked insurers with no quote uploaded show as declined on the presentation.</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          ${INSURERS.map(a => {
            const on = p.approached.includes(a.id);
            return `<div data-act="toggleApproach" data-arg="${a.id}" style="display:flex;align-items:center;gap:10px;padding:11px 13px;border:1px solid ${on ? 'var(--accent)' : 'var(--line)'};background:${on ? 'var(--accent-soft)' : '#fff'};border-radius:9px;cursor:pointer">
              <span style="width:18px;height:18px;border-radius:5px;border:1.5px solid ${on ? 'var(--accent)' : '#c5cdd8'};background:${on ? 'var(--accent)' : '#fff'};display:grid;place-items:center;color:#fff;font-size:11px;font-weight:700;flex:none">${on ? '✓' : ''}</span>
              <span style="font-size:13.5px;font-weight:500">${a.name}</span>
              ${a.debtIncl ? `<span class="mono" style="margin-left:auto;font-size:10px;font-weight:500;color:var(--set);background:var(--set-soft);padding:2px 6px;border-radius:4px">DEBT INCL</span>` : ''}
            </div>`;
          }).join('')}
        </div>
      </div>
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:20px">
      <button class="btn btn-secondary" data-act="toProjects">Cancel</button>
      <button class="btn btn-primary" data-act="go" data-arg="upload">Continue to upload →</button>
    </div>
  </div>`;
}

/* ── S4 Upload ─────────────────────────────────────────────────────── */
function renderUpload(p) {
  const isRen = p.projectType === 'renewal';
  const stMap = {
    extracted: ['var(--ok-soft)', 'var(--ok)', '●', 'Extracted'],
    processing: ['#eef1f5', 'var(--ink2)', '<span class="spin"></span>', 'Processing'],
    error: ['var(--warn-soft)', 'var(--warn)', '▲', 'Unreadable'],
  };
  const nErr = p.files.filter(f => f.status === 'error').length;
  const filesHtml = p.files.length ? p.files.map(f => {
    const [bg, fg, dot, label] = stMap[f.status] || stMap.processing;
    return `
    <div style="display:flex;align-items:center;gap:14px;padding:13px 18px;border-bottom:1px solid var(--line2)">
      <div class="mono" style="width:32px;height:38px;border-radius:5px;background:var(--panel);border:1px solid var(--line);display:grid;place-items:center;font-size:9px;font-weight:500;color:var(--ink3);flex:none">${esc(f.ext)}</div>
      <div style="flex:1;min-width:0">
        <div style="font-size:13.5px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(f.name)}</div>
        <div style="font-size:11.5px;color:var(--ink3)">${esc(f.meta)}</div>
      </div>
      <span class="status-pill" style="background:${bg};color:${fg}">${dot} ${label}</span>
    </div>`;
  }).join('')
  : `<div style="padding:34px;text-align:center;color:var(--ink3);font-size:13px">No documents yet — upload the quotes above.</div>`;

  return `
  <div style="max-width:900px">
    ${screenHeader('Upload documents', 'Add quotes as they arrive — uploads are cumulative and the comparison refreshes each time.')}
    <input type="file" id="file-quote" accept="application/pdf" multiple hidden>
    <input type="file" id="file-limits" accept="application/pdf,.xlsx,.xls" multiple hidden>
    <input type="file" id="file-expiring" accept="application/pdf" hidden>
    <div style="display:grid;grid-template-columns:${isRen ? '1fr 1fr 1fr' : '1fr 1fr'};gap:16px;margin-bottom:24px">
      <div data-drop="quote" style="border:1.5px dashed var(--line);border-radius:12px;padding:24px 18px;text-align:center;background:var(--surface)">
        <div style="width:38px;height:38px;border-radius:9px;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;margin:0 auto 12px;pointer-events:none">${ICON.upload}</div>
        <div style="font-weight:600;font-size:14px;margin-bottom:3px;pointer-events:none">Quotes</div>
        <div style="font-size:12px;color:var(--ink2);margin-bottom:14px;pointer-events:none">PDF, incl. scanned. Up to 6.</div>
        <button class="btn-soft" data-act="pickFile" data-arg="file-quote">Choose files</button>
      </div>
      <div data-drop="limits" style="border:1.5px dashed var(--line);border-radius:12px;padding:24px 18px;text-align:center;background:var(--surface)">
        <div style="width:38px;height:38px;border-radius:9px;background:var(--panel);color:var(--ink2);display:grid;place-items:center;margin:0 auto 12px;pointer-events:none">${ICON.table}</div>
        <div style="font-weight:600;font-size:14px;margin-bottom:3px;pointer-events:none">Credit-limit docs</div>
        <div style="font-size:12px;color:var(--ink2);margin-bottom:14px;pointer-events:none">PDF or Excel. Optional.</div>
        <button data-act="pickFile" data-arg="file-limits" style="font-size:12.5px;font-weight:600;color:var(--ink2);background:var(--panel);border:1px solid var(--line);padding:8px 14px;border-radius:7px;cursor:pointer">Choose files</button>
      </div>
      ${isRen ? `
      <div data-drop="expiring" style="border:1.5px dashed var(--warn);border-radius:12px;padding:24px 18px;text-align:center;background:var(--warn-soft)">
        <div style="width:38px;height:38px;border-radius:9px;background:#fff;color:var(--warn);display:grid;place-items:center;margin:0 auto 12px;pointer-events:none">${ICON.refresh}</div>
        <div style="font-weight:600;font-size:14px;margin-bottom:3px;pointer-events:none">Expiring policy</div>
        <div style="font-size:12px;color:var(--warn);margin-bottom:14px;pointer-events:none">Required for renewal.</div>
        <button data-act="pickFile" data-arg="file-expiring" style="font-size:12.5px;font-weight:600;color:var(--warn);background:#fff;border:1px solid var(--warn);padding:8px 14px;border-radius:7px;cursor:pointer">Choose file</button>
      </div>` : ''}
    </div>
    <div class="card" style="overflow:hidden">
      <div style="padding:13px 18px;border-bottom:1px solid var(--line);font-weight:600;font-size:13.5px;display:flex;justify-content:space-between;align-items:center">
        <span>Documents</span>
        <span class="mono" style="font-size:11px;font-weight:500;color:var(--ink3)">${p.files.length} file${p.files.length === 1 ? '' : 's'}${nErr ? ' · ' + nErr + ' unreadable' : ''}</span>
      </div>
      ${filesHtml}
    </div>
    <p style="font-size:12.5px;color:var(--ink2);margin:14px 2px 0">An unreadable document is flagged individually — the project continues with that insurer’s column blank.</p>
    ${navFooter('setup', 'Review comparison', 'review')}
  </div>`;
}

/* ── S5 Review ─────────────────────────────────────────────────────── */
function renderReview(p) {
  const done = allConfirmed(p);
  const nLeft = CONFIRM_KEYS.filter(k => !p.confirmed[k]).length;
  const chips = CONFIRM_KEYS.map(k => {
    const on = p.confirmed[k];
    return `<span data-act="toggleConfirm" data-arg="${k}" style="display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:500;padding:5px 11px;border-radius:20px;border:1px solid ${on ? 'var(--ok)' : 'var(--line)'};background:${on ? 'var(--ok-soft)' : '#fff'};color:${on ? 'var(--ok)' : 'var(--ink2)'};cursor:pointer">${on ? '✓' : '○'} ${confirmLabel(k)}</span>`;
  }).join('');

  const headCells = p.columns.map(col => {
    const isRec = col.id === p.recommended;
    return `
    <th style="padding:11px 14px;background:${isRec ? 'var(--rec)' : 'var(--panel)'};border-bottom:1px solid var(--line);border-left:1px solid var(--line2);min-width:150px;text-align:left">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <input class="head-input" data-edit="colname" data-col="${col.id}" value="${esc(col.name)}" style="color:${isRec ? 'var(--accent)' : 'var(--ink)'}">
        <div style="display:flex;align-items:center;gap:6px;flex:none">
          ${removeX(col.id, col.manual ? 'Remove column' : 'Remove this column and its uploaded file (re-upload to restore)')}
          <span data-act="pickRec" data-arg="${col.id}" class="mono" style="font-size:10px;font-weight:500;padding:3px 7px;border-radius:5px;cursor:pointer;background:${isRec ? 'var(--accent)' : '#fff'};color:${isRec ? '#fff' : 'var(--ink3)'};border:1px solid ${isRec ? 'var(--accent)' : 'var(--line)'}">${isRec ? '★ REC' : 'Set rec'}</span>
        </div>
      </div>
      ${col.manual ? `<span class="mono" style="display:inline-block;margin-top:5px;font-size:9px;font-weight:500;color:var(--warn);background:var(--warn-soft);padding:2px 6px;border-radius:4px">FREE FORMAT</span>` : ''}
    </th>`;
  }).join('');

  const bodyRows = FIELDS.map(f => {
    // Key-value rows are clickable: selecting the row confirms it in the
    // panel above (same state as the chips, so both stay in sync).
    const isKey = !!f.confirm;
    const keyOn = isKey && p.confirmed[f.confirm];
    return `
    <tr>
      <th ${isKey ? `data-act="toggleConfirm" data-arg="${f.confirm}" title="Click to ${keyOn ? 'un-confirm' : 'confirm'} this key value"` : ''} style="text-align:left;padding:11px 16px;border-bottom:1px solid var(--line2);background:${keyOn ? 'var(--ok-soft)' : 'var(--surface)'};position:sticky;left:0;z-index:1;vertical-align:top${isKey ? ';cursor:pointer;user-select:none' : ''}">
        <div style="display:flex;align-items:center;gap:7px">
          <span style="font-size:13px;font-weight:500;color:var(--ink)">${f.label}</span>
          ${f.tag ? `<span class="mono" style="font-size:9px;font-weight:500;padding:2px 6px;border-radius:4px;background:var(--set-soft);color:var(--set)">${f.tag}</span>` : ''}
        </div>
        ${f.note ? `<div style="font-size:11px;color:var(--ink3);margin-top:2px">${f.note}</div>` : ''}
      </th>
      ${p.columns.map(col => {
        const page = cellPage(col, f);
        return `
        <td style="padding:0;border-bottom:1px solid var(--line2);border-left:1px solid var(--line2);background:${cellBg(p, col, f)};vertical-align:middle">
          <div style="display:flex;align-items:center;gap:6px;padding:4px 8px">
            <input class="cell-input" data-edit="cell" data-col="${col.id}" data-field="${f.key}" value="${esc(cellValue(p, col, f))}" placeholder="—">
            ${cellUncertain(col, f) ? `<span class="mono" title="AI marked this value uncertain — verify against the source page (editing the cell clears the flag)" style="flex:none;font-size:10px;font-weight:500;color:var(--warn);background:#fff;border:1px solid var(--warn);border-radius:4px;padding:1px 5px;cursor:help">?</span>` : ''}
            ${page ? `<button class="src-chip" data-act="openSource" data-arg="${col.id}" data-arg2="${page}" title="Open source page">p${page}</button>` : ''}
          </div>
        </td>`;
      }).join('')}
    </tr>`;
  }).join('');

  return `
  <div>
    <div style="display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:6px">
      <div>
        <h1 style="font-size:26px;margin:0 0 6px;font-weight:700;letter-spacing:-.4px">Review &amp; edit</h1>
        <p style="color:var(--ink2);font-size:13.5px;margin:0">Same shape as the presentation slide, pre-populated. Every cell is editable.</p>
      </div>
      <div style="display:flex;gap:16px;font-size:11.5px;color:var(--ink2);align-items:center">
        <span style="display:flex;align-items:center;gap:6px"><span style="width:11px;height:11px;border-radius:3px;background:var(--set-soft);border:1px solid var(--set)"></span>Set field</span>
        <span style="display:flex;align-items:center;gap:6px"><span style="width:11px;height:11px;border-radius:3px;background:var(--warn-soft);border:1px solid var(--warn)"></span>Confirm before export</span>
        <span style="display:flex;align-items:center;gap:6px"><span style="width:11px;height:11px;border-radius:3px;background:var(--ok-soft);border:1px solid var(--ok)"></span>Confirmed</span>
        <span style="display:flex;align-items:center;gap:6px"><span style="width:11px;height:11px;border-radius:3px;background:var(--rec);border:1px solid var(--accent)"></span>Recommended</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:14px;background:${done ? 'var(--ok-soft)' : 'var(--warn-soft)'};border:1px solid ${done ? 'var(--ok)' : 'var(--warn)'};border-radius:10px;padding:11px 16px;margin:16px 0 14px">
      <span style="font-size:13px;font-weight:600;color:${done ? 'var(--ok)' : 'var(--warn)'}">${done ? '✓ All four key values confirmed — export enabled.' : '⚠ Confirm ' + nLeft + ' of 4 key values before export'}</span>
      <div style="display:flex;gap:8px;margin-left:auto">${chips}</div>
    </div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
      <span style="font-size:12.5px;color:var(--ink2)">${p.columns.length} comparison column${p.columns.length === 1 ? '' : 's'} — one per quote. Add a free-format column for a second quote from the same insurer or terms agreed offline.</span>
      <button class="btn-soft" style="flex:none" data-act="addColumn">${ICON.plus}Add comparison column</button>
    </div>
    <div class="card" style="overflow:hidden;overflow-x:auto">
      ${p.columns.length ? `
      <table class="grid-table">
        <thead><tr><th class="colhead-label">Field</th>${headCells}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>`
      : `<div style="padding:40px;text-align:center;color:var(--ink3);font-size:13.5px">No comparison columns yet — upload quotes on the previous step, or add a free-format column.</div>`}
    </div>
    <div class="card" style="margin-top:16px;padding:16px 18px">
      <label style="display:block;font-size:12.5px;font-weight:600;color:var(--ink2);margin-bottom:8px">Free-format notes <span style="color:var(--ink3);font-weight:400">— appears beneath the comparison</span></label>
      <textarea class="textarea" data-edit="notes" style="min-height:64px;line-height:1.5">${esc(p.notes)}</textarea>
    </div>
    ${navFooter('upload', 'Credit limits', 'limits')}
  </div>`;
}

/* Mirrors the server's Total row: sum of the parseable amounts. */
function moneyTotal(vals) {
  let total = 0, found = false;
  for (const v of vals) {
    const digits = String(v || '').replace(/[^\d]/g, '');
    if (digits) { total += parseInt(digits, 10); found = true; }
  }
  return found ? '£' + total.toLocaleString('en-GB') : '';
}

/* ── S6 Credit limits ──────────────────────────────────────────────── */
function renderLimits(p) {
  const th = (txt, extra) => `<th style="text-align:left;padding:12px 14px;font:500 11px 'IBM Plex Mono';letter-spacing:.4px;text-transform:uppercase;color:var(--ink3);background:var(--panel);border-bottom:1px solid var(--line);${extra || ''}">${txt}</th>`;
  // Wide enough that names and limits never truncate; the card scrolls
  // horizontally when columns outgrow it.
  const tableMin = 470 + p.columns.length * 130;
  const rows = p.credit.map(r => `
    <tr>
      <td style="padding:2px 8px;border-bottom:1px solid var(--line2)"><input class="cell-input" style="font-weight:500;padding:8px 6px" data-edit="credit" data-row="${r.id}" data-part="buyer" value="${esc(r.buyer)}" placeholder="Buyer name"></td>
      <td style="padding:2px 6px;border-bottom:1px solid var(--line2)"><input class="cell-input mono" style="font-size:12.5px;color:var(--ink2);padding:8px 6px" data-edit="credit" data-row="${r.id}" data-part="reg" value="${esc(r.reg)}" placeholder="—"></td>
      <td style="padding:2px 6px;border-bottom:1px solid var(--line2)"><input class="cell-input" style="padding:8px 6px" data-edit="credit" data-row="${r.id}" data-part="req" value="${esc(r.req)}" placeholder="—"></td>
      ${p.columns.map(col => {
        const v = r.offers[col.id] || '';
        return `<td style="padding:2px 6px;border-bottom:1px solid var(--line2);border-left:1px solid var(--line2);background:${col.id === p.recommended ? 'var(--rec)' : 'transparent'}">
          <input class="cell-input" style="padding:8px 6px" data-edit="credit" data-row="${r.id}" data-part="offer" data-col="${col.id}" value="${esc(v)}" placeholder="—">
        </td>`;
      }).join('')}
      <td style="text-align:center;border-bottom:1px solid var(--line2)"><span data-act="removeCredit" data-arg="${r.id}" title="Remove buyer row" style="color:var(--ink3);cursor:pointer;font-size:16px">×</span></td>
    </tr>`).join('');
  // The sample deck's Total row — computed, read-only, same as the export.
  const totalRow = p.credit.length ? `
    <tr style="background:var(--panel);font-weight:600">
      <td style="padding:10px 14px;border-top:1px solid var(--line)">Total</td>
      <td style="border-top:1px solid var(--line)"></td>
      <td style="padding:10px 6px;border-top:1px solid var(--line)">${esc(moneyTotal(p.credit.map(r => r.req)))}</td>
      ${p.columns.map(col => `<td style="padding:10px 6px;border-top:1px solid var(--line);border-left:1px solid var(--line2);background:${col.id === p.recommended ? 'var(--rec)' : 'transparent'}">${esc(moneyTotal(p.credit.map(r => r.offers[col.id])))}</td>`).join('')}
      <td style="border-top:1px solid var(--line)"></td>
    </tr>` : '';
  return `
  <div>
    <div style="display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:18px">
      <div>
        <h1 style="font-size:26px;margin:0 0 6px;font-weight:700;letter-spacing:-.4px">Buyer credit limits</h1>
        <p style="color:var(--ink2);font-size:13.5px;margin:0">Fully editable — add rows for facilities agreed offline that appear in no document.</p>
      </div>
      <button class="btn-soft" style="padding:9px 15px;flex:none" data-act="addCredit">${ICON.plus}Add buyer</button>
    </div>
    <div class="card" style="overflow:hidden;overflow-x:auto">
      <table class="grid-table" style="min-width:${tableMin}px">
        <thead><tr>
          ${th('Buyer', 'padding:12px 16px;min-width:170px;')}${th('Company no.', 'min-width:120px;')}${th('Required', 'min-width:120px;')}
          ${p.columns.map(col => {
            const isRec = col.id === p.recommended;
            return `<th style="text-align:left;padding:12px 14px;min-width:130px;background:${isRec ? 'var(--rec)' : 'var(--panel)'};border-bottom:1px solid var(--line);border-left:1px solid var(--line2)">
              <div style="display:flex;align-items:center;gap:7px">
                <span style="font-size:13px;font-weight:600;color:${isRec ? 'var(--accent)' : 'var(--ink)'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(col.name)}</span>
                ${removeX(col.id, 'Remove this column (also removes it from the comparison)')}
              </div>
              ${col.manual ? `<span class="mono" style="display:inline-block;margin-top:4px;font-size:9px;font-weight:500;color:var(--warn);background:var(--warn-soft);padding:2px 6px;border-radius:4px">FREE FORMAT</span>` : ''}
            </th>`;
          }).join('')}
          <th style="background:var(--panel);border-bottom:1px solid var(--line);width:40px"></th>
        </tr></thead>
        <tbody>${rows ? rows + totalRow : `<tr><td colspan="${4 + p.columns.length}" style="padding:34px;text-align:center;color:var(--ink3);font-size:13px">No buyer limits — extracted rows appear here, or add one manually.</td></tr>`}</tbody>
      </table>
    </div>
    <p style="font-size:12.5px;color:var(--ink2);margin:14px 2px 0">Around 90% of limits arrive as a separate schedule. This page is omitted cleanly from the presentation when no limits are supplied.</p>
    ${navFooter('review', 'Recommendation', 'recommend')}
  </div>`;
}

/* ── S7 Recommendation ─────────────────────────────────────────────── */
function renderRecommend(p) {
  const cards = p.columns.map(col => {
    const isRec = col.id === p.recommended;
    const prem = (col.data.estimated_annual_premium_exc_ipt || {}).value || '—';
    const ind = (col.data.indemnity || {}).value || '—';
    return `
    <div data-act="pickRec" data-arg="${col.id}" style="border:1.5px solid ${isRec ? 'var(--accent)' : 'var(--line)'};background:${isRec ? 'var(--accent-soft)' : 'var(--surface)'};border-radius:11px;padding:16px;cursor:pointer;display:flex;align-items:center;gap:12px">
      <span style="width:20px;height:20px;border-radius:50%;border:2px solid ${isRec ? 'var(--accent)' : '#c5cdd8'};background:${isRec ? 'var(--accent)' : '#fff'};display:grid;place-items:center;flex:none"><span style="width:8px;height:8px;border-radius:50%;background:${isRec ? '#fff' : 'transparent'}"></span></span>
      <div>
        <div style="font-weight:600;font-size:14.5px">${esc(col.name)}</div>
        <div style="font-size:12px;color:var(--ink2)">Est. premium ${esc(prem)} · ${esc(ind)} indemnity</div>
      </div>
      ${isRec ? `<span class="mono" style="margin-left:auto;font-size:10px;font-weight:500;color:var(--accent);background:#fff;border:1px solid var(--accent);padding:3px 8px;border-radius:5px">RECOMMENDED</span>` : ''}
    </div>`;
  }).join('');
  const recCol = p.columns.find(c => c.id === p.recommended);
  const recName = recCol ? recCol.name : '[select an insurer]';
  return `
  <div style="max-width:900px">
    ${screenHeader('Comments &amp; recommendation', 'Standard wording is fixed. You choose the insurer — the system never ranks or suggests.')}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
      ${cards || `<div style="grid-column:1/-1;padding:30px;text-align:center;color:var(--ink3);font-size:13.5px" class="card">No comparison columns yet — upload quotes first.</div>`}
    </div>
    <div class="card" style="padding:20px 22px;margin-bottom:16px">
      <div class="mono" style="font-size:11px;font-weight:500;letter-spacing:.5px;text-transform:uppercase;color:var(--ink3);margin-bottom:10px">Standard wording — fixed</div>
      <p style="font-size:13.5px;line-height:1.65;color:var(--ink2);margin:0">The policy we propose to arrange is provided by <strong style="color:var(--accent);background:var(--accent-soft);padding:1px 6px;border-radius:5px">${esc(recName)}</strong>, which is one of the UK’s leading Credit Insurance companies. An explanation of the proposed policy is included in the policy documents. We are not contractually obliged to purchase insurance products from ${esc(recName)}. Our past experience, and analysis of the market, has shown that the cover provided by ${esc(recName)} is comprehensive and its premiums competitive.</p>
    </div>
    <div class="card" style="padding:16px 18px">
      <label style="display:block;font-size:12.5px;font-weight:600;color:var(--ink2);margin-bottom:8px">Reasons for the recommendation <span style="color:var(--ink3);font-weight:400">— free text</span></label>
      <textarea class="textarea" data-edit="reasons" style="min-height:90px" placeholder="e.g. Highest indemnity at a competitive rate, debt collection included, and the widest discretionary limit for the client’s buyer profile.">${esc(p.reasons)}</textarea>
    </div>
    ${navFooter('limits', 'Generate &amp; export', 'export')}
  </div>`;
}

/* ── S8 Export ─────────────────────────────────────────────────────── */
function renderExport(p) {
  const done = allConfirmed(p);
  const nLeft = CONFIRM_KEYS.filter(k => !p.confirmed[k]).length;
  const isRen = p.projectType === 'renewal';
  const quoted = p.columns.filter(c => !c.manual && !c.expiring).map(c => c.name);
  const declined = p.approached
    .map(id => INSURERS.find(i => i.id === id))
    .filter(i => i && !p.columns.some(c =>
      (c.matched && c.matched.toLowerCase() === i.name.toLowerCase())
      || c.name.toLowerCase().includes(i.name.toLowerCase())
      || i.name.toLowerCase().includes(c.name.toLowerCase())))
    .map(i => i.name);
  const miniRows = MINI_FIELDS.map(([key, label]) => `
    <tr>
      <td style="padding:6px 8px;color:var(--ink2);border-bottom:1px solid var(--line2)">${label}</td>
      ${p.columns.map(col => `<td style="padding:6px 8px;border-bottom:1px solid var(--line2);background:${col.id === p.recommended ? 'var(--rec)' : 'transparent'};color:var(--ink)">${esc((col.data[key] || {}).value || '—')}</td>`).join('')}
    </tr>`).join('');

  return `
  <div style="display:grid;grid-template-columns:1fr 300px;gap:26px;align-items:start">
    <div>
      <h1 style="font-size:26px;margin:0 0 6px;font-weight:700;letter-spacing:-.4px">Generate &amp; export</h1>
      <p style="color:var(--ink2);font-size:13.5px;margin:0 0 20px">Preview of the presentation. Regenerating replaces the previous export under this project.</p>
      <div id="export-preview" style="display:flex;flex-direction:column;gap:16px">
        <div style="aspect-ratio:16/9;border:1px solid var(--line);border-radius:10px;background:linear-gradient(115deg,#ffffff 55%,#14c0d5 55.5%,#14c0d5 63%,#12395e 63.5%);color:#111;padding:34px 40px;display:flex;flex-direction:column;justify-content:center;box-shadow:0 4px 18px rgba(20,30,50,.08)">
          <div style="font-size:14px;font-weight:700;color:#12395e;margin-bottom:16px">UK Credit Insurance Brokers</div>
          <div style="font-size:30px;font-weight:700;line-height:1.15;letter-spacing:-.5px;max-width:56%">${esc(p.clientName || 'Client')} - ${isRen ? 'Renewal Credit Insurance Presentation' : 'Credit Insurance Presentation'}</div>
          <div style="margin-top:20px;font-size:14px;color:var(--ink2)">${monthLabel()} · ukcreditinsurance.com</div>
        </div>
        <div class="card" style="padding:24px 28px;border-radius:14px;background:#fff">
          <div style="font-size:16px;font-weight:600;margin-bottom:10px">Feedback of Terms</div>
          <p style="font-size:12px;color:var(--ink2);line-height:1.6;margin:0 0 14px">Insurance Act 2015 ‘Duty of Fair Presentation’ wording as required — fixed template text. This summary does not amend the policy documents.</p>
          <div class="mono" style="font-size:10.5px;font-weight:500;color:var(--ink3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Insurers approached</div>
          <div style="font-size:12.5px;color:var(--ink);margin-bottom:8px">${quoted.length ? esc(quoted.join(', ')) + ' — quotations obtained.' : 'No quotations extracted yet.'}</div>
          ${declined.length ? `<div style="font-size:12.5px;color:var(--warn);background:var(--warn-soft);padding:7px 10px;border-radius:6px">${esc(declined.join(', '))} ${declined.length === 1 ? 'was' : 'were'} approached but declined to quote.</div>` : ''}
        </div>
        <div class="card" style="padding:22px 24px;overflow:hidden;background:#fff">
          <div style="font-size:16px;font-weight:600;margin-bottom:12px">Terms comparison</div>
          <table style="border-collapse:collapse;width:100%;font-size:11.5px">
            <thead><tr>
              <th style="text-align:left;padding:7px 8px;color:var(--ink3);font-weight:500;border-bottom:1px solid var(--line)">Field</th>
              ${p.columns.map(col => `<th style="text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);background:${col.id === p.recommended ? 'var(--rec)' : 'var(--panel)'};color:${col.id === p.recommended ? 'var(--accent)' : 'var(--ink)'};font-weight:600">${esc(col.name)}</th>`).join('')}
            </tr></thead>
            <tbody>${miniRows}</tbody>
          </table>
          <div class="mono" style="font-size:10.5px;font-weight:500;color:var(--ink3);margin-top:10px">+ buyer credit limits · comments &amp; recommendation · contact</div>
        </div>
      </div>
    </div>
    <div class="card" style="position:sticky;top:76px;padding:20px">
      <div style="font-weight:600;font-size:15px;margin-bottom:4px">Export</div>
      <div style="font-size:12.5px;color:var(--ink2);margin-bottom:16px">One to two minutes. Nothing is sent from the system.</div>
      <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:16px">
        <button data-act="exportPpt" ${done ? '' : 'disabled'} class="btn" style="padding:12px;border-radius:9px;background:${done ? 'var(--accent)' : '#e7eaef'};color:${done ? '#fff' : 'var(--ink3)'};opacity:${done ? '1' : '.7'};cursor:${done ? 'pointer' : 'not-allowed'}">${ICON.download}Download PowerPoint</button>
        <button data-act="exportPdf" ${done ? '' : 'disabled'} class="btn" style="padding:12px;border-radius:9px;background:var(--surface);border:1px solid ${done ? 'var(--accent)' : 'var(--line)'};color:${done ? 'var(--accent)' : 'var(--ink3)'};opacity:${done ? '1' : '.7'};cursor:${done ? 'pointer' : 'not-allowed'}">${ICON.download}Download PDF</button>
        ${p.credit.length && done ? `<div data-act="exportLimitsXlsx" style="font-size:12px;color:var(--accent);cursor:pointer;font-weight:500;text-align:center">Credit limits as Excel ↓</div>` : ''}
      </div>
      <div style="background:${done ? 'var(--ok-soft)' : 'var(--warn-soft)'};border:1px solid ${done ? 'var(--ok)' : 'var(--warn)'};border-radius:9px;padding:11px 13px;font-size:12px;line-height:1.5;color:${done ? 'var(--ok)' : 'var(--warn)'}">${done ? '✓ All key values confirmed. Export is enabled.' : '⚠ Export is blocked until Est. premium, indemnity, excess and max liability are confirmed on the review screen (' + nLeft + ' remaining).'}</div>
      ${p.exported && done ? `<div style="margin-top:12px;background:var(--ok-soft);color:var(--ok);border-radius:8px;padding:10px 12px;font-size:12.5px;font-weight:500">✓ Files generated — ready to proofread &amp; send.</div>` : ''}
      <div style="display:flex;justify-content:space-between;margin-top:18px;padding-top:14px;border-top:1px solid var(--line2);font-size:12px;color:var(--ink3)">
        <span>Type</span><span style="color:var(--ink);font-weight:500">${isRen ? 'Renewal' : 'New business'}</span>
      </div>
      <div data-act="flipType" style="margin-top:6px;font-size:12px;color:var(--accent);cursor:pointer;font-weight:500">Switch to ${isRen ? 'new business' : 'renewal'} preview →</div>
    </div>
  </div>`;
}

/* ── Source modal ──────────────────────────────────────────────────── */
function renderSourceModal() {
  if (!state.source) return '';
  return `
  <div class="modal-overlay" data-act="closeSource">
    <div data-act="modalCard" style="width:520px;max-width:100%;background:var(--surface);border-radius:14px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.3)">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:15px 20px;border-bottom:1px solid var(--line)">
        <div>
          <div style="font-weight:600;font-size:14px">Source document</div>
          <div class="mono" style="font-size:11.5px;color:var(--ink3)">${esc(state.source.caption)}</div>
        </div>
        <span data-act="closeSource" style="cursor:pointer;color:var(--ink3);font-size:20px">×</span>
      </div>
      <div style="padding:24px;background:var(--bg);max-height:72vh;overflow:auto">
        ${state.source.docId
          ? `<img src="/documents/${esc(state.source.docId)}/page/${state.source.page}" alt="${esc(state.source.caption)}" style="width:100%;border:1px solid var(--line);border-radius:6px;background:#fff">`
          : `<div style="aspect-ratio:1/1.3;background:repeating-linear-gradient(135deg,#eef1f5,#eef1f5 10px,#f6f8fa 10px,#f6f8fa 20px);border:1px solid var(--line);border-radius:6px;display:grid;place-items:center">
          <div class="mono" style="text-align:center;font-size:12px;color:var(--ink3)">no stored page for this document<br>${esc(state.source.caption)}</div>
        </div>`}
      </div>
    </div>
  </div>`;
}
