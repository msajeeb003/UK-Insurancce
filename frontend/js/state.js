/* Application state, server persistence (BRD 2.9: projects are stored
   server-side and shared by all users) and small shared utilities. */

export const state = {
  screen: 'login',
  user: null,               // { email, initials }
  projects: [],             // loaded from the server
  currentId: null,
  source: null,             // { caption, docId, page }
  projSearch: '',
  projFilter: 'All',
};

export function setUser(email) {
  const parts = email.split('@')[0].split(/[._-]/).filter(Boolean);
  const initials = (parts.length > 1
    ? parts[0][0] + parts[1][0] : email.slice(0, 2)).toUpperCase();
  state.user = { email, initials };
}

export async function loadProjects() {
  const res = await fetch('/projects');
  if (res.ok) state.projects = (await res.json()).projects || [];
}

/* Session restore on page load: an existing cookie session goes straight
   to the project list (BRD S1: Next -> Project list). */
export async function boot() {
  try {
    const me = await fetch('/auth/me');
    if (me.ok) {
      setUser((await me.json()).email);
      await loadProjects();
      state.screen = 'projects';
    }
  } catch (e) { /* server unreachable: stay on the login screen */ }
}

/* Debounced per-project save — every edit reaches the server without a
   request per keystroke. */
const saveTimers = {};
export function save(p) {
  p = p || proj();
  if (!p) return;
  clearTimeout(saveTimers[p.id]);
  saveTimers[p.id] = setTimeout(() => {
    fetch('/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: p.id, state: p }),
    }).catch(() => {});
  }, 500);
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
