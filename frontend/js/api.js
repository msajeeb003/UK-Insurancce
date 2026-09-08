/* Backend wiring: insurer config, document upload/extraction, and
   presentation export. Every call goes to the FastAPI backend. */

import {
  CONFIRM_FIELD_MAP, DOC_TYPE_LABELS, FIELDS, INSURERS, MAX_QUOTES, setInsurers,
} from './constants.js';
import { proj, touch, uid } from './state.js';
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

function kindLabel(kind) {
  return kind === 'limits' ? 'credit-limit doc' : kind === 'expiring' ? 'expiring policy' : 'quote';
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
    existing.fileName = entry.name;
    entry.colId = existing.id;
    entry.meta += ' · updated existing column';
    mergeBuyers(p, existing.id, d.buyer_credit_limits);
    return;
  }

  const col = {
    id: uid(), name: colName,
    manual: false, expiring: kind === 'expiring',
    fileName: entry.name, data: freshData,
    debt: ruleDebt,
  };
  if (kind === 'expiring') p.columns.unshift(col); else p.columns.push(col);
  entry.colId = col.id;
  mergeBuyers(p, col.id, d.buyer_credit_limits);
}

/* ── Presentation export (BRD 2.8) — server renders PPTX/PDF/xlsx ────── */
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

export async function downloadExport(format) {
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
