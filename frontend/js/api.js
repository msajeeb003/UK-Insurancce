/* Backend wiring: insurer config, document upload/extraction, and
   presentation export. Every call goes to the FastAPI backend. */

import {
  CONFIRM_FIELD_MAP, DOC_TYPE_LABELS, FIELDS, INSURERS, MAX_QUOTES, setInsurers,
} from './constants.js';
import { proj, state, touch, uid } from './state.js';
import { cellValue, render } from './views.js';

/* ── Standing insurer list (configuration, not code) ─────────────────── */
export async function loadInsurerConfig() {
  try {
    const res = await fetch('/insurers');
    if (!res.ok) return;
    const list = (await res.json()).insurers;
    if (Array.isArray(list) && list.length) {
      setInsurers(list.map(i => ({
        id: i.id, name: i.name, debtIncl: i.debt_collection === 'included',
      })));
      render();
    }
  } catch (e) { /* fallback constant stays in effect */ }
}

function debtRuleFor(insurerName) {
  // Fallback only — the server's set_fields normally supplies this.
  // BRD 2.4: unmatched insurers default to Outsourced.
  if (!insurerName) return 'Outsourced';
  const hit = INSURERS.find(i => insurerName.toLowerCase().includes(i.name.toLowerCase())
    || i.name.toLowerCase().includes(insurerName.toLowerCase()));
  return hit && hit.debtIncl ? 'Included' : 'Outsourced';
}

function mergeBuyers(p, colId, buyers, pendKey) {
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
    if (colId && b.limit_offered) {
      row.offers[colId] = b.limit_offered;
    } else if (pendKey && b.limit_offered) {
      // Schedule arrived before its quote: park the offer under the
      // insurer's key so it attaches when that column is created.
      row.pending = row.pending || {};
      row.pending[pendKey] = b.limit_offered;
    }
  }
}

/* Attach offers parked by mergeBuyers once the insurer's column exists. */
function attachPendingOffers(p, col) {
  const keys = [col.matched, col.name].filter(Boolean).map(k => k.toLowerCase());
  for (const row of p.credit) {
    if (!row.pending) continue;
    for (const key of Object.keys(row.pending)) {
      if (keys.some(k => k === key || k.includes(key) || key.includes(k))) {
        if (!row.offers[col.id]) row.offers[col.id] = row.pending[key];
        delete row.pending[key];
      }
    }
    if (!Object.keys(row.pending).length) delete row.pending;
  }
}

function kindLabel(kind) {
  return kind === 'limits' ? 'credit-limit doc' : kind === 'expiring' ? 'expiring policy' : 'quote';
}

async function readDetail(res) {
  let detail = 'HTTP ' + res.status;
  try { detail = (await res.json()).detail || detail; } catch (e) {}
  return detail;
}

/* Session gone (expired, or the server was redeployed): back to sign-in. */
function sessionExpired() {
  alert('Your session has expired — please sign in again.');
  state.user = null;
  state.screen = 'login';
  render();
}

