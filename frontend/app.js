/* UK Insurance — Quote Comparison Tool (frontend)
   Theme + screens follow the approved wireframe 1:1.
   The Upload step calls the real backend: POST /extract-quote. */

'use strict';

/* ── Standing insurer list (Setup screen; DEBT INCL badge mirrors the
      BRD 2.4 rule). Served from the backend's config/insurers.json so the
      list is configuration, not code — this constant is only the fallback
      until /insurers responds. ─────────────────────────────────────── */
let INSURERS = [
  { id: 'allianz',  name: 'Allianz Trade',    debtIncl: true  },
  { id: 'atradius', name: 'Atradius',         debtIncl: true  },
  { id: 'coface',   name: 'Coface',           debtIncl: true  },
  { id: 'tmhcc',    name: 'Tokio Marine HCC', debtIncl: false },
  { id: 'qbe',      name: 'QBE',              debtIncl: false },
  { id: 'aig',      name: 'AIG',              debtIncl: false },
  { id: 'chubb',    name: 'Chubb',            debtIncl: false },
  { id: 'markel',   name: 'Markel',           debtIncl: false },
  { id: 'nexus',    name: 'Nexus',            debtIncl: false },
  { id: 'aviva',    name: 'Aviva',            debtIncl: false },
];

async function loadInsurerConfig() {
  try {
    const res = await fetch('/insurers');
    if (!res.ok) return;
    const list = (await res.json()).insurers;
    if (Array.isArray(list) && list.length) {
      INSURERS = list.map(i => ({
        id: i.id, name: i.name, debtIncl: i.debt_collection === 'included',
      }));
      render();
    }
  } catch (e) { /* fallback constant stays in effect */ }
}

/* ── Review grid rows. `key` matches the backend JSON where extracted;
      set:true rows are broker/rule-set (never extracted). ───────────── */
const FIELDS = [
  { key: 'type',     label: 'Type of policy', tag: 'SET', note: 'Set by broker · overridable', set: true },
  { key: 'annual_turnover', label: 'Annual turnover' },
  { key: 'premium_rate', label: 'Premium rate' },
  { key: 'estimated_annual_premium_exc_ipt', label: 'Estimated annual premium', note: 'exc IPT', confirm: 'premium' },
  { key: 'minimum_annual_premium', label: 'Minimum annual premium' },
  { key: 'credit_limit_charges', label: 'Credit limit charges' },
  { key: 'debt',     label: 'Debt collection support', tag: 'RULE', note: 'Set by insurer rule', set: true },
  { key: 'indemnity', label: 'Indemnity', confirm: 'indemnity' },
  { key: 'excess',   label: 'Excess', confirm: 'excess' },
  { key: 'excess_type', label: 'Excess type', note: 'Insurer’s own term' },
  { key: 'max_annual_liability', label: 'Max annual liability', confirm: 'maxLiability' },
  { key: 'discretionary_limit', label: 'Discretionary limit' },
  { key: 'max_terms_of_payment', label: 'Max terms of payment' },
  { key: 'max_extension_period', label: 'Max extension period' },
  { key: 'additional_info', label: 'Additional info', note: 'Free-format' },
];
const CONFIRM_KEYS = ['premium', 'indemnity', 'excess', 'maxLiability'];
const MINI_FIELDS = [
  ['premium_rate', 'Premium rate'], ['estimated_annual_premium_exc_ipt', 'Est. premium'],
  ['indemnity', 'Indemnity'], ['excess', 'Excess'], ['max_annual_liability', 'Max liability'],
];
const POLICY_OPTIONS = ['Whole Turnover', 'Top-Up', 'Single Risk', 'Gap-Fill'];
const STEPS = [
  ['setup', 'Setup'], ['upload', 'Upload'], ['review', 'Review'],
  ['limits', 'Credit limits'], ['recommend', 'Recommendation'], ['export', 'Generate'],
];

/* ── State ─────────────────────────────────────────────────────────── */
const state = {
  screen: 'login',
  user: null,               // { email, initials }
  projects: [],             // persisted
  currentId: null,
  source: null,             // { caption }
  projSearch: '',
  projFilter: 'All',
};

function load() {
  try {
    state.projects = JSON.parse(localStorage.getItem('qct_projects') || '[]');
    const u = sessionStorage.getItem('qct_user');
    if (u) { state.user = JSON.parse(u); state.screen = 'projects'; }
  } catch (e) { /* fresh start on corrupt storage */ }
}
function save() {
  try { localStorage.setItem('qct_projects', JSON.stringify(state.projects)); } catch (e) {}
}
const proj = () => state.projects.find(p => p.id === state.currentId) || null;
const uid = () => Math.random().toString(36).slice(2, 9);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function todayLabel() {
  return new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}
function monthLabel() {
  return new Date().toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
}

/* ── Project factory ───────────────────────────────────────────────── */
function newProject() {
  const n = 2400 + state.projects.length + 1;
  const p = {
    id: uid(), clientName: '', ref: 'UKCIB-' + n,
    projectType: 'new', policyType: 'Whole Turnover',
    approached: [], columns: [], files: [],
    credit: [],               // { id, buyer, reg, req, offers: {colId: val} }
    confirmed: { premium: false, indemnity: false, excess: false, maxLiability: false },
    recommended: null, manualSeq: 1,
    notes: 'All quotes shown are subject to underwriting and the terms of the policy documents. Premiums exclude IPT.',
    reasons: '', exported: false, status: 'draft', updated: todayLabel(),
  };
  state.projects.unshift(p);
  state.currentId = p.id;
  return p;
}

