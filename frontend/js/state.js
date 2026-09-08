/* Application state + persistence (localStorage for projects,
   sessionStorage for the signed-in user) and small shared utilities. */

export const state = {
  screen: 'login',
  user: null,               // { email, initials }
  projects: [],             // persisted
  currentId: null,
  source: null,             // { caption }
  projSearch: '',
  projFilter: 'All',
};

export function load() {
  try {
    state.projects = JSON.parse(localStorage.getItem('qct_projects') || '[]');
    const u = sessionStorage.getItem('qct_user');
    if (u) { state.user = JSON.parse(u); state.screen = 'projects'; }
  } catch (e) { /* fresh start on corrupt storage */ }
}

export function save() {
  try { localStorage.setItem('qct_projects', JSON.stringify(state.projects)); } catch (e) {}
}

export const proj = () => state.projects.find(p => p.id === state.currentId) || null;

export const uid = () => Math.random().toString(36).slice(2, 9);

export const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export function todayLabel() {
  return new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

export function monthLabel() {
  return new Date().toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
}

/* ── Project factory ─────────────────────────────────────────────────── */
export function createProject() {
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

export function touch(p) { p.updated = todayLabel(); save(); }