/* ── Upload -> POST /extract-quote ───────────────────────────────────── */
export async function uploadFiles(kind, fileList) {
  const p = proj(); if (!p) return;
  let files = Array.from(fileList);

  // Same file uploaded twice (double-click, re-picked by mistake): skip it.
  // A previous FAILED attempt is the exception — re-uploading is the retry,
  // so the old error card is removed and the file goes through again.
  const isDuplicate = f => p.files.some(e =>
    e.kind === kind && e.name === f.name && e.status !== 'error');
  const skipped = files.filter(isDuplicate).map(f => f.name);
  files = files.filter(f => !isDuplicate(f));
  for (const f of files) {
    p.files = p.files.filter(e =>
      !(e.kind === kind && e.name === f.name && e.status === 'error'));
  }
  if (skipped.length) {
    alert('Already uploaded — skipped:\n· ' + skipped.join('\n· ') +
      '\n\nTo replace a quote with a new version, upload the newer file: ' +
      'its insurer column is updated in place, never duplicated.');
    if (!files.length) { render(); return; }
  }

  if (kind === 'quote') {
    const room = MAX_QUOTES - p.files.filter(
      f => f.kind === 'quote' && f.status !== 'error').length;
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
      fd.append('project_id', p.id);   // BRD S4: documents retained
      fd.append('doc_kind', kind);
      const res = await fetch('/extract-quote', { method: 'POST', body: fd });
      if (res.status === 401) {
        // Session expired mid-work (e.g. a redeploy): back to sign-in —
        // the document is fine, so drop the card instead of flagging it.
        p.files = p.files.filter(e => e.id !== entry.id);
        sessionExpired();
        return;
      }
      if (!res.ok) throw new Error(await readDetail(res));
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

function applyExtraction(p, entry, body, kind) {
  const d = body.data;
  const insurer = d.insurer && d.insurer.value ? d.insurer.value : null;
  // Standing-list name the server's alias matching resolved (e.g. a Zurich
  // schedule issued as "The Marine Insurance Company Limited" -> "Zurich").
  const matched = body.set_fields && body.set_fields.debt_collection_support
    ? body.set_fields.debt_collection_support.matched_insurer : null;
  const review = body.review || { missing_fields: [], uncertain_fields: [] };
  const nCheck = review.uncertain_fields.length;
  entry.status = 'extracted';
  entry.docId = body.meta.document_id || null;
  // When the document's entity wording maps to a different standing-list
  // insurer, say so on the file card so the broker can verify the match.
  const matchNote = matched && insurer
    && matched.toLowerCase() !== insurer.toLowerCase()
    ? ' (matched: ' + matched + ')' : '';
  entry.meta = (insurer || 'Unrecognised insurer') + matchNote
    + ' · ' + (DOC_TYPE_LABELS[d.document_type] || kindLabel(kind))
    + (body.meta.extraction_engine === 'azure_document_intelligence' ? ' (scanned)' : '')
    + ' · ' + body.meta.page_count + ' pages'
    + (nCheck ? ' · ' + nCheck + ' value' + (nCheck === 1 ? '' : 's') + ' to verify' : '');

  // A credit-limit schedule never becomes a comparison column — even when
  // it arrives through the quotes slot. Its offers attach to the column of
  // the same insurer, matched by the standing-list name first (so a Zurich
  // schedule finds the Zurich column whatever entity name it prints).
  if (kind === 'limits' || d.document_type === 'credit_limit_schedule') {
    const col =
      (matched && p.columns.find(c => c.matched === matched))
      || (insurer && p.columns.find(c =>
        c.name.toLowerCase().includes(insurer.toLowerCase())
        || insurer.toLowerCase().includes(c.name.toLowerCase())))
      || null;
    mergeBuyers(p, col ? col.id : null, d.buyer_credit_limits,
      (matched || insurer || '').toLowerCase() || null);
    if (col) entry.meta += ' · limits added to ' + col.name;
    return;
  }

  // BRD 2.4: debt collection support is set by the server-side insurer
  // rule (backend/config/insurers.json), never extracted; editable per column.
  const ruleDebt = body.set_fields && body.set_fields.debt_collection_support
    ? body.set_fields.debt_collection_support.value : debtRuleFor(insurer);
  const colName = kind === 'expiring'
    ? 'Expiring — ' + (insurer || 'policy')
    : (insurer || entry.name.replace(/\.pdf$/i, ''));

  const freshData = {};
  for (const f of FIELDS) {
    if (f.set) continue;
    const sv = d[f.key];
    if (sv && typeof sv === 'object') {
      freshData[f.key] = { value: sv.value || '', page: sv.page, conf: sv.confidence };
    }
  }

  // One automatic column per insurer (BRD 2.1: a genuine second quote from
  // the same insurer gets a manual free-format column). A duplicate or
  // newer upload UPDATES the existing column in place — same column id, so
  // the recommendation and credit-limit offers stay linked.
  const existing = p.columns.find(c =>
    !c.manual && c.name.toLowerCase() === colName.toLowerCase());
  if (existing) {
    existing.data = freshData;
    existing.debt = ruleDebt;
    existing.matched = matched;
    existing.docId = entry.docId;
    existing.fileName = entry.name;
    entry.colId = existing.id;
    entry.meta += ' · updated existing column';
    mergeBuyers(p, existing.id, d.buyer_credit_limits);
    attachPendingOffers(p, existing);
    return;
  }

  const col = {
    id: uid(), name: colName,
    manual: false, expiring: kind === 'expiring',
    fileName: entry.name, docId: entry.docId, data: freshData,
    debt: ruleDebt, matched,
  };
  if (kind === 'expiring') p.columns.unshift(col); else p.columns.push(col);
  entry.colId = col.id;
  mergeBuyers(p, col.id, d.buyer_credit_limits);
  attachPendingOffers(p, col);
}

/* ── Presentation export (BRD 2.8) — server renders PPTX/PDF/xlsx ────── */
function buildPresentationPayload(p) {
  const columns = p.columns.map(col => {
    const values = {};
    for (const f of FIELDS) values[f.key] = cellValue(p, col, f) || '';
    return { id: col.id, name: col.name, matched: col.matched || null, values };
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

export async function downloadExport(format) {
  const p = proj(); if (!p) return false;
  try {
    const res = await fetch('/generate-presentation?format=' + format
      + '&project_id=' + encodeURIComponent(p.id), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPresentationPayload(p)),
    });
    if (res.status === 401) { sessionExpired(); return false; }
    if (!res.ok) {
      alert('Export failed: ' + await readDetail(res));
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