function touch(p) { p.updated = todayLabel(); save(); }

/* ── Backend wiring ────────────────────────────────────────────────── */
function debtRuleFor(insurerName) {
  // Fallback only — the server's set_fields normally supplies this.
  // BRD 2.4: unmatched insurers default to Outsourced.
  if (!insurerName) return 'Outsourced';
  const hit = INSURERS.find(i => insurerName.toLowerCase().includes(i.name.toLowerCase())
    || i.name.toLowerCase().includes(insurerName.toLowerCase()));
  return hit && hit.debtIncl ? 'Included' : 'Outsourced';
}

function mergeBuyers(p, colId, buyers) {
  for (const b of buyers || []) {
    if (!b.buyer_name && !b.company_number) continue;
    let row = p.credit.find(r =>
      (b.company_number && r.reg === b.company_number) ||
      (b.buyer_name && r.buyer.toLowerCase() === b.buyer_name.toLowerCase()));
    if (!row) {
      row = { id: uid(), buyer: b.buyer_name || '', reg: b.company_number || '', req: '', offers: {} };
      p.credit.push(row);
    }
    if (!row.reg && b.company_number) row.reg = b.company_number;
    if (!row.req && b.limit_required) row.req = b.limit_required;
    if (colId && b.limit_offered) row.offers[colId] = b.limit_offered;
  }
}

const MAX_QUOTES = 6;

async function uploadFiles(kind, fileList) {
  const p = proj(); if (!p) return;
  let files = Array.from(fileList);
  if (kind === 'quote') {
    const room = MAX_QUOTES - p.files.filter(f => f.kind === 'quote').length;
    if (files.length > room) {
      alert(`Up to ${MAX_QUOTES} quotes per project — ${Math.max(room, 0)} more can be added.`);
      files = files.slice(0, Math.max(room, 0));
    }
  }
  for (const f of files) {
    const entry = {
      id: uid(), name: f.name, kind,
      ext: (f.name.split('.').pop() || 'PDF').toUpperCase().slice(0, 4),
      status: 'processing', meta: kindLabel(kind) + ' · uploading…',
    };
    p.files.push(entry);
    render();
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await fetch('/extract-quote', { method: 'POST', body: fd });
      if (!res.ok) {
        let detail = 'HTTP ' + res.status;
        try { detail = (await res.json()).detail || detail; } catch (e) {}
        throw new Error(detail);
      }
      const body = await res.json();
      applyExtraction(p, entry, body, kind);
    } catch (err) {
      entry.status = 'error';
      entry.meta = kindLabel(kind) + ' · ' + (err.message || 'extraction failed');
    }
    touch(p);
    render();
  }
}

function kindLabel(kind) {
  return kind === 'limits' ? 'credit-limit doc' : kind === 'expiring' ? 'expiring policy' : 'quote';
}

/* ── Demo data (wireframe sample) — lets the whole flow be exercised
      without uploads or API credits ─────────────────────────────────── */
function buildDemoColumns() {
  const sv = (v, page, conf) => ({ value: v, page, conf: conf || 'high' });
  const mk = (id, name, debt, d) => ({
    id, name, manual: false, debt, fileName: name.replace(/ /g, '-') + '_quote.pdf', data: d,
  });
  return [
    mk('demo-a', 'Insurer A', 'Included', {
      annual_turnover: sv('£4,500,000', 2), premium_rate: sv('0.32%', 3),
      estimated_annual_premium_exc_ipt: sv('£14,400', 3), minimum_annual_premium: sv('£10,000', 3),
      credit_limit_charges: sv('Included', 4), indemnity: sv('90%', 5),
      excess: sv('£1,000', 5), excess_type: sv('Minimum Retention', 5),
      max_annual_liability: sv('£2,000,000', 6), discretionary_limit: sv('£25,000', 6),
      max_terms_of_payment: sv('90 days', 7), max_extension_period: sv('60 days', 7),
      additional_info: sv('No-claims bonus 10%', 8),
    }),
    mk('demo-b', 'Insurer B', 'Included', {
      annual_turnover: sv('£4,500,000', 1), premium_rate: sv('0.28%', 2),
      estimated_annual_premium_exc_ipt: sv('£12,600', 2), minimum_annual_premium: sv('£9,500', 2),
      credit_limit_charges: sv('£45 per limit', 3), indemnity: sv('90%', 3),
      excess: sv('£2,500', 4), excess_type: sv('Deductible', 4),
      max_annual_liability: sv('£1,500,000', 4), discretionary_limit: sv('£20,000', 5, 'uncertain'),
      max_terms_of_payment: sv('60 days', 5), max_extension_period: sv('30 days', 5),
      additional_info: sv(null, null, null),
    }),
    mk('demo-c', 'Insurer C', 'Outsourced', {
      annual_turnover: sv('£4,500,000', 2), premium_rate: sv('0.35%', 3),
      estimated_annual_premium_exc_ipt: sv('£15,750', 4), minimum_annual_premium: sv('£11,000', 4),
      credit_limit_charges: sv('Included', 5), indemnity: sv('85%', 6),
      excess: sv('£1,000', 6), excess_type: sv('First Loss', 6),
      max_annual_liability: sv('£2,500,000', 7), discretionary_limit: sv(null, null, null),
      max_terms_of_payment: sv('120 days', 8), max_extension_period: sv('60 days', 8),
      additional_info: sv('New buyer cover to £50k. Quote subject to satisfactory proposal form.', 9),
    }),
    { id: 'demo-m1', name: 'Insurer A — Option 2', manual: true, debt: '', data: {} },
  ];
}

