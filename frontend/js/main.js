/* Entry point: user actions + event delegation + boot.
   Every clickable element carries data-act; every editable one data-edit. */

import { downloadExport, loadInsurerConfig, uploadFiles } from './api.js';
import {
  boot, createProject, loadProjects, proj, save, setUser, state, touch, uid,
} from './state.js';
import { allConfirmed, projectRowsHtml, render } from './views.js';

const ACTIONS = {
  async signIn() {
    const email = (document.getElementById('login-email').value || '').trim();
    const password = document.getElementById('login-pass').value || '';
    if (!email) { document.getElementById('login-email').focus(); return; }
    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        alert(res.status === 401
          ? 'Wrong email or password.'
          : 'Sign-in failed — try again.');
        return;
      }
    } catch (e) { alert('Server unreachable — try again.'); return; }
    setUser(email);
    await loadProjects();
    state.screen = 'projects';
    render();
  },
  async signOut() {
    try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) {}
    state.user = null; state.projects = []; state.currentId = null;
    state.screen = 'login';
    render();
  },
  noopLink() { /* anchor handles itself (download); row click must not fire */ },
  toProjects() { state.screen = 'projects'; render(); },
  newProject() { createProject(); save(); state.screen = 'setup'; render(); },
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
    // Drop the upload card that produced this column, so the file list and
    // the declined-insurers logic stay truthful (and the file can be
    // re-uploaded cleanly later).
    p.files = p.files.filter(f => f.colId !== colId);
    touch(p); render();
  },
  openSource(colId, page) {
    const p = proj();
    const col = p && p.columns.find(c => c.id === colId);
    state.source = {
      caption: (col ? col.name : 'document') + ' · p' + page,
      docId: col ? col.docId : null,
      page: Number(page) || 1,
    };
    render();
  },
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
        // Change fires on blur, so re-rendering to refresh the computed
        // Total row doesn't steal focus mid-edit.
        render();
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
render();                       // login screen paints immediately
boot().then(render);            // an existing session goes to the list
loadInsurerConfig();  // standing list + debt rule from config, not code