function loadDemoData(p) {
  p.columns = buildDemoColumns();
  p.recommended = 'demo-b';
  p.credit = [
    { id: 'demo-r1', buyer: 'Meridian Foods Ltd', reg: '04821990', req: '£250,000',
      offers: { 'demo-a': '£250,000', 'demo-b': '£200,000', 'demo-c': '£250,000' } },
    { id: 'demo-r2', buyer: 'Harbord Retail Group', reg: '07733120', req: '£120,000',
      offers: { 'demo-a': '£120,000', 'demo-b': '£120,000', 'demo-c': '£100,000' } },
    { id: 'demo-r3', buyer: 'Castle Logistics Ltd', reg: '09912004', req: '£80,000',
      offers: { 'demo-a': '£75,000', 'demo-c': '£80,000' } },
  ];
  p.files = [
    { id: 'demo-f1', name: 'Insurer-A_quote_2026.pdf', kind: 'quote', ext: 'PDF',
      status: 'extracted', meta: 'Insurer A · quote · 8 pages · demo data', colId: 'demo-a' },
    { id: 'demo-f2', name: 'Insurer-B_quote.pdf', kind: 'quote', ext: 'PDF',
      status: 'extracted', meta: 'Insurer B · quote (scanned) · 6 pages · 1 value to verify · demo data', colId: 'demo-b' },
    { id: 'demo-f3', name: 'Insurer-C_quote.pdf', kind: 'quote', ext: 'PDF',
      status: 'extracted', meta: 'Insurer C · quote · 9 pages · demo data', colId: 'demo-c' },
    { id: 'demo-f4', name: 'credit-limits_schedule.pdf', kind: 'limits', ext: 'PDF',
      status: 'extracted', meta: 'credit-limit schedule · 3 buyers · demo data' },
  ];
  if (!p.clientName) p.clientName = 'Aldgate Timber Ltd';
  if (!p.approached.length) p.approached = ['allianz', 'atradius', 'coface', 'tmhcc'];
}

const DOC_TYPE_LABELS = {
  insurer_quote: 'quote', credit_limit_schedule: 'credit-limit schedule',
  policy_document: 'policy document', other: 'document',
};

function applyExtraction(p, entry, body, kind) {
  const d = body.data;
  const insurer = d.insurer && d.insurer.value ? d.insurer.value : null;
  const review = body.review || { missing_fields: [], uncertain_fields: [] };
  const nCheck = review.uncertain_fields.length;
  entry.status = 'extracted';
  entry.meta = (insurer || 'Unrecognised insurer')
    + ' · ' + (DOC_TYPE_LABELS[d.document_type] || kindLabel(kind))
    + (body.meta.extraction_engine === 'azure_document_intelligence' ? ' (scanned)' : '')
    + ' · ' + body.meta.page_count + ' pages'
    + (nCheck ? ' · ' + nCheck + ' value' + (nCheck === 1 ? '' : 's') + ' to verify' : '');

  if (kind === 'limits') {
    // Attribute offers to the matching insurer column if one exists.
    const col = insurer
      ? p.columns.find(c => c.name.toLowerCase().includes(insurer.toLowerCase())) : null;
    mergeBuyers(p, col ? col.id : null, d.buyer_credit_limits);
    return;
  }

  // BRD 2.4: debt collection support is set by the server-side insurer
  // rule (config/insurers.json), never extracted; editable per column.
  const ruleDebt = body.set_fields && body.set_fields.debt_collection_support
    ? body.set_fields.debt_collection_support.value : debtRuleFor(insurer);
  const col = {
    id: uid(),
    name: kind === 'expiring' ? 'Expiring — ' + (insurer || 'policy') : (insurer || entry.name.replace(/\.pdf$/i, '')),
    manual: false, expiring: kind === 'expiring',
    fileName: entry.name, data: {},
    debt: ruleDebt,
  };
  for (const f of FIELDS) {
    if (f.set) continue;
    const sv = d[f.key];
    if (sv && typeof sv === 'object') {
      col.data[f.key] = { value: sv.value || '', page: sv.page, conf: sv.confidence };
    }
  }
  if (kind === 'expiring') p.columns.unshift(col); else p.columns.push(col);
  entry.colId = col.id;
  mergeBuyers(p, col.id, d.buyer_credit_limits);
}

/* ── Small view helpers ────────────────────────────────────────────── */
const ICON = {
  plus: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" style="margin-right:7px;vertical-align:-2px"><path d="M12 5v14M5 12h14"/></svg>',
  search: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>',
  upload: '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V7m0 0l-3 3m3-3l3 3"/><path d="M20 16.5A3.8 3.8 0 0017.5 9.6 5.5 5.5 0 006.3 11 4 4 0 005 18.9"/></svg>',
  table: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M3 9.5h18M9 4.5v15"/></svg>',
  refresh: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 12a8.5 8.5 0 11-2.6-6.1M20.5 4v5h-5"/></svg>',
  download: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"/></svg>',
};

function cellValue(p, col, field) {
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
function allConfirmed(p) { return CONFIRM_KEYS.every(k => p.confirmed[k]); }
function confirmLabel(k) {
  return { premium: 'Premium', indemnity: 'Indemnity', excess: 'Excess', maxLiability: 'Max liability' }[k];
}

/* ═══════════════════════════ RENDERERS ═════════════════════════════ */

function render() {
  const app = document.getElementById('app');
  let html = '';
  if (state.screen === 'login') {
    html = renderLogin();
  } else {
    html = '<div style="height:100vh;display:flex;flex-direction:column;overflow:hidden">'
      + renderTopbar()
      + (state.screen === 'projects' ? renderProjects() : renderWizard())
      + '</div>';
  }
  html += renderSourceModal();
  app.innerHTML = html;
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
      <div style="width:32px;height:32px;border-radius:50%;background:var(--set-soft);color:var(--set);display:grid;place-items:center;font-weight:600;font-size:13px">${esc(u.initials)}</div>
    </div>
  </header>`;
}

/* ── S2 Projects ───────────────────────────────────────────────────── */
function projectRowsHtml() {
  const q = state.projSearch.toLowerCase();
  const typeLabelOf = p => p.projectType === 'renewal' ? 'Renewal' : 'New business';
  let list = state.projects.filter(p =>
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
      <span class="mono" style="text-align:right;color:var(--ink3);font-size:11px;font-weight:500">${p.exported ? 'PPT · PDF' : '—'}</span>
    </div>`;
  }).join('');
}

function renderProjects() {
  const filters = ['All', 'New business', 'Renewal'].map(f => `
    <span data-act="setFilter" data-arg="${f}" style="font-size:12.5px;padding:9px 13px;background:var(--surface);border:1px solid var(--line);border-radius:9px;cursor:pointer;color:${state.projFilter === f ? 'var(--ink)' : 'var(--ink2)'};font-weight:${state.projFilter === f ? '500' : '400'}">${f}</span>`).join('');
  return `
  <main class="fade" style="flex:1;min-height:0;overflow:auto;padding:34px 26px 60px"><div style="max-width:1100px;width:100%;margin:0 auto">
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
function renderStepper() {
  const cur = STEPS.findIndex(s => s[0] === state.screen);
  return `
  <div style="background:var(--surface);border-bottom:1px solid var(--line);padding:20px 26px">
    <div style="max-width:960px;margin:0 auto;display:flex;align-items:center;overflow-x:auto">
      ${STEPS.map(([id, label], i) => {
        const st = i < cur ? 'done' : i === cur ? 'current' : 'todo';
        const numBg = st === 'current' ? 'var(--accent)' : st === 'done' ? 'var(--accent-soft)' : '#fff';
        const numFg = st === 'current' ? '#fff' : st === 'done' ? 'var(--accent)' : 'var(--ink3)';
        const numBorder = st === 'current' ? 'var(--accent)' : st === 'done' ? 'var(--accent-soft)' : 'var(--line)';
        const shadow = st === 'current' ? '0 2px 8px rgba(79,70,229,.4)' : 'none';
        return (i > 0 ? `<span style="flex:1;min-width:16px;height:2px;background:${i <= cur ? 'var(--accent)' : 'var(--line)'};margin:0 10px"></span>` : '')
        + `<div data-act="go" data-arg="${id}" style="display:flex;align-items:center;gap:9px;cursor:pointer;flex:none;white-space:nowrap">
            <span style="width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-size:12.5px;font-weight:700;background:${numBg};color:${numFg};border:1.5px solid ${numBorder};box-shadow:${shadow}">${st === 'done' ? '✓' : i + 1}</span>
            <span style="font-size:12.5px;font-weight:${st === 'current' ? 700 : 500};color:${st === 'todo' ? 'var(--ink3)' : 'var(--ink)'}">${label}</span>
          </div>`;
      }).join('')}
    </div>
  </div>`;
}

function renderWizard() {
  const p = proj();
  if (!p) { state.screen = 'projects'; return renderProjects(); }
  const inner = {
    setup: renderSetup, upload: renderUpload, review: renderReview,
    limits: renderLimits, recommend: renderRecommend, export: renderExport,
  }[state.screen] || renderSetup;
  return `
  <div style="flex:1;min-height:0;display:flex;flex-direction:column">
    ${renderStepper()}
    <main style="flex:1;min-height:0;overflow:auto">
      <div class="fade" style="max-width:1180px;margin:0 auto;padding:30px 26px 40px">${inner(p)}</div>
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
    <h1 style="font-size:26px;margin:0 0 6px;font-weight:700;letter-spacing:-.4px">New project</h1>
    <p style="color:var(--ink2);font-size:13.5px;margin:0 0 26px">Set up the client and choose which insurers were approached.</p>
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
          ${typeCard('new', !isRen, 'New business', 'Front page: “Credit Insurance Proposals”')}
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
    <h1 style="font-size:26px;margin:0 0 6px;font-weight:700;letter-spacing:-.4px">Upload documents</h1>
    <p style="color:var(--ink2);font-size:13.5px;margin:0 0 24px">Add quotes as they arrive — uploads are cumulative and the comparison refreshes each time.</p>
    <input type="file" id="file-quote" accept="application/pdf" multiple hidden>
    <input type="file" id="file-limits" accept="application/pdf,.xlsx,.xls" multiple hidden>
    <input type="file" id="file-expiring" accept="application/pdf" hidden>
    <div style="display:grid;grid-template-columns:${isRen ? '1fr 1fr 1fr' : '1fr 1fr'};gap:16px;margin-bottom:24px">
      <div data-drop="quote" style="border:1.5px dashed var(--line);border-radius:12px;padding:24px 18px;text-align:center;background:var(--surface)">
        <div style="width:38px;height:38px;border-radius:9px;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;margin:0 auto 12px;pointer-events:none">${ICON.upload}</div>
        <div style="font-weight:600;font-size:14px;margin-bottom:3px;pointer-events:none">Quotes</div>
        <div style="font-size:12px;color:var(--ink2);margin-bottom:14px;pointer-events:none">Drag &amp; drop PDFs here, incl. scanned. Up to 6.</div>
        <button class="btn-soft" data-act="pickFile" data-arg="file-quote">Choose files</button>
      </div>
      <div data-drop="limits" style="border:1.5px dashed var(--line);border-radius:12px;padding:24px 18px;text-align:center;background:var(--surface)">
        <div style="width:38px;height:38px;border-radius:9px;background:var(--panel);color:var(--ink2);display:grid;place-items:center;margin:0 auto 12px;pointer-events:none">${ICON.table}</div>
        <div style="font-weight:600;font-size:14px;margin-bottom:3px;pointer-events:none">Credit-limit docs</div>
        <div style="font-size:12px;color:var(--ink2);margin-bottom:14px;pointer-events:none">Drag &amp; drop — PDF or Excel. Optional.</div>
        <button data-act="pickFile" data-arg="file-limits" style="font-size:12.5px;font-weight:600;color:var(--ink2);background:var(--panel);border:1px solid var(--line);padding:8px 14px;border-radius:7px;cursor:pointer">Choose files</button>
      </div>
      ${isRen ? `
      <div data-drop="expiring" style="border:1.5px dashed var(--warn);border-radius:12px;padding:24px 18px;text-align:center;background:var(--warn-soft)">
        <div style="width:38px;height:38px;border-radius:9px;background:#fff;color:var(--warn);display:grid;place-items:center;margin:0 auto 12px;pointer-events:none">${ICON.refresh}</div>
        <div style="font-weight:600;font-size:14px;margin-bottom:3px;pointer-events:none">Expiring policy</div>
        <div style="font-size:12px;color:var(--warn);margin-bottom:14px;pointer-events:none">Drag &amp; drop — required for renewal.</div>
        <button data-act="pickFile" data-arg="file-expiring" style="font-size:12.5px;font-weight:600;color:var(--warn);background:#fff;border:1px solid var(--warn);padding:8px 14px;border-radius:7px;cursor:pointer">Choose file</button>
      </div>` : ''}
    </div>
    <div class="card" style="overflow:hidden">
      <div style="padding:13px 18px;border-bottom:1px solid var(--line);font-weight:600;font-size:13.5px;display:flex;justify-content:space-between;align-items:center">
        <span>Documents</span>
        <div style="display:flex;align-items:center;gap:12px">
          ${p.columns.length ? '' : `<button class="btn-soft" style="padding:6px 12px;font-size:12px" data-act="loadDemo">Load demo data</button>`}
          <span class="mono" style="font-size:11px;font-weight:500;color:var(--ink3)">${p.files.length} file${p.files.length === 1 ? '' : 's'}${nErr ? ' · ' + nErr + ' unreadable' : ''}</span>
        </div>
      </div>
      ${filesHtml}
    </div>
    <p style="font-size:12.5px;color:var(--ink2);margin:14px 2px 0">An unreadable document is flagged individually — the project continues with that insurer’s column blank.</p>
    <div style="display:flex;justify-content:space-between;gap:10px;margin-top:22px">
      <button class="btn btn-secondary" data-act="go" data-arg="setup">← Back</button>
      <button class="btn btn-primary" data-act="go" data-arg="review">Review comparison →</button>
    </div>
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
          ${col.manual ? `<span data-act="removeColumn" data-arg="${col.id}" title="Remove column" style="cursor:pointer;color:var(--ink3);font-size:15px;line-height:1">×</span>` : ''}
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
            ${page ? `<button class="src-chip" data-act="openSource" data-arg="${esc(col.name)} quote · p${page}" title="Open source page">p${page}</button>` : ''}
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
        <span style="display:flex;align-items:center;gap:6px"><span style="width:11px;height:11px;border-radius:3px;background:var(--warn-soft);border:1px solid var(--warn)"></span>Confirm / AI-uncertain</span>
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
      : `<div style="padding:40px;text-align:center;color:var(--ink3);font-size:13.5px">No comparison columns yet — upload quotes on the previous step, or add a free-format column.<br><button class="btn-soft" style="margin-top:14px" data-act="loadDemo">Load demo data</button></div>`}
    </div>
    <div class="card" style="margin-top:16px;padding:16px 18px">
      <label style="display:block;font-size:12.5px;font-weight:600;color:var(--ink2);margin-bottom:8px">Free-format notes <span style="color:var(--ink3);font-weight:400">— appears beneath the comparison</span></label>
      <textarea class="textarea" data-edit="notes" style="min-height:64px;line-height:1.5">${esc(p.notes)}</textarea>
    </div>
    <div style="display:flex;justify-content:space-between;gap:10px;margin-top:22px">
      <button class="btn btn-secondary" data-act="go" data-arg="upload">← Back</button>
      <button class="btn btn-primary" data-act="go" data-arg="limits">Credit limits →</button>
    </div>
  </div>`;
}

/* ── S6 Credit limits ──────────────────────────────────────────────── */
function renderLimits(p) {
  const th = (txt, extra) => `<th style="text-align:left;padding:12px 14px;font:500 11px 'IBM Plex Mono';letter-spacing:.4px;text-transform:uppercase;color:var(--ink3);background:var(--panel);border-bottom:1px solid var(--line);${extra || ''}">${txt}</th>`;
  // Wide enough that names, limits and the "Not reviewed" placeholder never
  // truncate; the card scrolls horizontally when columns outgrow it.
  const tableMin = 470 + p.columns.length * 130;
  const rows = p.credit.map(r => `
    <tr>
      <td style="padding:2px 8px;border-bottom:1px solid var(--line2)"><input class="cell-input" style="font-weight:500;padding:8px 6px" data-edit="credit" data-row="${r.id}" data-part="buyer" value="${esc(r.buyer)}" placeholder="Buyer name"></td>
      <td style="padding:2px 6px;border-bottom:1px solid var(--line2)"><input class="cell-input mono" style="font-size:12.5px;color:var(--ink2);padding:8px 6px" data-edit="credit" data-row="${r.id}" data-part="reg" value="${esc(r.reg)}" placeholder="—"></td>
      <td style="padding:2px 6px;border-bottom:1px solid var(--line2)"><input class="cell-input" style="padding:8px 6px" data-edit="credit" data-row="${r.id}" data-part="req" value="${esc(r.req)}" placeholder="—"></td>
      ${p.columns.map(col => {
        const v = r.offers[col.id] || '';
        return `<td style="padding:2px 6px;border-bottom:1px solid var(--line2);border-left:1px solid var(--line2);background:${col.id === p.recommended ? 'var(--rec)' : 'transparent'}">
          <input class="cell-input" style="padding:8px 6px;font-style:${v ? 'normal' : 'italic'}" data-edit="credit" data-row="${r.id}" data-part="offer" data-col="${col.id}" value="${esc(v)}" placeholder="Not reviewed">
        </td>`;
      }).join('')}
      <td style="text-align:center;border-bottom:1px solid var(--line2)"><span data-act="removeCredit" data-arg="${r.id}" title="Remove buyer row" style="color:var(--ink3);cursor:pointer;font-size:16px">×</span></td>
    </tr>`).join('');
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
                ${col.manual ? `<span data-act="removeColumn" data-arg="${col.id}" title="Remove this free-format column (also removes it from the comparison)" style="flex:none;cursor:pointer;color:var(--ink3);font-size:15px;line-height:1">×</span>` : ''}
              </div>
              ${col.manual ? `<span class="mono" style="display:inline-block;margin-top:4px;font-size:9px;font-weight:500;color:var(--warn);background:var(--warn-soft);padding:2px 6px;border-radius:4px">FREE FORMAT</span>` : ''}
            </th>`;
          }).join('')}
          <th style="background:var(--panel);border-bottom:1px solid var(--line);width:40px"></th>
        </tr></thead>
        <tbody>${rows || `<tr><td colspan="${4 + p.columns.length}" style="padding:34px;text-align:center;color:var(--ink3);font-size:13px">No buyer limits — extracted rows appear here, or add one manually.</td></tr>`}</tbody>
      </table>
    </div>
    <p style="font-size:12.5px;color:var(--ink2);margin:14px 2px 0">Around 90% of limits arrive as a separate schedule. This page is omitted cleanly from the presentation when no limits are supplied.</p>
    <div style="display:flex;justify-content:space-between;gap:10px;margin-top:22px">
      <button class="btn btn-secondary" data-act="go" data-arg="review">← Back</button>
      <button class="btn btn-primary" data-act="go" data-arg="recommend">Recommendation →</button>
    </div>
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
    <h1 style="font-size:26px;margin:0 0 6px;font-weight:700;letter-spacing:-.4px">Comments &amp; recommendation</h1>
    <p style="color:var(--ink2);font-size:13.5px;margin:0 0 24px">Standard wording is fixed. You choose the insurer — the system never ranks or suggests.</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
      ${cards || `<div style="grid-column:1/-1;padding:30px;text-align:center;color:var(--ink3);font-size:13.5px" class="card">No comparison columns yet — upload quotes first.</div>`}
    </div>
    <div class="card" style="padding:20px 22px;margin-bottom:16px">
      <div class="mono" style="font-size:11px;font-weight:500;letter-spacing:.5px;text-transform:uppercase;color:var(--ink3);margin-bottom:10px">Standard wording — fixed</div>
      <p style="font-size:13.5px;line-height:1.65;color:var(--ink2);margin:0">Having reviewed the quotations obtained on your behalf, we recommend <strong style="color:var(--accent);background:var(--accent-soft);padding:1px 6px;border-radius:5px">${esc(recName)}</strong>. This recommendation reflects the cover, terms and pricing offered relative to the alternatives presented. This document is a summary; the policy wording prevails. UK Credit Insurance Brokers is authorised and regulated by the Financial Conduct Authority.</p>
    </div>
    <div class="card" style="padding:16px 18px">
      <label style="display:block;font-size:12.5px;font-weight:600;color:var(--ink2);margin-bottom:8px">Reasons for the recommendation <span style="color:var(--ink3);font-weight:400">— free text</span></label>
      <textarea class="textarea" data-edit="reasons" style="min-height:90px" placeholder="e.g. Highest indemnity at a competitive rate, debt collection included, and the widest discretionary limit for the client’s buyer profile.">${esc(p.reasons)}</textarea>
    </div>
    <div style="display:flex;justify-content:space-between;gap:10px;margin-top:22px">
      <button class="btn btn-secondary" data-act="go" data-arg="limits">← Back</button>
      <button class="btn btn-primary" data-act="go" data-arg="export">Generate &amp; export →</button>
    </div>
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
    .filter(i => i && !p.columns.some(c => c.name.toLowerCase().includes(i.name.toLowerCase())))
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
        <div style="aspect-ratio:16/9;border:1px solid var(--line);border-radius:10px;background:linear-gradient(155deg,#0f1424,#252f68);color:#fff;padding:34px 40px;display:flex;flex-direction:column;justify-content:center;box-shadow:0 4px 18px rgba(20,30,50,.08)">
          <div class="mono" style="font-size:12px;font-weight:500;color:#8fa2c9;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:16px">${isRen ? 'Renewal' : 'New business'}</div>
          <div style="font-size:34px;font-weight:600;line-height:1.15;letter-spacing:-.5px;max-width:80%">${isRen ? 'Renewal of Credit Insurance' : 'Credit Insurance Proposals'}</div>
          <div style="margin-top:20px;font-size:15px;color:#c3cfe0">${esc(p.clientName || 'Client')} · ${monthLabel()}</div>
        </div>
        <div class="card" style="padding:24px 28px;border-radius:14px;background:#fff">
          <div style="font-size:16px;font-weight:600;margin-bottom:10px">Important information</div>
          <p style="font-size:12px;color:var(--ink2);line-height:1.6;margin:0 0 14px">Regulatory wording as required by the Financial Conduct Authority. This summary does not amend the policy documents.</p>
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
      <div style="padding:24px;background:var(--bg)">
        <div style="aspect-ratio:1/1.3;background:repeating-linear-gradient(135deg,#eef1f5,#eef1f5 10px,#f6f8fa 10px,#f6f8fa 20px);border:1px solid var(--line);border-radius:6px;display:grid;place-items:center">
          <div class="mono" style="text-align:center;font-size:12px;color:var(--ink3)">quote PDF preview<br>${esc(state.source.caption)}</div>
        </div>
      </div>
    </div>
  </div>`;
}

/* ═══════════════════════════ ACTIONS ═══════════════════════════════ */

const ACTIONS = {
  signIn() {
    const email = (document.getElementById('login-email').value || '').trim();
    if (!email) { document.getElementById('login-email').focus(); return; }
    const parts = email.split('@')[0].split(/[._-]/).filter(Boolean);
    const initials = (parts.length > 1 ? parts[0][0] + parts[1][0] : email.slice(0, 2)).toUpperCase();
    state.user = { email, initials };
    try { sessionStorage.setItem('qct_user', JSON.stringify(state.user)); } catch (e) {}
    state.screen = 'projects';
    render();
  },
  toProjects() { state.screen = 'projects'; render(); },
  newProject() { newProject(); save(); state.screen = 'setup'; render(); },
  openProject(id) {
    state.currentId = id;
    const p = proj();
    state.screen = p && p.columns.length ? 'review' : 'setup';
    render();
  },
  setFilter(f) { state.projFilter = f; render(); },
  go(screen) { state.screen = screen; render(); },

  setType(t) { const p = proj(); p.projectType = t; touch(p); render(); },
  setPolicy(pt) { const p = proj(); p.policyType = pt; touch(p); render(); },
  toggleApproach(id) {
    const p = proj();
    const i = p.approached.indexOf(id);
    if (i >= 0) p.approached.splice(i, 1);
    else if (p.approached.length < 10) p.approached.push(id);
    touch(p); render();
  },

  pickFile(inputId) { document.getElementById(inputId).click(); },

  loadDemo() {
    const p = proj(); if (!p) return;
    if (p.columns.length) {
      alert('This project already has comparison columns. Demo data loads onto an empty project — create a new project first.');
      return;
    }
    loadDemoData(p);
    touch(p); render();
  },

  toggleConfirm(k) { const p = proj(); p.confirmed[k] = !p.confirmed[k]; touch(p); render(); },
  pickRec(colId) {
    // BRD 2.7: changing the selection updates the highlight; selecting the
    // already-recommended insurer again UNSELECTS it and clears the highlight.
    const p = proj();
    p.recommended = p.recommended === colId ? null : colId;
    touch(p); render();
  },
  addColumn() {
    const p = proj();
    p.columns.push({ id: 'm' + (p.manualSeq++), name: 'Free-format column', manual: true, data: {}, debt: '' });
    touch(p); render();
  },
  removeColumn(colId) {
    const p = proj();
    p.columns = p.columns.filter(c => c.id !== colId);
    if (p.recommended === colId) p.recommended = null;
    p.credit.forEach(r => delete r.offers[colId]);
    touch(p); render();
  },
  openSource(caption) { state.source = { caption }; render(); },
  closeSource() { state.source = null; render(); },
  modalCard() { /* click shield: stops card clicks reaching the overlay's closeSource */ },

  addCredit() {
    const p = proj();
    p.credit.push({ id: uid(), buyer: '', reg: '', req: '', offers: {} });
    touch(p); render();
  },
  removeCredit(rowId) {
    const p = proj();
    p.credit = p.credit.filter(r => r.id !== rowId);
    touch(p); render();
  },

  flipType() { const p = proj(); p.projectType = p.projectType === 'new' ? 'renewal' : 'new'; touch(p); render(); },
  async exportPdf() {
    const p = proj();
    if (!allConfirmed(p)) return;
    if (await downloadExport('pdf')) { p.exported = true; p.status = 'ready'; touch(p); render(); }
  },
  async exportPpt() {
    const p = proj();
    if (!allConfirmed(p)) return;
    if (await downloadExport('pptx')) { p.exported = true; p.status = 'ready'; touch(p); render(); }
  },
  exportLimitsXlsx() { downloadExport('limits-xlsx'); },
};

/* ── Presentation export (BRD 2.8) — server renders PPTX/PDF/xlsx ──── */
const CONFIRM_FIELD_MAP = {
  premium: 'estimated_annual_premium_exc_ipt',
  indemnity: 'indemnity',
  excess: 'excess',
  maxLiability: 'max_annual_liability',
};

function buildPresentationPayload(p) {
  const columns = p.columns.map(col => {
    const values = {};
    for (const f of FIELDS) values[f.key] = cellValue(p, col, f) || '';
    return { id: col.id, name: col.name, values };
  });
  return {
    client_name: p.clientName || 'Client',
    reference: p.ref || '',
    project_type: p.projectType === 'renewal' ? 'renewal' : 'new',
    columns,
    recommended_id: p.recommended,
    approached_insurers: p.approached
      .map(id => (INSURERS.find(i => i.id === id) || {}).name)
      .filter(Boolean),
    credit_limits: p.credit.map(r => ({
      buyer: r.buyer || '', company_number: r.reg || '',
      required: r.req || '', offers: r.offers || {},
    })),
    notes: p.notes || '',
    reasons: p.reasons || '',
    confirmed_fields: Object.keys(p.confirmed)
      .filter(k => p.confirmed[k])
      .map(k => CONFIRM_FIELD_MAP[k])
      .filter(Boolean),
  };
}

async function downloadExport(format) {
  const p = proj(); if (!p) return false;
  try {
    const res = await fetch('/generate-presentation?format=' + format, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPresentationPayload(p)),
    });
    if (!res.ok) {
      let detail = 'HTTP ' + res.status;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      alert('Export failed: ' + detail);
      return false;
    }
    const blob = await res.blob();
    const match = (res.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = match ? match[1]
      : (p.clientName || 'presentation') + '.' + (format === 'limits-xlsx' ? 'xlsx' : format);
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    return true;
  } catch (err) {
    alert('Export failed: ' + (err.message || 'network error'));
    return false;
  }
}

/* ── Event delegation ──────────────────────────────────────────────── */
document.addEventListener('click', e => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const fn = ACTIONS[el.dataset.act];
  if (fn) fn(el.dataset.arg, el.dataset.arg2);
});

document.addEventListener('change', e => {
  const el = e.target.closest('[data-edit]');
  if (!el) return;
  const p = proj();
  const v = el.value;
  switch (el.dataset.edit) {
    case 'proj': if (p) { p[el.dataset.part] = v; touch(p); } break;
    case 'colname': {
      const col = p && p.columns.find(c => c.id === el.dataset.col);
      if (col) { col.name = v; touch(p); }
      break;
    }
    case 'cell': {
      const col = p && p.columns.find(c => c.id === el.dataset.col);
      if (col) {
        const k = el.dataset.field;
        // An edited value no longer matches its source page verbatim, so the
        // page link is cleared on change; a broker touching the cell also
        // counts as human verification, clearing any AI-uncertain flag.
        const prev = col.data[k];
        const unchanged = prev && prev.value === v;
        const wasUncertain = prev && prev.conf === 'uncertain';
        col.data[k] = { value: v, page: unchanged ? prev.page : null, conf: 'high' };
        touch(p);
        // Change fires on blur, so re-rendering to drop the amber
        // uncertain highlight doesn't steal focus mid-edit.
        if (wasUncertain) render();
      }
      break;
    }
    case 'credit': {
      const row = p && p.credit.find(r => r.id === el.dataset.row);
      if (row) {
        if (el.dataset.part === 'offer') row.offers[el.dataset.col] = v;
        else row[el.dataset.part] = v;
        touch(p);
      }
      break;
    }
    case 'notes': if (p) { p.notes = v; touch(p); } break;
    case 'reasons': if (p) { p.reasons = v; touch(p); } break;
  }
});

document.addEventListener('input', e => {
  if (e.target.id === 'proj-search') {
    state.projSearch = e.target.value;
    const rows = document.getElementById('proj-rows');
    if (rows) rows.innerHTML = projectRowsHtml();
  }
});

document.addEventListener('change', e => {
  const map = { 'file-quote': 'quote', 'file-limits': 'limits', 'file-expiring': 'expiring' };
  const kind = map[e.target.id];
  if (kind && e.target.files && e.target.files.length) {
    const files = Array.from(e.target.files);  // copy before clearing the input
    e.target.value = null;
    uploadFiles(kind, files);
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && state.screen === 'login') ACTIONS.signIn();
  if (e.key === 'Escape' && state.source) ACTIONS.closeSource();
});

/* ── Drag-and-drop upload (BRD 2.1: drag-and-drop with picker fallback) ── */
document.addEventListener('dragover', e => {
  const zone = e.target.closest('[data-drop]');
  if (zone) {
    e.preventDefault();
    zone.style.borderColor = 'var(--accent)';
    zone.style.background = 'var(--accent-soft)';
  }
});
document.addEventListener('dragleave', e => {
  const zone = e.target.closest('[data-drop]');
  if (zone && !zone.contains(e.relatedTarget)) {
    zone.style.borderColor = '';
    zone.style.background = '';
  }
});
document.addEventListener('drop', e => {
  const zone = e.target.closest('[data-drop]');
  if (!zone) return;
  e.preventDefault();
  zone.style.borderColor = '';
  zone.style.background = '';
  const files = Array.from(e.dataTransfer.files);
  if (files.length) uploadFiles(zone.dataset.drop, files);
});

/* ── Boot ──────────────────────────────────────────────────────────── */
load();
render();
loadInsurerConfig();  // standing list + debt rule from config, not code
