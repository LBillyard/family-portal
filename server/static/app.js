/* Family Portal — live app */

// --- Theme (light / dark / system) ---------------------------------------
// Applied as early as possible (module top-level runs before load()/render)
// to avoid a flash. A tiny inline <head> guard in index.html handles the very
// first paint; these helpers keep everything in sync afterwards.
const THEME_KEY = 'hub-theme';
const THEME_ICONS = {
  moon: '<svg viewBox="0 0 20 20" fill="currentColor"><path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"/></svg>',
  sun: '<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clip-rule="evenodd"/></svg>',
};

function getThemePref() {
  const v = localStorage.getItem(THEME_KEY);
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
}

// Apply a theme preference by driving the root data-theme attribute.
// 'system' removes the attribute so the prefers-color-scheme media query governs.
function applyTheme(pref) {
  if (pref === 'light' || pref === 'dark') {
    document.documentElement.dataset.theme = pref;
  } else {
    delete document.documentElement.dataset.theme;
  }
  updateThemeToggleIcon();
}

// The theme actually in effect right now (resolving 'system' against the OS).
function effectiveTheme() {
  const pref = getThemePref();
  if (pref === 'light' || pref === 'dark') return pref;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// Persist + apply a preference, and reflect it in any visible controls.
function setThemePref(pref) {
  localStorage.setItem(THEME_KEY, pref);
  applyTheme(pref);
  document.querySelectorAll('.theme-seg').forEach((b) => b.classList.toggle('active', b.dataset.theme === pref));
}

// Header quick-toggle: flip between light and dark (leaves 'system' behind).
function toggleTheme() {
  setThemePref(effectiveTheme() === 'dark' ? 'light' : 'dark');
}

// Header button shows a moon while light (tap → dark) and a sun while dark.
function updateThemeToggleIcon() {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const dark = effectiveTheme() === 'dark';
  btn.innerHTML = dark ? THEME_ICONS.sun : THEME_ICONS.moon;
  btn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
  btn.setAttribute('aria-label', btn.title);
}

// Apply the saved preference immediately on script load.
applyTheme(getThemePref());
// Keep 'system' choices live when the OS flips light/dark.
if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
    if (getThemePref() === 'system') updateThemeToggleIcon();
  });
}

const API = '/api';
let store = {};
let currentUser = null;
const DOC_CATEGORY_MAP = {
  Insurance: 'insurance',
  'Passport & ID': 'passport',
  'MOT & vehicle': 'mot',
  'Legal & wills': 'legal',
  Medical: 'medical',
  'Finance & tax': 'finance',
  Property: 'property',
  Other: 'other',
};

const DOC_CATEGORY_LABELS = {
  insurance: 'Insurance',
  passport: 'Passport & ID',
  mot: 'MOT & vehicle',
  legal: 'Legal & wills',
  medical: 'Medical',
  finance: 'Finance & tax',
  property: 'Property',
  other: 'Other',
};

let vaultFilter = 'all';
let mediaFilter = 'all';
let mediaStorage = null;
let tripFilter = 'all';
let calView = 'month';
let calCursor = null;
let activeModalKey = null;
// Calendar member filter — user ids whose events are hidden (shared/null events always show).
const calFilterHidden = new Set();

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (res.status === 401 && !path.includes('/auth/')) {
    currentUser = null;
    showLogin();
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    let detail = err.detail;
    if (Array.isArray(detail)) {
      // FastAPI 422 validation errors: [{loc: [...], msg: '...'}]
      detail = detail.map((d) => `${(d.loc || []).join('.')}: ${d.msg}`).join('; ');
    } else if (detail && typeof detail === 'object') {
      detail = JSON.stringify(detail);
    }
    throw new Error(detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

const ICONS = {
  plus: '<path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>',
  calendar: '<path fill-rule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z" clip-rule="evenodd"/>',
  money: '<path d="M4 4a2 2 0 00-2 2v1h16V6a2 2 0 00-2-2H4z"/><path fill-rule="evenodd" d="M18 9H2v5a2 2 0 002 2h12a2 2 0 002-2V9z" clip-rule="evenodd"/>',
  user: '<path fill-rule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clip-rule="evenodd"/>',
  pin: '<path fill-rule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clip-rule="evenodd"/>',
  spark: '<path d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z"/>',
  check: '<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>',
};

function icon(name) {
  return `<svg class="btn-icon-svg" viewBox="0 0 20 20" fill="currentColor">${ICONS[name] || ''}</svg>`;
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str ?? '';
  // textContent escapes < > & but NOT quotes, so the result is unsafe inside a
  // double/single-quoted HTML attribute (attribute-breakout XSS). Escape quotes too
  // so esc() is safe in BOTH text and attribute contexts across the whole app.
  return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const fmt = {
  gbp(n) {
    return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n);
  },
  date(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  },
  time(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  },
  datetime(iso) {
    if (!iso) return '—';
    return `${fmt.date(iso)} · ${fmt.time(iso)}`;
  },
  relative(iso) {
    if (!iso) return 'never';
    const then = new Date(iso).getTime();
    if (isNaN(then)) return 'never';
    const min = Math.floor((Date.now() - then) / 60000);
    if (min < 0) return 'just now';
    if (min < 1) return 'just now';
    if (min < 60) return `${min} min ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} hr ago`;
    const days = Math.floor(hr / 24);
    if (days === 1) return 'yesterday';
    if (days < 7) return `${days} days ago`;
    return fmt.date(iso);
  },
  greeting() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  },
  todayLabel() {
    return new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  },
  fileSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  },
};

// Only allow real hex colours into style="" attributes — anything else falls back.
function safeColour(c, fallback = '#718096') {
  return /^#[0-9a-fA-F]{3,8}$/.test(c || '') ? c : fallback;
}

function userColour(users, id) {
  return safeColour(users.find((u) => u.id === id)?.colour);
}
function userName(users, id) {
  // null/undefined id = shared between the household
  return esc(users.find((u) => u.id === id)?.name || id || 'Both');
}

// Resolve a display name picked in a modal back to a user id; 'Both'/'Either' → null (shared).
function resolveUserIdByName(name) {
  const users = store.dashboard?.users || [];
  return users.find((u) => u.name === name)?.id ?? null;
}

// Option list for assignee selects — built at openModal time so renames propagate.
// A shared option ('Both'/'Either') is only offered where the backend column is
// nullable (tasks); events/appointments have a NOT NULL owner, so pass no label.
function userOptionList(sharedLabel) {
  const users = store.dashboard?.users || [];
  const names = users.map((u) => u.name);
  return sharedLabel ? [...names, sharedLabel] : names;
}

function todayIsoDate(plusDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + plusDays);
  return d.toISOString().slice(0, 10);
}

const MODALS = {
  'add-event': {
    title: 'Add event',
    desc: 'Creates a portal event and optionally syncs to Google Calendar.',
    fields: [
      { label: 'Title', type: 'text', placeholder: 'e.g. Date night' },
      { label: 'Date', type: 'date', value: () => todayIsoDate() },
      { label: 'Time', type: 'time', value: '19:00' },
      { label: 'Assigned to', type: 'select', options: () => userOptionList() },
      { label: 'Location', type: 'text', value: '' },
      { label: 'Google calendar', type: 'select', options: ['Default'] },
    ],
  },
  'log-expense': {
    title: 'Log transaction',
    desc: 'Manual income or expense entry.',
    fields: [
      { label: 'Description', type: 'text', placeholder: 'e.g. Weekly shop' },
      { label: 'Amount (£)', type: 'number', value: '' },
      { label: 'Category', type: 'select', options: ['Groceries', 'Transport', 'Eating out', 'Income'] },
      { label: 'Account', type: 'select', options: [] },
      { label: 'Date', type: 'date', value: () => todayIsoDate() },
    ],
  },
  'add-bill': {
    title: 'Add recurring bill',
    desc: 'Track monthly or annual payments.',
    fields: [
      { label: 'Bill name', type: 'text', placeholder: 'e.g. Spotify' },
      { label: 'Amount (£)', type: 'number', value: '' },
      { label: 'Due day of month', type: 'number', value: '1' },
      { label: 'Category', type: 'select', options: () => BILL_CATEGORIES },
      { label: 'Recurrence', type: 'select', options: ['monthly', 'quarterly', 'yearly', 'weekly'] },
    ],
  },
  'add-appointment': {
    title: 'New appointment',
    desc: 'Health, dental, car MOT, vet — with optional calendar sync.',
    fields: [
      { label: 'Title', type: 'text', placeholder: 'e.g. GP appointment' },
      { label: 'Provider', type: 'text', placeholder: 'e.g. Oakwood Medical' },
      { label: 'Date & time', type: 'datetime-local', value: '' },
      { label: 'Location', type: 'text', placeholder: 'e.g. High Street surgery' },
      { label: 'Person', type: 'select', options: () => userOptionList() },
      { label: 'Category', type: 'select', options: ['Health', 'Dental', 'Car', 'Vet'] },
      { label: 'Remind me (days before)', type: 'number', value: '2' },
    ],
  },
  'add-task': {
    title: 'Add shared task',
    desc: 'Household to-do assigned to one or both of you.',
    fields: [
      { label: 'Task', type: 'text', placeholder: 'e.g. Book airport parking' },
      { label: 'Assign to', type: 'select', options: () => userOptionList('Either') },
      { label: 'Due date', type: 'date', value: () => todayIsoDate(3) },
      { label: 'Priority', type: 'select', options: ['High', 'Medium', 'Low'] },
      { label: 'Remind me', type: 'datetime-local', value: '' },
    ],
  },
  'new-trip': {
    title: 'New holiday trip',
    desc: 'Start from scratch or promote a saved AI idea.',
    fields: [
      { label: 'Trip name', type: 'text', placeholder: 'e.g. Summer city break' },
      { label: 'Destination', type: 'text', placeholder: 'e.g. Barcelona, Spain — used for weather' },
      { label: 'Status', type: 'select', options: ['Idea', 'Planning', 'Booked'] },
      { label: 'Start date', type: 'date', value: '' },
      { label: 'End date', type: 'date', value: '' },
      { label: 'Budget (£)', type: 'number', value: '800' },
    ],
  },
  'connect-google': {
    title: 'Connect Google Calendar',
    desc: 'OAuth sign-in — read and write events per person.',
    fields: [
      { label: 'Account', type: 'select', options: ['Luke', 'Laura'] },
    ],
  },
  'holiday-ai': {
    title: 'Generate holiday ideas',
    desc: 'OpenRouter picks the best model for travel suggestions.',
    fields: [
      { label: 'Prompt', type: 'textarea', value: 'Beach holiday under £2k in August, max 4 hour flight from UK' },
      { label: 'Model', type: 'select', options: ['Auto (OpenRouter)', 'GPT-4o mini', 'Claude Sonnet'] },
    ],
  },
  search: {
    title: 'Search everything',
    desc: 'Events, bills, appointments, tasks and trips — one search bar.',
    fields: [{ label: 'Search', type: 'text', value: 'dentist' }],
  },
  'add-document': {
    title: 'Add document reminder',
    desc: 'Track expiry without a file — or use the Vault tab to upload.',
    fields: [
      { label: 'Document name', type: 'text', value: 'Home insurance' },
      { label: 'Category', type: 'select', options: ['Insurance', 'Passport & ID', 'MOT & vehicle', 'Legal & wills', 'Medical', 'Finance & tax', 'Property', 'Other'] },
      { label: 'Expiry date', type: 'date', value: '' },
      { label: 'Notes', type: 'text', value: '' },
    ],
  },
};

function showToast(msg, isError = false) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = isError
    ? `<strong style="color:#f87171">Error:</strong> ${esc(msg)}`
    : esc(msg);
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function showLogin() {
  document.getElementById('login-overlay').hidden = false;
  // Only show the dismiss button when a signed-in user is previewing the screen —
  // an unauthenticated visitor must not be able to reveal the app shell.
  const closeBtn = document.getElementById('login-close');
  if (closeBtn) closeBtn.hidden = !currentUser;
}

function hideLogin() {
  document.getElementById('login-overlay').hidden = true;
}

function openModal(key) {
  const def = MODALS[key];
  if (!def) return;
  activeModalKey = key;
  closeModal();
  closeNotif();
  const fields = def.fields
    .map((f) => {
      // Values/options can be functions so defaults (today's date, live user list) are computed at open time.
      const val = typeof f.value === 'function' ? f.value() : f.value;
      if (f.type === 'select') {
        const opts = typeof f.options === 'function' ? f.options() : f.options;
        return `<label>${f.label}<select data-key="${esc(f.label)}">${opts.map((o) => `<option>${esc(o)}</option>`).join('')}</select></label>`;
      }
      if (f.type === 'textarea') {
        return `<label>${f.label}<textarea rows="3" data-key="${esc(f.label)}">${esc(val || '')}</textarea></label>`;
      }
      return `<label>${f.label}<input type="${f.type}" data-key="${esc(f.label)}" value="${esc(val || '')}" placeholder="${esc(f.placeholder || '')}"></label>`;
    })
    .join('');

  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header">
        <h3>${def.title}</h3>
        <p>${def.desc}</p>
      </div>
      <div class="wf-modal-body">
        <div class="wf-modal-note">Data saves to your local SQLite database</div>
        ${fields}
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary" id="modal-cancel">Cancel</button>
        <button type="button" class="btn btn-primary" id="modal-save">Save</button>
      </div>
    </div>`;

  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('modal-cancel').onclick = closeModal;
  document.getElementById('modal-save').onclick = () => submitModal(key);

  // Drive the Google-calendar picker from connected accounts (write-back target)
  if (key === 'add-event') {
    const calLabel = [...document.querySelectorAll('.wf-modal label')].find((l) => l.textContent.trim().startsWith('Google calendar'));
    const accts = store.settings?.google_accounts || [];
    const sel = calLabel?.querySelector('select');
    if (sel && accts.length) {
      sel.innerHTML = accts.map((a) => `<option value="${esc(a.id)}">${esc(a.email)}</option>`).join('');
    }
    // Hide the picker unless there's a real choice to make (2+ calendars).
    if (calLabel && accts.length < 2) calLabel.style.display = 'none';
  }

  // Drive the account picker from real accounts so IDs always resolve
  if (key === 'log-expense') {
    const accountLabel = [...document.querySelectorAll('.wf-modal label')].find((l) => l.textContent.trim().startsWith('Account'));
    const sel = accountLabel?.querySelector('select');
    const all = store.finances?.accounts || [];
    const preferred = all.filter((a) => a.type === 'current' || a.type === 'savings');
    const accounts = preferred.length ? preferred : all;
    if (sel) {
      if (accounts.length) {
        sel.innerHTML = accounts.map((a) => `<option>${esc(a.name)}</option>`).join('');
      } else {
        sel.innerHTML = '<option value="">No accounts yet</option>';
        sel.disabled = true;
        const saveBtn = document.getElementById('modal-save');
        if (saveBtn) saveBtn.disabled = true;
        accountLabel.insertAdjacentHTML('beforeend', '<span class="hint-small">Connect a bank or import a CSV first</span>');
      }
    }
  }
}

function readModalFields() {
  const modal = document.querySelector('.wf-modal');
  if (!modal) return {};
  const data = {};
  // Key by the explicit data-key, NOT label.textContent — a <select>'s option
  // text is part of the label's textContent, which would corrupt the key.
  modal.querySelectorAll('[data-key]').forEach((input) => {
    data[input.dataset.key] = input.value;
  });
  return data;
}

async function submitModal(key) {
  const f = readModalFields();
  try {
    if (key === 'add-event') {
      const dateVal = f['Date'];
      if (!dateVal) {
        showToast('Pick a date', true);
        return; // keep the modal open so nothing is lost
      }
      const timeVal = f['Time'] || '09:00';
      const start = dateVal.includes('T') ? dateVal : `${dateVal}T${timeVal}:00`;
      const calChoice = f['Google calendar'];
      await api('/events', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Title'],
          start,
          end: start,
          user_id: resolveUserIdByName(f['Assigned to']),
          location: f['Location'] || null,
          google_account_id: calChoice && calChoice !== 'Default' ? calChoice : null,
        }),
      });
    } else if (key === 'log-expense') {
      const accounts = store.finances?.accounts || [];
      const byName = Object.fromEntries(accounts.map((a) => [a.name, a.id]));
      const fallback = accounts.find((a) => a.type === 'current')?.id || accounts[0]?.id;
      await api('/transactions', {
        method: 'POST',
        body: JSON.stringify({
          description: f['Description'],
          amount: parseFloat(f['Amount (£)'] || f['Amount'] || 0),
          category: f['Category'],
          account_id: byName[f['Account']] || fallback,
          date: f['Date'] || undefined,
        }),
      });
    } else if (key === 'add-bill') {
      await api('/bills', {
        method: 'POST',
        body: JSON.stringify({
          name: f['Bill name'],
          amount: parseFloat(f['Amount (£)'] || 0),
          due_day: parseInt(f['Due day of month'], 10),
          category: f['Category'],
          recurrence: f['Recurrence'] || 'monthly',
        }),
      });
    } else if (key === 'add-appointment') {
      await api('/appointments', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Title'],
          provider: f['Provider'],
          datetime: f['Date & time'],
          location: f['Location'] || null,
          user_id: resolveUserIdByName(f['Person']),
          category: (f['Category'] || 'health').toLowerCase(),
          reminder_days: parseInt(f['Remind me (days before)'] || 2, 10),
        }),
      });
    } else if (key === 'add-task') {
      await api('/tasks', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Task'],
          assignee_id: resolveUserIdByName(f['Assign to']),
          due: f['Due date'] || null,
          priority: (f['Priority'] || 'medium').toLowerCase(),
          remind_at: f['Remind me'] || null,
        }),
      });
    } else if (key === 'new-trip') {
      await api('/holidays/trips', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Trip name'],
          destination: f['Destination'] || null,
          status: (f['Status'] || 'idea').toLowerCase(),
          start: f['Start date'] || null,
          end: f['End date'] || null,
          budget: parseFloat(f['Budget (£)'] || 0),
        }),
      });
    } else if (key === 'add-document') {
      await api('/documents', {
        method: 'POST',
        body: JSON.stringify({
          name: f['Document name'],
          category: DOC_CATEGORY_MAP[f['Category']] || 'other',
          expiry: f['Expiry date'] || '',
          expiry_date: f['Expiry date'] || null,
          notes: f['Notes'] || '',
        }),
      });
    } else if (key === 'holiday-ai') {
      await submitHolidayAI(f['Prompt'], f['Model']);
      return;
    } else {
      closeModal();
      showToast('Coming soon');
      return;
    }
    closeModal();
    showToast(`${MODALS[key].title} — saved`);
    await load();
  } catch (err) {
    showToast(err.message, true);
  }
}

function closeModal() {
  activeModalKey = null;
  document.getElementById('modal-root').innerHTML = '';
}

async function openConnectBankModal() {
  try {
    const data = await api('/banking/providers');
    if (!data.configured) {
      showToast('Add TrueLayer credentials to .env — see docs/BUILD.md', true);
      return;
    }
    const tiles = (data.providers || [])
      .map(
        (p) => `
      <button type="button" class="bank-provider-tile wf-action" data-action="connect-bank-provider" data-provider-id="${esc(p.id)}">
        <strong>${esc(p.name)}</strong>
        <span>${p.kind === 'card' ? 'Credit card' : 'Current account'}</span>
        ${p.note ? `<small>${esc(p.note)}</small>` : ''}
      </button>`
      )
      .join('');
    document.getElementById('modal-root').innerHTML = `
      <div class="modal-backdrop" id="modal-backdrop">
        <div class="modal modal-wide">
          <div class="modal-header">
            <h3>Connect a bank account</h3>
            <button class="modal-close wf-action" data-action="close-modal" type="button">×</button>
          </div>
          <div class="modal-body">
            <p style="margin-bottom:14px;color:var(--text-muted)">
              Secure Open Banking via TrueLayer. Connect each account once — Starling, Revolut, Amex and Virgin appear together on the Finances tab after syncing.
            </p>
            <div class="bank-provider-grid">${tiles}</div>
            <p style="margin-top:14px;font-size:0.8125rem;color:var(--text-muted)">
              Consent lasts 90 days (UK regulation). You'll need to reconnect periodically.
            </p>
          </div>
        </div>
      </div>`;
    activeModalKey = 'connect-bank';
  } catch (err) {
    showToast(err.message, true);
  }
}

async function submitHolidayAI(prompt, model) {
  const text = prompt || document.getElementById('ai-prompt-input')?.value;
  if (!text?.trim()) {
    showToast('Enter a prompt first', true);
    return;
  }
  const modelMap = {
    'Auto (OpenRouter)': null,
    'GPT-4o mini': 'openai/gpt-4o-mini',
    'Claude Sonnet': 'anthropic/claude-3.5-sonnet',
  };
  try {
    showToast('Generating ideas…');
    const res = await api('/holidays/ideas/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt: text, model: modelMap[model] || null }),
    });
    closeModal();
    showToast(`${res.ideas?.length || 3} holiday ideas saved`);
    switchTab('holidays');
    await load();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function uploadCsv(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API}/finances/import-csv`, { method: 'POST', body: form, credentials: 'include' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Import failed');
  }
  return res.json();
}

function openTransferModal() {
  const accounts = store.finances?.accounts || [];
  if (accounts.length < 2) {
    showToast('Need at least two accounts to transfer', true);
    return;
  }
  const opts = (selId) => accounts.map((a) => `<option value="${a.id}"${a.id === selId ? ' selected' : ''}>${esc(a.name)}</option>`).join('');
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Transfer between accounts</h3><p>Logs a paired debit and credit and updates balances.</p></div>
      <div class="wf-modal-body">
        <label class="field field-full"><span>From</span><select id="tr-from">${opts(accounts[0].id)}</select></label>
        <label class="field field-full"><span>To</span><select id="tr-to">${opts(accounts[1].id)}</select></label>
        <label class="field field-full"><span>Amount (£)</span><input type="number" id="tr-amount" min="0.01" step="0.01" value="50"></label>
        <label class="field field-full"><span>Note</span><input type="text" id="tr-note" value="Transfer"></label>
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="tr-save">Transfer</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('tr-save').onclick = async () => {
    const from_account = document.getElementById('tr-from').value;
    const to_account = document.getElementById('tr-to').value;
    const amount = parseFloat(document.getElementById('tr-amount').value);
    const note = document.getElementById('tr-note').value.trim();
    if (!amount || amount <= 0) return showToast('Enter an amount', true);
    if (from_account === to_account) return showToast('Choose two different accounts', true);
    try {
      const r = await api('/finances/transfer', { method: 'POST', body: JSON.stringify({ from_account, to_account, amount, note }) });
      closeModal();
      showToast(`Transferred ${fmt.gbp(r.amount)}: ${r.from} → ${r.to}`);
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

function openEditAppointmentModal(apptId) {
  const appt = (store.appointments?.appointments || []).find((a) => a.id === apptId);
  if (!appt) return showToast('Appointment not found', true);
  const users = store.appointments?.users || [];
  const userOpts = users.map((u) => `<option value="${u.id}"${u.id === appt.user_id ? ' selected' : ''}>${esc(u.name)}</option>`).join('');
  const catOpts = ['health', 'dental', 'car', 'vet', 'other'].map((c) => `<option value="${c}"${c === appt.category ? ' selected' : ''}>${c}</option>`).join('');
  const statusOpts = ['upcoming', 'completed', 'cancelled'].map((s) => `<option value="${s}"${s === appt.status ? ' selected' : ''}>${s}</option>`).join('');
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Edit appointment</h3><p>Update details, reassign, or change status.</p></div>
      <div class="wf-modal-body">
        <label class="field field-full"><span>Title</span><input type="text" id="ea-title" value="${esc(appt.title)}"></label>
        <label class="field field-full"><span>Provider</span><input type="text" id="ea-provider" value="${esc(appt.provider)}"></label>
        <label class="field field-full"><span>Date &amp; time</span><input type="datetime-local" id="ea-dt" value="${(appt.datetime || '').slice(0, 16)}"></label>
        <label class="field field-full"><span>Location</span><input type="text" id="ea-location" value="${esc(appt.location || '')}"></label>
        <label class="field field-full"><span>Person</span><select id="ea-user">${userOpts}</select></label>
        <label class="field field-full"><span>Category</span><select id="ea-cat">${catOpts}</select></label>
        <label class="field field-full"><span>Status</span><select id="ea-status">${statusOpts}</select></label>
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-ghost" id="ea-delete" style="margin-right:auto">Delete</button>
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="ea-save">Save</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('ea-save').onclick = async () => {
    try {
      await api(`/appointments/${apptId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: document.getElementById('ea-title').value.trim(),
          provider: document.getElementById('ea-provider').value.trim(),
          datetime: document.getElementById('ea-dt').value,
          location: document.getElementById('ea-location').value.trim(),
          user_id: document.getElementById('ea-user').value,
          category: document.getElementById('ea-cat').value,
          status: document.getElementById('ea-status').value,
        }),
      });
      closeModal();
      showToast('Appointment updated');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
  document.getElementById('ea-delete').onclick = async () => {
    if (!confirm('Delete this appointment?')) return;
    try {
      await api(`/appointments/${apptId}`, { method: 'DELETE' });
      closeModal();
      showToast('Appointment deleted');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

function openEditTripModal(tripId) {
  const trip = (store.holidays?.trips || []).find((t) => t.id === tripId);
  if (!trip) return showToast('Trip not found', true);
  const statusOpts = ['idea', 'planning', 'booked'].map((s) => `<option value="${s}"${s === trip.status ? ' selected' : ''}>${s}</option>`).join('');
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Edit trip</h3><p>Update dates, status and budget.</p></div>
      <div class="wf-modal-body">
        <label class="field field-full"><span>Title</span><input type="text" id="et-title" value="${esc(trip.title)}"></label>
        <label class="field field-full"><span>Destination</span><input type="text" id="et-destination" value="${esc(trip.destination || '')}" placeholder="e.g. Barcelona, Spain — used for weather"></label>
        <label class="field field-full"><span>Status</span><select id="et-status">${statusOpts}</select></label>
        <label class="field field-full"><span>Start date</span><input type="date" id="et-start" value="${(trip.start || '').slice(0, 10)}"></label>
        <label class="field field-full"><span>End date</span><input type="date" id="et-end" value="${(trip.end || '').slice(0, 10)}"></label>
        <label class="field field-full"><span>Budget (£)</span><input type="number" id="et-budget" min="0" step="1" value="${trip.budget || 0}"></label>
        <label class="field field-full"><span>Spent (£)</span><input type="number" id="et-spent" min="0" step="1" value="${trip.spent || 0}"></label>
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-ghost" id="et-delete" style="margin-right:auto">Delete</button>
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="et-save">Save</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('et-delete').onclick = async () => {
    if (!confirm('Delete this trip? Its checklist, packing list and document links go too.')) return;
    try {
      await api(`/holidays/trips/${tripId}`, { method: 'DELETE' });
      closeModal();
      showToast('Trip deleted');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
  document.getElementById('et-save').onclick = async () => {
    try {
      await api(`/holidays/trips/${tripId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: document.getElementById('et-title').value.trim(),
          destination: document.getElementById('et-destination').value.trim(),
          status: document.getElementById('et-status').value,
          start: document.getElementById('et-start').value || null,
          end: document.getElementById('et-end').value || null,
          budget: parseFloat(document.getElementById('et-budget').value) || 0,
          spent: parseFloat(document.getElementById('et-spent').value) || 0,
        }),
      });
      closeModal();
      showToast('Trip updated');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

function openEditMemberModal(userId) {
  const users = store.settings?.users || store.dashboard?.users || [];
  const user = users.find((u) => u.id === userId);
  if (!user) return showToast('Member not found', true);
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Edit ${esc(user.name)}</h3><p>Name, colour and WhatsApp number for reminders.</p></div>
      <div class="wf-modal-body">
        <label class="field field-full"><span>Name</span><input type="text" id="em-name" value="${esc(user.name)}"></label>
        <label class="field field-full"><span>Colour</span><input type="color" id="em-colour" value="${safeColour(user.colour, '#00a89e')}"></label>
        <label class="field field-full"><span>WhatsApp number</span><input type="tel" id="em-phone" value="${esc(user.phone || '')}" placeholder="+44 7911 123456"></label>
        <p style="font-size:0.8125rem;color:var(--text-muted);margin:2px 2px 0">Used for the morning digest and two-way chat. Include the country code.</p>
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="em-save">Save</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('em-save').onclick = async () => {
    try {
      await api(`/members/${userId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: document.getElementById('em-name').value.trim(),
          colour: document.getElementById('em-colour').value,
          phone: document.getElementById('em-phone').value.trim(),
        }),
      });
      closeModal();
      showToast('Member updated');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

function openCompareTripsModal() {
  const trips = store.holidays?.trips || [];
  if (!trips.length) return showToast('No trips to compare', true);
  const row = (label, fn) => `<tr><th style="text-align:left">${label}</th>${trips.map((t) => `<td>${fn(t)}</td>`).join('')}</tr>`;
  const table = `
    <table class="data-table">
      <thead><tr><th></th>${trips.map((t) => `<th>${esc(t.title)}</th>`).join('')}</tr></thead>
      <tbody>
        ${row('Status', (t) => `<span class="status-tag ${t.status}">${t.status}</span>`)}
        ${row('Dates', (t) => (t.start ? `${fmt.date(t.start)} → ${fmt.date(t.end)}` : 'TBC'))}
        ${row('Budget', (t) => fmt.gbp(t.budget))}
        ${row('Spent', (t) => fmt.gbp(t.spent))}
        ${row('Remaining', (t) => fmt.gbp((t.budget || 0) - (t.spent || 0)))}
        ${row('Countdown', (t) => (t.days_until != null ? `${t.days_until} days` : '—'))}
        ${row('Checklist', (t) => { const c = t.checklist || []; return c.length ? `${c.filter((x) => x.done).length}/${c.length}` : '—'; })}
        ${row('Photos', (t) => t.media_count || 0)}
      </tbody>
    </table>`;
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal wf-modal-wide" role="dialog">
      <div class="wf-modal-header"><h3>Compare trips</h3><p>All trips side by side.</p></div>
      <div class="wf-modal-body"><div class="table-wrap">${table}</div></div>
      <div class="wf-modal-footer"><button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Close</button></div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
}

function openChangePasswordModal() {
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Change password</h3><p>Update the password for ${esc(currentUser?.name || 'your account')}.</p></div>
      <div class="wf-modal-body">
        <label class="field field-full"><span>Current password</span><input type="password" id="cp-current" autocomplete="current-password"></label>
        <label class="field field-full"><span>New password</span><input type="password" id="cp-new" autocomplete="new-password"></label>
        <label class="field field-full"><span>Confirm new password</span><input type="password" id="cp-confirm" autocomplete="new-password"></label>
        <p class="hint-small">At least 8 characters.</p>
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="cp-save">Update password</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('cp-save').onclick = async () => {
    const current = document.getElementById('cp-current').value;
    const next = document.getElementById('cp-new').value;
    const confirmVal = document.getElementById('cp-confirm').value;
    if (next.length < 8) return showToast('New password must be at least 8 characters', true);
    if (next !== confirmVal) return showToast('New passwords do not match', true);
    try {
      await api('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }) });
      closeModal();
      showToast('Password updated');
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

function openRenameAccountModal(accountId, currentName) {
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Rename account</h3><p>Give this account a name you'll recognise. Bank syncs won't overwrite it.</p></div>
      <div class="wf-modal-body">
        <label class="field field-full"><span>Account name</span><input type="text" id="ra-name" value="${esc(currentName)}"></label>
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="ra-save">Save</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('ra-save').onclick = async () => {
    const name = document.getElementById('ra-name').value.trim();
    if (!name) return showToast('Enter a name', true);
    try {
      await api(`/accounts/${accountId}`, { method: 'PATCH', body: JSON.stringify({ name }) });
      closeModal();
      showToast('Account renamed');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

async function openHiddenAccountsModal() {
  try {
    const data = await api('/accounts?include_hidden=true');
    const hidden = (data.accounts || []).filter((a) => a.hidden);
    const rows = hidden.length
      ? hidden
          .map(
            (a) => `
        <div class="connection-row">
          <div class="connection-info"><div>
            <div class="connection-name">${esc(a.name)}</div>
            <div class="connection-status">${esc(a.institution)} · ${fmt.gbp(a.balance)}</div>
          </div></div>
          <button class="btn btn-sm btn-primary wf-action" data-action="unhide-account" data-account-id="${a.id}">Unhide</button>
        </div>`
          )
          .join('')
      : '<p class="hint-small">No hidden accounts.</p>';
    document.getElementById('modal-root').innerHTML = `
      <div class="modal-backdrop" id="modal-backdrop"></div>
      <div class="wf-modal" role="dialog">
        <div class="wf-modal-header"><h3>Hidden accounts</h3><p>Restore an account to the finances view.</p></div>
        <div class="wf-modal-body">${rows}</div>
        <div class="wf-modal-footer"><button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Close</button></div>
      </div>`;
    document.getElementById('modal-backdrop').onclick = closeModal;
  } catch (err) {
    showToast(err.message, true);
  }
}

function switchTab(tabId) {
  document.querySelectorAll('.tab').forEach((t) => {
    t.classList.toggle('active', t.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-panel').forEach((p) => {
    p.classList.toggle('active', p.id === `tab-${tabId}`);
  });
}

function renderMembers(users) {
  const chips = document.getElementById('member-chips');
  if (chips) {
    chips.innerHTML = users
      .map(
        (u) =>
          `<span class="member-chip"><span class="member-dot" style="background:${safeColour(u.colour)}"></span>${esc(u.name)}${u.google_connected ? ' · Google ✓' : ''}</span>`
      )
      .join('');
  }

  document.getElementById('cal-filters').innerHTML = users
    .map(
      (u) =>
        `<label class="filter-chip"><input type="checkbox" data-user-id="${esc(u.id)}"${calFilterHidden.has(u.id) ? '' : ' checked'}><span style="display:inline-flex;align-items:center;gap:6px"><span class="member-dot" style="background:${safeColour(u.colour)}"></span>${esc(u.name)}</span></label>`
    )
    .join('');
}

function renderWelcome(data) {
  const h = data.next_holiday;
  document.getElementById('welcome-hero').innerHTML = `
    <div>
      <h2>${fmt.greeting()}, ${(data.users || []).map((u) => esc(u.name)).join(' & ') || 'household'}</h2>
      <p>${fmt.todayLabel()} · ${data.upcoming_events.length} events this week · ${data.notifications_unread} notifications</p>
    </div>
    <div class="welcome-meta">
      <div class="welcome-meta-item"><strong>${h?.days_until ?? '—'}</strong><span>Days to ${esc((h?.title || 'holiday').split(',')[0])}</span></div>
      <div class="welcome-meta-item"><strong>${fmt.gbp(data.finance_summary.joint_balance)}</strong><span>Joint balance</span></div>
      <div class="welcome-meta-item"><strong>${data.tasks.filter((t) => !t.done).length}</strong><span>Tasks open</span></div>
    </div>`;
}

function renderActionGrid() {
  const tiles = [
    { action: 'add-event', modal: 'add-event', icon: 'calendar', colour: 'teal', label: 'Add event', sub: 'Calendar' },
    { action: 'log-expense', modal: 'log-expense', icon: 'money', colour: 'navy', label: 'Log expense', sub: 'Finances' },
    { action: 'add-appointment', modal: 'add-appointment', icon: 'user', colour: 'amber', label: 'Appointment', sub: 'Bookings' },
    { action: 'holiday-idea', modal: 'holiday-ai', icon: 'spark', colour: 'purple', label: 'Holiday AI', sub: 'OpenRouter' },
    { action: 'add-task', modal: 'add-task', icon: 'check', colour: 'green', label: 'Add task', sub: 'To-do' },
    { action: 'new-trip', modal: 'new-trip', icon: 'pin', colour: 'blue', label: 'New trip', sub: 'Holidays' },
    { action: 'open-vault', icon: 'check', colour: 'navy', label: 'Upload doc', sub: 'Vault' },
  ];
  document.getElementById('action-grid').innerHTML = tiles
    .map(
      (t) => `
    <button class="action-tile wf-action" data-action="${t.action}"${t.modal ? ` data-modal="${t.modal}"` : ''}${t.action === 'open-vault' ? ' data-tab-link="documents"' : ''}>
      <div class="action-tile-icon ${t.colour}">${icon(t.icon)}</div>
      <span class="action-tile-label">${t.label}</span>
      <span class="action-tile-sub">${t.sub}</span>
    </button>`
    )
    .join('');
}

function renderReminders(reminders) {
  const icons = { appointment: '📅', bill: '💷', document: '📄' };
  document.getElementById('reminder-strip').innerHTML = reminders
    .map(
      (r) => `
    <div class="reminder-chip">
      <div class="reminder-chip-icon ${r.type}">${icons[r.type] || '•'}</div>
      <div><strong>${esc(r.text)}</strong><span>${esc(r.when)}</span></div>
    </div>`
    )
    .join('');
}

function taskRowInner(users, t) {
  const remindLabel = t.remind_at ? `⏰ ${fmt.datetime(t.remind_at)}` : '';
  return `
      <div class="task-check${t.done ? ' done' : ''} wf-action" data-action="toggle-task" data-task-id="${t.id}" data-done="${t.done ? '1' : '0'}"></div>
      <div class="task-body">
        <div class="task-title">${esc(t.title)}</div>
        <div class="task-meta">
          ${userName(users, t.assignee)}
          ${t.due ? `· Due ${fmt.date(t.due)}` : ''}
          ${remindLabel ? `· ${remindLabel}` : ''}
          <span class="priority-tag ${esc(t.priority)}">${esc(t.priority)}</span>
        </div>
      </div>
      <button class="task-edit-btn wf-action" data-action="edit-task" data-task-id="${t.id}" title="Edit task" aria-label="Edit task">✎</button>`;
}

function taskRow(users, t) {
  return `<div class="task-item${t.done ? ' done' : ''}" data-task-id="${t.id}">${taskRowInner(users, t)}</div>`;
}

// Inline edit form that replaces a task row's contents in place (no modal).
function taskEditInner(users, t) {
  const userOpts = users.map((u) => `<option value="${u.id}"${u.id === t.assignee ? ' selected' : ''}>${esc(u.name)}</option>`).join('')
    + `<option value=""${!t.assignee ? ' selected' : ''}>Both</option>`;
  const priOpts = ['high', 'medium', 'low'].map((p) => `<option value="${p}"${p === t.priority ? ' selected' : ''}>${p}</option>`).join('');
  return `
    <div class="row-edit" data-task-id="${t.id}">
      <input type="text" class="te-input" data-f="title" value="${esc(t.title)}" placeholder="Task">
      <div class="row-edit-fields">
        <label>Owner<select data-f="assignee">${userOpts}</select></label>
        <label>Priority<select data-f="priority">${priOpts}</select></label>
        <label>Complete by<input type="date" data-f="due" value="${esc(t.due || '')}"></label>
        <label>Remind me<input type="datetime-local" data-f="remind_at" value="${esc((t.remind_at || '').slice(0, 16))}"></label>
        <label class="row-edit-check"><input type="checkbox" data-f="notify"> Notify owner on WhatsApp</label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-task-inline" data-task-id="${t.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-task-inline" data-task-id="${t.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-task-inline" data-task-id="${t.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function openAllTasksModal() {
  const users = store.dashboard?.users || [];
  const tasks = store.dashboard?.tasks || [];
  const sorted = [...tasks].sort((a, b) => Number(a.done) - Number(b.done) || (a.due || '').localeCompare(b.due || ''));
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal wf-modal-wide" role="dialog">
      <div class="wf-modal-header"><h3>All tasks</h3><p>Tick, untick, or edit any household task.</p></div>
      <div class="wf-modal-body">${sorted.map((t) => taskRow(users, t)).join('') || '<p class="hint-small">No tasks yet.</p>'}</div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Close</button>
        <button type="button" class="btn btn-primary wf-action" data-action="add-task" data-modal="add-task">+ Add task</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
}

// Read the values out of an inline row-edit form (task or bill).
function readInlineFields(root) {
  const data = {};
  root.querySelectorAll('[data-f]').forEach((el) => {
    data[el.dataset.f] = el.type === 'checkbox' ? el.checked : el.value;
  });
  return data;
}

const BILL_CATEGORIES = ['Housing', 'Utilities', 'Subscriptions', 'Transport', 'Insurance', 'Groceries', 'Health', 'Other'];

function findBill(id) {
  return (store.finances?.bills || []).find((b) => String(b.id) === String(id))
    || (store.dashboard?.upcoming_bills || []).find((b) => String(b.id) === String(id));
}

function billRowInner(b) {
  const lockBtn = b.subscription_id
    ? `<button class="bill-lock-btn wf-action" data-action="${b.locked ? 'unlock-bill' : 'lock-bill'}" data-bill-id="${b.id}" data-sub-id="${esc(b.subscription_id)}" title="${b.locked ? 'Unlock from bank payment' : 'Lock to bank payment (auto-marks paid)'}">${b.locked ? '🔒' : '🔓'}</button>`
    : '';
  let status = '';
  if (b.paid && b.locked) status = ` · <span class="bill-auto">🔒 Auto-paid${b.locked_to_name ? ` · ${esc(b.locked_to_name)}` : ''}</span>`;
  else if (b.paid) status = ' · ✓ Paid';
  else if (b.locked) status = ` · <span class="bill-auto">🔒 Locked${b.locked_to_name ? ` · ${esc(b.locked_to_name)}` : ''}</span>`;
  return `
    <div class="list-item-body">
      <div class="list-item-title">${esc(b.name)}</div>
      <div class="list-item-meta">Day ${b.due_day} · ${esc(b.category)}${status}</div>
    </div>
    <div class="bill-row-actions">
      <div class="list-item-amount negative">${fmt.gbp(b.amount)}</div>
      ${!b.paid && !b.locked ? `<button class="btn btn-sm btn-soft wf-action" data-action="mark-paid" data-bill-id="${b.id}">Pay</button>` : ''}
      ${lockBtn}
      <button class="bill-edit-btn wf-action" data-action="edit-bill" data-bill-id="${b.id}" title="Edit bill" aria-label="Edit bill">✎</button>
    </div>`;
}

function billRow(b) {
  return `<div class="list-item${b.paid ? ' bill-paid' : ''}" data-bill-id="${b.id}">${billRowInner(b)}</div>`;
}

function billEditInner(b) {
  const catOpts = BILL_CATEGORIES.map((c) => `<option${c === b.category ? ' selected' : ''}>${c}</option>`).join('');
  const recOpts = ['monthly', 'quarterly', 'yearly', 'weekly'].map((r) => `<option value="${r}"${r === (b.recurrence || 'monthly') ? ' selected' : ''}>${r}</option>`).join('');
  return `
    <div class="row-edit" data-bill-id="${b.id}">
      <input type="text" class="te-input" data-f="name" value="${esc(b.name)}" placeholder="Bill name">
      <div class="row-edit-fields">
        <label>Amount £<input type="number" step="0.01" min="0" data-f="amount" value="${b.amount}"></label>
        <label>Due day<input type="number" min="1" max="31" data-f="due_day" value="${b.due_day}"></label>
        <label>Category<select data-f="category">${catOpts}</select></label>
        <label>Recurrence<select data-f="recurrence">${recOpts}</select></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-bill-inline" data-bill-id="${b.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-bill-inline" data-bill-id="${b.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-bill-inline" data-bill-id="${b.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function findBudget(cat) {
  return (store.finances?.budgets || []).find((b) => String(b.category) === String(cat));
}

function findSavings(id) {
  return (store.finances?.savings_goals || []).find((g) => String(g.id) === String(id));
}

function budgetRowInner(b) {
  const pct = b.limit > 0 ? Math.round((b.spent / b.limit) * 100) : 0;
  const cls = pct >= 100 ? 'over' : pct >= 85 ? 'warn' : '';
  return `
    <div class="budget-row-head">
      <span>${esc(b.category)}</span>
      <span class="bill-row-actions">
        <span class="${pct >= 100 ? 'over' : ''}">${fmt.gbp(b.spent)} / ${fmt.gbp(b.limit)}</span>
        <button type="button" class="bill-edit-btn wf-action" data-action="edit-budget" data-budget-cat="${esc(b.category)}" title="Edit limit">✎</button>
        <button type="button" class="bill-edit-btn wf-action" data-action="delete-budget" data-budget-cat="${esc(b.category)}" title="Remove">🗑</button>
      </span>
    </div>
    <div class="progress-bar budget"><div class="progress-fill ${cls}" style="width:${Math.min(pct, 100)}%"></div></div>`;
}

function budgetRow(b) {
  return `<div class="budget-item" data-budget-cat="${esc(b.category)}">${budgetRowInner(b)}</div>`;
}

function budgetEditInner(b) {
  return `
    <div class="row-edit" data-budget-cat="${esc(b.category)}">
      <div class="row-edit-fields">
        <label>${esc(b.category)} — monthly limit £<input type="number" step="0.01" min="0" data-f="monthly_limit" value="${b.limit}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-budget-inline" data-budget-cat="${esc(b.category)}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-budget-inline" data-budget-cat="${esc(b.category)}">Cancel</button>
      </div>
    </div>`;
}

function budgetAddInner(cats) {
  const opts = cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
  if (!opts) return '<p class="hint-small">Every spending category already has a budget.</p>';
  return `
    <div class="row-edit" id="budget-add-form">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${opts}</select></label>
        <label>Monthly limit £<input type="number" step="0.01" min="0" data-f="monthly_limit" value=""></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-budget-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="finance-budgets">Cancel</button>
      </div>
    </div>`;
}

function savingsRowInner(g) {
  const pct = g.target > 0 ? Math.round((g.current / g.target) * 100) : 0;
  return `
    <div class="savings-head">
      <h4>${esc(g.name)}</h4>
      <span class="bill-row-actions">
        <button type="button" class="bill-edit-btn wf-action" data-action="edit-savings" data-goal-id="${g.id}" title="Edit">✎</button>
        <button type="button" class="bill-edit-btn wf-action" data-action="delete-savings" data-goal-id="${g.id}" title="Remove">🗑</button>
      </span>
    </div>
    <div class="savings-amounts"><strong>${fmt.gbp(g.current)}</strong><span>of ${fmt.gbp(g.target)}</span></div>
    <div class="progress-bar"><div class="progress-fill" style="width:${Math.min(pct, 100)}%;background:${safeColour(g.colour, 'var(--accent)')}"></div></div>`;
}

function savingsRow(g) {
  return `<div class="savings-card" data-goal-id="${g.id}">${savingsRowInner(g)}</div>`;
}

function savingsEditInner(g) {
  return `
    <div class="row-edit" data-goal-id="${g.id}">
      <input type="text" class="te-input" data-f="name" value="${esc(g.name)}" placeholder="Goal name">
      <div class="row-edit-fields">
        <label>Target £<input type="number" step="0.01" min="0" data-f="target" value="${g.target}"></label>
        <label>Saved £<input type="number" step="0.01" min="0" data-f="current" value="${g.current}"></label>
        <label>Colour<input type="color" data-f="colour" value="${safeColour(g.colour, '#00a89e')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-savings-inline" data-goal-id="${g.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-savings-inline" data-goal-id="${g.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-savings-inline" data-goal-id="${g.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function savingsAddInner() {
  return `
    <div class="row-edit" id="savings-add-form">
      <input type="text" class="te-input" data-f="name" value="" placeholder="Goal name (e.g. New car)">
      <div class="row-edit-fields">
        <label>Target £<input type="number" step="0.01" min="0" data-f="target" value=""></label>
        <label>Saved £<input type="number" step="0.01" min="0" data-f="current" value="0"></label>
        <label>Colour<input type="color" data-f="colour" value="#00a89e"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-savings-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="finance-savings">Cancel</button>
      </div>
    </div>`;
}

// --- Feature A: Home layout (reorder + hide cards, per-device) -------------
// Saved in localStorage under 'hub-home-layout' as { order:[key...], hidden:[key...] }.
// Card keys come from the data-card attribute on each `.dashboard-grid > .card`.
// Unknown / brand-new cards (not in the saved order) always render, appended
// after the known ones, so future features keep appearing automatically.
const HOME_LAYOUT_KEY = 'hub-home-layout';
let homeCustomising = false;

function getHomeLayout() {
  try {
    const raw = JSON.parse(localStorage.getItem(HOME_LAYOUT_KEY) || '{}');
    return {
      order: Array.isArray(raw.order) ? raw.order.filter((k) => typeof k === 'string') : [],
      hidden: Array.isArray(raw.hidden) ? raw.hidden.filter((k) => typeof k === 'string') : [],
    };
  } catch {
    return { order: [], hidden: [] };
  }
}

function saveHomeLayout(layout) {
  try {
    localStorage.setItem(HOME_LAYOUT_KEY, JSON.stringify({
      order: Array.isArray(layout.order) ? layout.order : [],
      hidden: Array.isArray(layout.hidden) ? layout.hidden : [],
    }));
  } catch { /* storage full / disabled — layout just won't persist */ }
}

function homeGrid() {
  return document.querySelector('#tab-home .dashboard-grid');
}

// Only cards that carry a stable data-card key participate in reorder/hide.
function homeCards() {
  const grid = homeGrid();
  return grid ? Array.from(grid.querySelectorAll(':scope > .card[data-card]')) : [];
}

// The full key order actually applied: saved keys that still exist first (in
// saved order), then any remaining present cards in their current DOM order.
function homeResolvedOrder() {
  const layout = getHomeLayout();
  const present = homeCards().map((c) => c.dataset.card);
  const seen = new Set();
  const out = [];
  layout.order.forEach((k) => {
    if (present.includes(k) && !seen.has(k)) { out.push(k); seen.add(k); }
  });
  present.forEach((k) => {
    if (!seen.has(k)) { out.push(k); seen.add(k); }
  });
  return out;
}

// Apply saved order + hidden state to the live DOM. Safe to call on every home
// render — it only moves existing card nodes (handlers/content preserved).
function applyHomeLayout() {
  const grid = homeGrid();
  if (!grid) return;
  const hidden = new Set(getHomeLayout().hidden);
  const byKey = new Map(homeCards().map((c) => [c.dataset.card, c]));
  const keys = homeResolvedOrder();

  keys.forEach((key, idx) => {
    const card = byKey.get(key);
    if (!card) return;
    grid.appendChild(card); // re-append in resolved order (moves the node)
    const isHidden = hidden.has(key);
    card.classList.toggle('home-card-hidden', isHidden);
    // Hidden cards vanish normally; in customise mode they stay visible (greyed)
    // so they can be un-hidden.
    card.style.display = !isHidden || homeCustomising ? '' : 'none';
    renderHomeCardControls(card, idx, keys.length, isHidden);
  });
}

// Inject / remove the per-card move + hide controls used in customise mode.
function renderHomeCardControls(card, idx, total, isHidden) {
  let bar = card.querySelector(':scope > .home-card-controls');
  if (!homeCustomising) {
    if (bar) bar.remove();
    return;
  }
  const key = card.dataset.card;
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'home-card-controls';
    card.insertBefore(bar, card.firstChild);
  }
  bar.innerHTML = `
    <button type="button" class="home-card-ctl wf-action" data-action="home-move-card" data-card="${esc(key)}" data-dir="up"${idx === 0 ? ' disabled' : ''} title="Move up" aria-label="Move card up">⬆︎</button>
    <button type="button" class="home-card-ctl wf-action" data-action="home-move-card" data-card="${esc(key)}" data-dir="down"${idx === total - 1 ? ' disabled' : ''} title="Move down" aria-label="Move card down">⬇︎</button>
    <button type="button" class="home-card-ctl home-card-hide wf-action" data-action="home-toggle-card-hidden" data-card="${esc(key)}" title="${isHidden ? 'Show this card' : 'Hide this card'}" aria-label="${isHidden ? 'Show this card' : 'Hide this card'}">${isHidden ? '👁 Show' : '🙈 Hide'}</button>`;
}

// Swap a card one slot up/down within the resolved order, then persist + apply.
function moveHomeCard(key, dir) {
  const keys = homeResolvedOrder();
  const i = keys.indexOf(key);
  if (i < 0) return;
  const j = dir === 'up' ? i - 1 : i + 1;
  if (j < 0 || j >= keys.length) return;
  [keys[i], keys[j]] = [keys[j], keys[i]];
  const layout = getHomeLayout();
  layout.order = keys;
  saveHomeLayout(layout);
  applyHomeLayout();
}

function toggleHomeCardHidden(key) {
  const layout = getHomeLayout();
  const hidden = new Set(layout.hidden);
  if (hidden.has(key)) hidden.delete(key); else hidden.add(key);
  layout.hidden = Array.from(hidden);
  saveHomeLayout(layout);
  applyHomeLayout();
}

// Enter / leave customise mode: relabel the button, flag the grid, re-apply.
function toggleHomeCustomise() {
  homeCustomising = !homeCustomising;
  const btn = document.getElementById('home-customise-btn');
  if (btn) {
    btn.textContent = homeCustomising ? '✓ Done' : '⚙︎ Customise';
    btn.setAttribute('aria-pressed', homeCustomising ? 'true' : 'false');
    btn.classList.toggle('btn-primary', homeCustomising);
    btn.classList.toggle('btn-secondary', !homeCustomising);
  }
  const grid = homeGrid();
  if (grid) grid.classList.toggle('home-grid-editing', homeCustomising);
  applyHomeLayout();
}

function renderHome(data) {
  const { users, upcoming_events, upcoming_bills, upcoming_appointments, next_holiday, finance_summary, tasks, documents } = data;

  document.getElementById('home-stats').innerHTML = `
    <div class="stat"><span>${upcoming_events.length}</span><label>Events this week</label><div class="stat-trend up">${upcoming_events.filter((e) => e.source === 'google').length} from Google</div></div>
    <div class="stat"><span>${upcoming_bills.length}</span><label>Bills due</label><div class="stat-trend neutral">${fmt.gbp(finance_summary.bills_due_this_month)} total</div></div>
    <div class="stat"><span>${upcoming_appointments.length}</span><label>Appointments</label><div class="stat-trend neutral">Next: ${fmt.date(upcoming_appointments[0]?.datetime)}</div></div>
    <div class="stat"><span>${next_holiday?.days_until ?? '—'}</span><label>Days to holiday</label><div class="stat-trend up">${esc(next_holiday?.title || '')}</div></div>`;

  document.getElementById('home-events').innerHTML = upcoming_events
    .map((e) => {
      const col = userColour(users, e.user_id);
      return `
      <div class="list-item">
        <div class="list-item-time">${e.all_day ? 'All day' : fmt.time(e.start)}</div>
        <div class="list-item-body">
          <div class="list-item-title">${esc(e.title)}</div>
          <div class="list-item-meta">${fmt.date(e.start)} · ${userName(users, e.user_id)}${e.location ? ` · ${esc(e.location)}` : ''}
            <span class="source-tag ${esc(e.source)}">${esc(e.source)}</span></div>
        </div>
        <span class="member-dot" style="background:${col};margin-top:6px"></span>
      </div>`;
    })
    .join('') || '<p class="hint-small">No events this week — tap + Add to create one.</p>';

  document.getElementById('home-tasks').innerHTML = tasks
    .slice(0, 4)
    .map((t) => taskRow(users, t))
    .join('') || '<p class="hint-small">No tasks yet.</p>';

  document.getElementById('home-bills').innerHTML = upcoming_bills
    .map((b) => billRow(b))
    .join('') || '<p class="hint-small">Nothing due — add a bill in Finances.</p>';

  document.getElementById('home-appointments').innerHTML = upcoming_appointments
    .map(
      (a) => `
    <div class="list-item">
      <div class="list-item-time">${fmt.date(a.datetime)}</div>
      <div class="list-item-body">
        <div class="list-item-title">${esc(a.title)}</div>
        <div class="list-item-meta">${esc(a.provider)} · ${fmt.time(a.datetime)}</div>
      </div>
    </div>`
    )
    .join('') || '<p class="hint-small">No appointments in the next 7 days.</p>';

  if (next_holiday) {
    const done = next_holiday.checklist?.filter((c) => c.done).length || 0;
    const total = next_holiday.checklist?.length || 0;
    document.getElementById('home-holiday').innerHTML = `
      ${next_holiday.days_until != null ? `<div class="holiday-countdown">${next_holiday.days_until} days</div>` : ''}
      <p style="font-size:1rem;font-weight:600;color:var(--navy-900);margin:8px 0 4px">${esc(next_holiday.title)}</p>
      <p style="font-size:0.875rem;color:var(--text-muted)">${fmt.date(next_holiday.start)} → ${fmt.date(next_holiday.end)}</p>
      ${total ? `<p style="font-size:0.8125rem;color:var(--text-muted);margin-top:10px">Checklist: ${done}/${total} done</p>
        <div class="progress-bar"><div class="progress-fill" style="width:${Math.round((done / total) * 100)}%"></div></div>` : ''}
      <span class="status-tag booked" style="margin-top:12px;display:inline-block">${esc(next_holiday.status)}</span>`;
  } else {
    document.getElementById('home-holiday').innerHTML = '<p class="hint-small">No trips planned — add one on the Holidays tab.</p>';
  }

  document.getElementById('home-documents').innerHTML = documents.length
    ? documents
        .slice(0, 4)
        .map(
          (d) => `
      <div class="list-item">
        <div class="list-item-body">
          <div class="list-item-title">${esc(d.name)}</div>
          <div class="list-item-meta">${esc(DOC_CATEGORY_LABELS[d.category] || d.category)}${docExpiryValue(d) ? ' · ' + fmt.date(docExpiryValue(d)) : ''}${d.has_file ? ' · 📎' : ''}</div>
        </div>
        <span class="status-tag ${docStatusClass(d.status)}">${docStatusLabel(d.status)}</span>
      </div>`
        )
        .join('')
    : '<p class="hint-small">All documents up to date</p>';

  const financeSub = document.getElementById('home-finance-sub');
  if (financeSub) financeSub.textContent = `Income vs spending · ${new Date().toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })}`;

  const spentPct = finance_summary.monthly_income > 0
    ? Math.round((finance_summary.monthly_spent / finance_summary.monthly_income) * 100)
    : 0;
  document.getElementById('home-finance').innerHTML = `
    <div class="two-col" style="gap:32px">
      <div>
        <div style="display:flex;justify-content:space-between;margin-bottom:8px">
          <span style="font-size:0.875rem;color:var(--text-muted)">Spent this month</span>
          <span style="font-weight:700">${fmt.gbp(finance_summary.monthly_spent)} / ${fmt.gbp(finance_summary.monthly_income)}</span>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${finance_summary.monthly_income > 0 ? Math.min(spentPct, 100) : 0}%"></div></div>
        <div class="finance-split"><span>${finance_summary.monthly_income > 0 ? `${spentPct}% of income` : '—'}</span><span>Savings: ${fmt.gbp(finance_summary.savings_total)}</span></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div class="stat" style="margin:0;padding:16px"><span style="font-size:1.5rem">${fmt.gbp(finance_summary.joint_balance)}</span><label>Joint</label></div>
        <div class="stat" style="margin:0;padding:16px"><span style="font-size:1.5rem">${fmt.gbp(finance_summary.bills_due_this_month)}</span><label>Bills due</label></div>
      </div>
    </div>`;

  // Reorder / hide cards to match the per-device saved layout (Feature A).
  applyHomeLayout();
}

// --- Proactive inbox suggestions (Home card) -------------------------------
// Persistent, deduplicated "we spotted this in your email — add it?" cards that
// survive across scans (dismissed stays dismissed, accepted stays accepted).
// GET /api/inbox/suggestions -> { suggestions:[{id,kind,title,summary,source_subject,...}] }.
// Own endpoint / own refresh, like the shopping + meal home cards.
const SUGGESTION_KIND_EMOJI = {
  trip: '✈️',
  appointment: '📅',
  document: '📄',
  bill: '💷',
};

// Where each accepted kind lands — drives the "Added to your …" toast.
const SUGGESTION_ADDED_DEST = {
  trip: 'trips',
  appointment: 'calendar',
  document: 'vault',
  bill: 'bills',
};

async function renderInboxSuggestions() {
  const el = document.getElementById('home-suggestions');
  if (!el) return;
  let res;
  try {
    res = await api('/inbox/suggestions');
  } catch {
    el.innerHTML = '<p class="hint-small">Suggestions unavailable.</p>';
    return;
  }
  const items = (res && res.suggestions) || [];
  if (!items.length) {
    el.innerHTML = '<p class="hint-small">Nothing waiting — I\'ll keep an eye on your inbox.</p>';
    return;
  }
  el.innerHTML = items
    .map((s) => {
      const emoji = SUGGESTION_KIND_EMOJI[s.kind] || '📨';
      const summary = s.summary ? `<div class="list-item-meta">${esc(s.summary)}</div>` : '';
      const src = s.source_subject ? `<div class="sug-source">from: ${esc(s.source_subject)}</div>` : '';
      return `
      <div class="list-item sug-row" data-sug-id="${esc(s.id)}">
        <div class="sug-emoji" aria-hidden="true">${emoji}</div>
        <div class="list-item-body">
          <div class="list-item-title">${esc(s.title)}</div>
          ${summary}
          ${src}
          <div class="sug-actions">
            <button type="button" class="btn btn-sm btn-primary wf-action" data-action="accept-suggestion" data-sug-id="${esc(s.id)}" data-kind="${esc(s.kind)}">Add ✓</button>
            <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="dismiss-suggestion" data-sug-id="${esc(s.id)}">Dismiss ✕</button>
          </div>
        </div>
      </div>`;
    })
    .join('');
}

// Drop a row after accept/dismiss for instant feedback; fall back to the empty
// state if it was the last one. A full load() then refreshes home counts.
function removeSuggestionRow(sid) {
  const el = document.getElementById('home-suggestions');
  if (!el) return;
  el.querySelectorAll('.sug-row').forEach((row) => {
    if (row.dataset.sugId === sid) row.remove();
  });
  if (!el.querySelector('.sug-row')) {
    el.innerHTML = '<p class="hint-small">Nothing waiting — I\'ll keep an eye on your inbox.</p>';
  }
}

async function acceptSuggestion(sid, kind, btn) {
  if (!sid) return;
  if (btn) btn.disabled = true;
  try {
    await api(`/inbox/suggestions/${encodeURIComponent(sid)}`, {
      method: 'PATCH',
      body: JSON.stringify({ action: 'accept' }),
    });
  } catch (err) {
    if (btn) btn.disabled = false;
    return showToast(err.message, true);
  }
  removeSuggestionRow(sid);
  showToast(`Added to your ${SUGGESTION_ADDED_DEST[kind] || 'hub'}`);
  load(); // accepting created a trip/appointment/document/bill — refresh home counts
}

async function dismissSuggestion(sid, btn) {
  if (!sid) return;
  if (btn) btn.disabled = true;
  try {
    await api(`/inbox/suggestions/${encodeURIComponent(sid)}`, {
      method: 'PATCH',
      body: JSON.stringify({ action: 'dismiss' }),
    });
  } catch (err) {
    if (btn) btn.disabled = false;
    return showToast(err.message, true);
  }
  removeSuggestionRow(sid);
  showToast('Dismissed');
}

// Header "Scan my email" button: fresh POST scan, spinner, then re-render.
async function scanInboxSuggestions(btn) {
  const el = document.getElementById('home-suggestions');
  if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }
  if (el) el.innerHTML = '<div class="sug-scanning"><span class="sug-spinner" aria-hidden="true"></span> Reading your inbox…</div>';
  let res;
  try {
    res = await api('/inbox/suggestions/scan', { method: 'POST' });
  } catch (err) {
    showToast(err.message, true);
    await renderInboxSuggestions();
    if (btn) { btn.disabled = false; btn.textContent = 'Scan my email'; }
    return;
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Scan my email'; }
  if (res && res.no_account) {
    showToast('Connect your Gmail in Settings', true);
  } else if (res && (res.needs_reconnect || []).length) {
    showToast('Reconnect Gmail to grant email access', true);
  } else {
    const n = res && typeof res.new === 'number' ? res.new : 0;
    showToast(n > 0 ? `Found ${n} new suggestion${n === 1 ? '' : 's'}` : 'No new suggestions right now');
  }
  await renderInboxSuggestions();
}

// --- Shared shopping list (home card) ---
// Refreshes on its own (not via the heavy load()) so ticking an item doesn't reset the page.
async function loadShopping() {
  const el = document.getElementById('home-shopping');
  if (!el) return;
  try {
    const d = await api('/shopping');
    store.shopping = d.items || [];
    renderShopping(store.shopping);
  } catch {
    store.shopping = [];
    el.innerHTML = '<p class="hint-small">Shopping list unavailable.</p>';
  }
}

function renderShopping(items) {
  const el = document.getElementById('home-shopping');
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = '<p class="hint-small">Nothing on the list</p>';
    return;
  }
  const doneCount = items.filter((i) => i.done).length;
  const rows = items
    .map(
      (i) => `
    <label class="shopping-item${i.done ? ' done' : ''}" data-shop-id="${i.id}">
      <input type="checkbox" class="shopping-check" data-shop-id="${i.id}"${i.done ? ' checked' : ''}>
      <span class="shopping-text">${esc(i.text)}</span>
      <button type="button" class="shopping-del wf-action" data-action="delete-shopping" data-shop-id="${i.id}" title="Remove" aria-label="Remove item">×</button>
    </label>`
    )
    .join('');
  const clear = doneCount
    ? `<button type="button" class="shopping-clear wf-action" data-action="clear-done-shopping">Clear done (${doneCount})</button>`
    : '';
  el.innerHTML = `<div class="shopping-list">${rows}</div>${clear}`;
}

function addShoppingItem() {
  const input = document.getElementById('shopping-input');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  api('/shopping', { method: 'POST', body: JSON.stringify({ text }) })
    .then(() => loadShopping())
    .catch((err) => { showToast(err.message, true); input.value = text; });
}

function toggleShoppingItem(id, done) {
  api(`/shopping/${id}`, { method: 'PATCH', body: JSON.stringify({ done }) })
    .then(() => loadShopping())
    .catch((err) => { showToast(err.message, true); loadShopping(); });
}

function deleteShoppingItem(id) {
  api(`/shopping/${id}`, { method: 'DELETE' })
    .then(() => loadShopping())
    .catch((err) => showToast(err.message, true));
}

function clearDoneShopping() {
  api('/shopping/clear-done', { method: 'POST' })
    .then((r) => {
      loadShopping();
      if (r && r.cleared) showToast(`Cleared ${r.cleared} item${r.cleared === 1 ? '' : 's'}`);
    })
    .catch((err) => showToast(err.message, true));
}

// --- Weekly meal planner (home card) ---
// Own endpoint / own refresh, like the shopping list — editing one day never
// resets the whole page. GET /meals with no params returns the current Mon–Sun
// week as { meals:[{date,title,ingredients,...}], start, end }.
let mealsData = null;

async function loadMeals() {
  const el = document.getElementById('home-meals');
  if (!el) return;
  try {
    mealsData = await api('/meals');
    renderMeals(mealsData);
  } catch {
    mealsData = null;
    el.innerHTML = '<p class="hint-small">Meal planner unavailable.</p>';
  }
}

// Seven Date objects Mon→Sun. Prefer the server's start; fall back to this
// week's Monday so the card still fills in if start is ever missing.
function mealWeekDates(startIso) {
  let base;
  if (startIso) {
    base = new Date(`${startIso}T00:00:00`);
  } else {
    base = new Date();
    const dow = (base.getDay() + 6) % 7; // 0 = Monday
    base.setDate(base.getDate() - dow);
  }
  const out = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    out.push(d);
  }
  return out;
}

function renderMeals(data) {
  const el = document.getElementById('home-meals');
  if (!el) return;
  const byDate = {};
  (data?.meals || []).forEach((m) => { byDate[m.date] = m; });
  const todayIso = calYmd(new Date());
  el.innerHTML = mealWeekDates(data?.start)
    .map((d) => {
      const iso = calYmd(d);
      const m = byDate[iso];
      const today = iso === todayIso ? ' today' : '';
      return `<div class="meal-row${m ? '' : ' empty'}${today}" data-date="${iso}">${mealRowInner(d, iso, m)}</div>`;
    })
    .join('');
}

function mealRowInner(dateObj, iso, m) {
  const day = dateObj.toLocaleDateString('en-GB', { weekday: 'short' });
  const dm = dateObj.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  const title = m && m.title ? esc(m.title) : '<span class="meal-empty-text">—</span>';
  const ingredients = m && m.ingredients ? `<div class="meal-ingredients">${esc(m.ingredients)}</div>` : '';
  const cart = m && m.title
    ? `<button type="button" class="meal-cart-btn wf-action" data-action="meal-to-shopping" data-date="${iso}" title="Add ingredients to shopping list" aria-label="Add ingredients to shopping list">🛒</button>`
    : '';
  return `
    <div class="meal-day"><span class="meal-day-name">${esc(day)}</span><span class="meal-day-date">${esc(dm)}</span></div>
    <div class="meal-body wf-action" data-action="edit-meal" data-date="${iso}">
      <div class="meal-title">${title}</div>
      ${ingredients}
    </div>
    <div class="meal-row-actions">
      ${cart}
      <button type="button" class="meal-edit-btn wf-action" data-action="edit-meal" data-date="${iso}" title="Edit meal" aria-label="Edit meal">✎</button>
    </div>`;
}

// Inline editor that replaces a meal row's contents (reuses .row-edit styling).
function mealEditInner(m) {
  return `
    <div class="row-edit" data-date="${m.date}">
      <input type="text" class="te-input" data-f="title" value="${esc(m.title || '')}" placeholder="Dinner (e.g. Spaghetti bolognese)">
      <div class="row-edit-fields">
        <label>Ingredients<input type="text" data-f="ingredients" value="${esc(m.ingredients || '')}" placeholder="e.g. pasta, mince, tomatoes, onion"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-meal-inline" data-date="${m.date}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-meal-inline" data-date="${m.date}">Cancel</button>
        ${m.title ? `<button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-meal-inline" data-date="${m.date}" style="margin-left:auto">Delete</button>` : ''}
      </div>
    </div>`;
}

function calYmd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function calStartOfWeek(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const offset = (x.getDay() + 6) % 7; // Monday = 0
  x.setDate(x.getDate() - offset);
  return x;
}

function calAgendaRow(users, e) {
  return `
      <div class="list-item wf-action" data-action="event-detail" data-event-id="${esc(e.id)}" style="cursor:pointer">
        <div class="list-item-time">${e.all_day ? 'All day' : fmt.time(e.start)}</div>
        <div class="list-item-body">
          <div class="list-item-title">${esc(e.title)}</div>
          <div class="list-item-meta">${fmt.date(e.start)} · ${userName(users, e.user_id)}${e.location ? ` · 📍 ${esc(e.location)}` : ''}</div>
        </div>
        <span class="cal-event" style="background:${userColour(users, e.user_id)}">${userName(users, e.user_id)}</span>
      </div>`;
}

function openEventDetailModal(id) {
  const data = store.calendar || {};
  const users = data.users || [];
  const e = (data.events || []).find((x) => String(x.id) === String(id));
  if (!e) return showToast('Event not found', true);
  const colour = userColour(users, e.user_id);
  const who = userName(users, e.user_id);
  const when = e.all_day
    ? fmt.date(e.start)
    : `${fmt.date(e.start)} · ${fmt.time(e.start)}${e.end ? '–' + fmt.time(e.end) : ''}`;
  const rows = [`<div class="ev-row"><span class="ev-ico">🕑</span><div>${esc(when)}</div></div>`];
  if (e.location) rows.push(`<div class="ev-row"><span class="ev-ico">📍</span><div>${esc(e.location)}</div></div>`);
  rows.push(
    `<div class="ev-row"><span class="ev-ico">👤</span><div>${who}${
      e.source === 'google' && e.calendar_name ? ` · <span style="color:var(--text-muted)">${esc(e.calendar_name)}</span>` : ''
    }</div></div>`
  );
  if (e.description) rows.push(`<div class="ev-row"><span class="ev-ico">📝</span><div style="white-space:pre-wrap">${esc(e.description)}</div></div>`);
  const editable = e.source !== 'google';
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header" style="border-left:5px solid ${colour};padding-left:14px">
        <h3>${esc(e.title)}</h3><p>${e.source === 'google' ? 'From Google Calendar' : 'Portal event'}</p>
      </div>
      <div class="wf-modal-body ev-detail">${rows.join('')}</div>
      <div class="wf-modal-footer">
        ${editable ? `<button type="button" class="btn btn-ghost wf-action" data-action="delete-event" data-event-id="${esc(e.id)}" style="margin-right:auto">Delete</button>` : ''}
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Close</button>
        ${editable ? `<button type="button" class="btn btn-primary wf-action" data-action="edit-event" data-event-id="${esc(e.id)}">Edit</button>` : ''}
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
}

function openEditEventModal(id) {
  const e = (store.calendar?.events || []).find((x) => String(x.id) === String(id));
  if (!e) return showToast('Event not found', true);
  if (e.source === 'google') return showToast('Google events are read-only here — edit them in Google Calendar', true);
  const dateVal = (e.start || '').slice(0, 10);
  const timeVal = e.all_day ? '' : (e.start || '').slice(11, 16);
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Edit event</h3><p>Portal events only — Google events stay read-only.</p></div>
      <div class="wf-modal-body">
        <label class="field field-full"><span>Title</span><input type="text" id="ee-title" value="${esc(e.title)}"></label>
        <label class="field field-full"><span>Date</span><input type="date" id="ee-date" value="${esc(dateVal)}"></label>
        <label class="field field-full"><span>Time <small>(leave empty for all-day)</small></span><input type="time" id="ee-time" value="${esc(timeVal)}"></label>
        <label class="field field-full"><span>Location</span><input type="text" id="ee-location" value="${esc(e.location || '')}"></label>
        <label class="field field-full"><span>Description</span><textarea id="ee-description" rows="3">${esc(e.description || '')}</textarea></label>
      </div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="ee-save">Save</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('ee-save').onclick = async () => {
    const title = document.getElementById('ee-title').value.trim();
    const date = document.getElementById('ee-date').value;
    const time = document.getElementById('ee-time').value;
    if (!title) return showToast('Give the event a title', true);
    if (!date) return showToast('Pick a date', true);
    const allDay = !time;
    const start = allDay ? date : `${date}T${time}:00`;
    try {
      await api(`/events/${e.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title,
          start,
          end: start,
          all_day: allDay,
          location: document.getElementById('ee-location').value.trim() || null,
          description: document.getElementById('ee-description').value.trim() || null,
        }),
      });
      closeModal();
      showToast('Event updated');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

function renderCalendar(data) {
  const users = data.users || [];
  // Member filter: hide events for unticked users; shared (null user_id) events always show.
  const events = (data.events || []).filter((e) => e.user_id == null || !calFilterHidden.has(e.user_id));
  if (!calCursor) calCursor = new Date();
  const todayIso = calYmd(new Date());

  // Right-hand agenda panel: upcoming events from today onward
  const upcoming = events
    .filter((e) => (e.start || '').slice(0, 10) >= todayIso)
    .sort((a, b) => (a.start || '').localeCompare(b.start || ''))
    .slice(0, 12);
  document.getElementById('calendar-agenda').innerHTML = upcoming.length
    ? upcoming.map((e) => calAgendaRow(users, e)).join('')
    : '<p class="hint-small">No upcoming events.</p>';

  document.querySelectorAll('[data-action^="cal-view-"]').forEach((b) => {
    b.classList.toggle('active', b.dataset.action === `cal-view-${calView}`);
  });

  const label = document.getElementById('cal-month-label');
  const grid = document.getElementById('calendar-grid');

  if (calView === 'agenda') {
    label.textContent = 'Agenda';
    grid.className = 'calendar-agenda-list';
    const sorted = [...events].sort((a, b) => (a.start || '').localeCompare(b.start || ''));
    grid.innerHTML = sorted.length
      ? sorted.map((e) => calAgendaRow(users, e)).join('')
      : '<p class="hint-small">No events yet.</p>';
    return;
  }

  grid.className = 'calendar-week';
  const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const cells = [];
  if (calView === 'week') {
    const start = calStartOfWeek(calCursor);
    label.textContent = `Week of ${start.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`;
    for (let i = 0; i < 7; i++) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      cells.push(d);
    }
  } else {
    const first = new Date(calCursor.getFullYear(), calCursor.getMonth(), 1);
    label.textContent = first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    const lead = (first.getDay() + 6) % 7;
    const gridStart = new Date(first);
    gridStart.setDate(1 - lead);
    for (let i = 0; i < 42; i++) {
      const d = new Date(gridStart);
      d.setDate(gridStart.getDate() + i);
      cells.push(d);
    }
  }

  let html = dayNames.map((d) => `<div class="cal-day-header">${d}</div>`).join('');
  html += cells
    .map((d) => {
      const iso = calYmd(d);
      const muted = calView === 'month' && d.getMonth() !== calCursor.getMonth();
      const dayEvents = events.filter((e) => (e.start || '').slice(0, 10) === iso);
      return `
      <div class="cal-day${iso === todayIso ? ' today' : ''}"${muted ? ' style="opacity:.4"' : ''}>
        <div class="cal-day-num">${d.getDate()}</div>
        ${dayEvents
          .slice(0, 4)
          .map(
            (e) => `<div class="cal-event wf-action" data-action="event-detail" data-event-id="${esc(e.id)}" style="background:${userColour(users, e.user_id)}" title="${esc(e.title)}">${e.all_day ? '' : esc(fmt.time(e.start)) + ' '}${esc(e.title)}</div>`
          )
          .join('')}
        ${dayEvents.length > 4 ? `<div class="cal-more wf-action" data-action="cal-view-agenda">+${dayEvents.length - 4} more</div>` : ''}
      </div>`;
    })
    .join('');
  grid.innerHTML = html;
}

function renderFinances(data) {
  const { bills, transactions, accounts, budgets, savings_goals, summary, connections = [], banking_configured, categories = [], category_breakdown = [] } = data;

  document.getElementById('finance-stats').innerHTML = `
    <div class="stat"><span>${fmt.gbp(summary.monthly_income)}</span><label>Monthly income</label><div class="stat-trend up">All accounts</div></div>
    <div class="stat"><span>${fmt.gbp(summary.monthly_spent)}</span><label>Spent</label><div class="stat-trend neutral">This month</div></div>
    <div class="stat"><span>${fmt.gbp(summary.bills_due_this_month)}</span><label>Bills left</label><div class="stat-trend down">Unpaid</div></div>
    <div class="stat"><span>${fmt.gbp(summary.joint_balance)}</span><label>Current accounts</label><div class="stat-trend up">Live balance</div></div>`;

  const bankEl = document.getElementById('bank-connections');
  const connectBtn = document.getElementById('connect-bank-btn');
  if (connectBtn) {
    connectBtn.disabled = !banking_configured;
    connectBtn.title = banking_configured ? '' : 'Configure TrueLayer in .env';
  }
  if (connections.length) {
    bankEl.style.display = '';
    bankEl.innerHTML = `
      <div class="card-header"><h3>Connected banks</h3><p>Open Banking — last sync pulls balances &amp; transactions</p></div>
      ${connections
        .map(
          (c) => {
            const needsReauth = c.status === 'needs_reauth';
            return `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">🏦</div>
            <div>
              <div class="connection-name">${esc(c.provider_name)}</div>
              <div class="connection-status ${needsReauth ? '' : 'connected'}">${needsReauth
                ? '⚠️ Needs re-connect — sign in again to resume syncing'
                : (c.last_synced_at ? 'Synced ' + fmt.datetime(c.last_synced_at) : 'Connected — tap Sync all banks')}</div>
            </div>
          </div>
          ${needsReauth ? `<button class="btn btn-sm btn-primary wf-action" data-action="connect-bank-provider" data-provider-id="${esc(c.provider_id)}">Reconnect</button>` : ''}
          <button class="btn btn-sm btn-ghost wf-action" data-action="disconnect-bank" data-connection-id="${c.id}">Disconnect</button>
        </div>`;
          }
        )
        .join('')}`;
  } else {
    bankEl.style.display = banking_configured ? '' : 'none';
    bankEl.innerHTML = banking_configured
      ? `<div class="card-header"><h3>Connect your accounts</h3><p>Link Starling, Revolut, Amex and Virgin credit card to see everything in one place.</p></div>`
      : '';
  }

  document.getElementById('accounts-row').innerHTML = accounts
    .map(
      (a) => `
    <div class="account-tile ${a.type}${a.linked ? ' linked' : ''}">
      <div class="account-tile-name">${esc(a.name)}${a.linked ? ' <span class="linked-badge">Live</span>' : ''}</div>
      <div class="account-tile-balance">${fmt.gbp(a.balance)}</div>
      <div class="account-tile-inst">${esc(a.institution)}</div>
      <div class="account-tile-actions">
        <button class="acct-btn wf-action" data-action="rename-account" data-account-id="${a.id}" data-account-name="${esc(a.name)}">Rename</button>
        <button class="acct-btn wf-action" data-action="hide-account" data-account-id="${a.id}">Hide</button>
      </div>
    </div>`
    )
    .join('') + '<button class="acct-btn acct-hidden-link wf-action" data-action="show-hidden-accounts">Hidden…</button>';

  document.getElementById('finance-bills').innerHTML = bills
    .map((b) => billRow(b))
    .join('') || '<p class="hint-small">No bills yet — add one above.</p>';

  const budgetedCats = new Set(budgets.map((b) => b.category));
  document.getElementById('finance-budgets').innerHTML =
    (budgets.map((b) => budgetRow(b)).join('') ||
      '<p class="hint-small">No budgets yet — set a monthly target for a spending category.</p>') +
    `<button class="acct-btn wf-action" data-action="add-budget">+ Budget</button>`;
  window._budgetedCats = budgetedCats;

  document.getElementById('finance-savings').innerHTML =
    (savings_goals.map((g) => savingsRow(g)).join('') ||
      '<p class="hint-small">No savings goals yet — add one to track progress.</p>') +
    `<button class="acct-btn wf-action" data-action="add-savings">+ Goal</button>`;

  if (data.merged_recurring) {
    renderMergedRecurring(data.merged_recurring);
  }

  document.getElementById('finance-transactions').innerHTML = transactions
    .map((t) => {
      const opts = categories.map((c) => `<option value="${esc(c)}"${c === t.category ? ' selected' : ''}>${esc(c)}</option>`).join('');
      const showRaw = t.display_name && t.display_name !== t.description;
      return `
    <tr>
      <td>${fmt.date(t.date)}</td>
      <td>${esc(t.display_name || t.description)}${showRaw ? `<br><span class="txn-raw">${esc(t.description)}</span>` : ''}</td>
      <td><select class="txn-cat" data-txn-id="${t.id}" aria-label="Category">${opts}</select></td>
      <td>${personSelect(t)}</td>
      <td>${esc(t.account)}</td>
      <td class="amount-cell ${t.amount >= 0 ? 'positive' : 'negative'}">${fmt.gbp(t.amount)}</td>
    </tr>`;
    })
    .join('') || '<tr><td colspan="6" class="hint-small">No transactions yet — log one, import a CSV or connect a bank.</td></tr>';

  renderCategoryBreakdown(category_breakdown);
}

function renderCategoryBreakdown(items) {
  const card = document.getElementById('category-breakdown-card');
  const el = document.getElementById('category-breakdown');
  if (!card || !el) return;
  if (!items || !items.length) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';
  const max = Math.max(...items.map((i) => i.spent), 1);
  el.innerHTML = items
    .map(
      (i) => `
      <div class="budget-row" style="margin-bottom:10px">
        <div class="budget-row-head"><span>${esc(i.category)}</span><span>${fmt.gbp(i.spent)} · ${i.count}</span></div>
        <div class="progress-bar budget"><div class="progress-fill" style="width:${Math.round((i.spent / max) * 100)}%"></div></div>
      </div>`
    )
    .join('');
}

// --- Finances: per-transaction "who spent" tagging + forecast + by-person ---
// Person keys the backend uses: 'luke' | 'partner' | 'joint' | null/'unassigned'.
// Display names are fixed for this household (partner === Laura).
const PERSON_LABELS = { luke: 'Luke', partner: 'Laura', joint: 'Joint', unassigned: 'Unassigned' };
// Options for the compact per-row selector — value '' maps to null (untagged).
const PERSON_OPTIONS = [['', '—'], ['luke', 'Luke'], ['partner', 'Laura'], ['joint', 'Joint']];

function personSelect(t) {
  const cur = t.person || '';
  const opts = PERSON_OPTIONS
    .map(([v, l]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(l)}</option>`)
    .join('');
  return `<select class="txn-person" data-role="txn-person" data-txn-id="${t.id}" aria-label="Who spent">${opts}</select>`;
}

// Money-left-this-month forecast card (own endpoint; degrades gracefully).
async function loadForecast() {
  const el = document.getElementById('finance-forecast');
  if (!el) return;
  try {
    renderForecast(await api('/finances/forecast'));
  } catch {
    el.innerHTML = '<p class="hint-small">Forecast unavailable.</p>';
  }
}

function renderForecast(d) {
  const el = document.getElementById('finance-forecast');
  if (!el) return;
  if (!d || d.has_data === false) {
    el.innerHTML = '<p class="hint-small">Not enough data yet — log some transactions to project your month-end balance.</p>';
    return;
  }
  const positive = Number(d.projected_month_end_cash) >= 0;
  const days = Number(d.days_left);
  el.innerHTML = `
    <div class="forecast-figure ${positive ? 'pos' : 'neg'}">${fmt.gbp(d.projected_month_end_cash)}</div>
    <p class="forecast-sub">projected balance end of ${esc(d.month_label)} · before any income lands</p>
    <p class="hint-small forecast-breakdown">Now ${fmt.gbp(d.current_cash)} − projected everyday spend ${fmt.gbp(d.projected_further_spend)}</p>
    <p class="hint-small">${days} day${days === 1 ? '' : 's'} left · spent ${fmt.gbp(d.spent_so_far)} so far (~${fmt.gbp(d.avg_daily_spend)}/day) · ${fmt.gbp(d.bills_due_remaining)} bills unpaid</p>`;
}

// Spending-by-person mini-breakdown (own endpoint; degrades gracefully).
async function loadByPerson() {
  const el = document.getElementById('finance-by-person');
  if (!el) return;
  try {
    renderByPerson(await api('/finances/by-person'));
  } catch {
    el.innerHTML = '<p class="hint-small">Spending by person unavailable.</p>';
  }
}

function renderByPerson(d) {
  const el = document.getElementById('finance-by-person');
  if (!el) return;
  const people = ((d && d.people) || []).filter((p) => Math.abs(Number(p.amount) || 0) > 0);
  if (!people.length) {
    el.innerHTML = '<p class="hint-small">No spending tagged yet — set “who” on a transaction to see the split.</p>';
    return;
  }
  const max = Math.max(...people.map((p) => Math.abs(Number(p.amount) || 0)), 1);
  el.innerHTML = people
    .map(
      (p) => `
      <div class="budget-row" style="margin-bottom:10px">
        <div class="budget-row-head"><span>${esc(PERSON_LABELS[p.person] || p.person)}</span><span>${fmt.gbp(p.amount)}</span></div>
        <div class="progress-bar budget"><div class="progress-fill" style="width:${Math.round((Math.abs(Number(p.amount) || 0) / max) * 100)}%"></div></div>
      </div>`
    )
    .join('');
}

// --- Finances: Insights card ---
async function loadInsights() {
  const el = document.getElementById('finance-insights');
  if (!el) return;
  try {
    renderInsights(await api('/finances/insights'));
  } catch {
    // Older backend without the endpoint — leave a gentle placeholder.
    el.innerHTML = '<p class="hint-small">Insights unavailable.</p>';
  }
}

function renderInsights(d) {
  const el = document.getElementById('finance-insights');
  if (!el) return;
  if (!d || !d.has_data) {
    el.innerHTML = '<p class="hint-small">Not enough data yet — log or import some transactions to see spending insights.</p>';
    return;
  }
  const parts = [];
  let delta = '';
  if (d.spend_delta_pct != null) {
    const up = d.spend_delta_pct > 0;
    delta = ` · <span class="${up ? 'insight-up' : 'insight-down'}">${up ? '▲' : '▼'} ${Math.abs(Math.round(d.spend_delta_pct))}% ${up ? 'more' : 'less'} than ${esc(d.last_month.label)}</span>`;
  }
  parts.push(`<p class="insight-headline"><strong>${fmt.gbp(d.this_month.spend)}</strong> spent in ${esc(d.this_month.label)}${delta}</p>`);
  if (d.this_month.income) {
    parts.push(`<p class="hint-small">Income ${fmt.gbp(d.this_month.income)} this month</p>`);
  }
  const cats = d.top_categories || [];
  if (cats.length) {
    const max = Math.max(...cats.map((c) => c.amount), 1);
    const rows = cats
      .slice(0, 5)
      .map(
        (c) => `
      <div class="budget-row" style="margin-bottom:10px">
        <div class="budget-row-head"><span>${esc(c.category)}</span><span>${fmt.gbp(c.amount)}</span></div>
        <div class="progress-bar budget"><div class="progress-fill" style="width:${Math.round((c.amount / max) * 100)}%"></div></div>
      </div>`
      )
      .join('');
    parts.push(`<div class="insight-section"><h4 class="insight-subhead">Top categories</h4>${rows}</div>`);
  }
  const subs = d.subscriptions;
  if (subs && subs.count) {
    parts.push(`<p class="insight-line">🔁 ${subs.count} subscription${subs.count === 1 ? '' : 's'} · ${fmt.gbp(subs.monthly_total)}/mo (${fmt.gbp(subs.annualised)}/yr)</p>`);
  }
  if (d.biggest_expense) {
    parts.push(`<p class="insight-line">💥 Biggest this month: ${esc(d.biggest_expense.description)} — ${fmt.gbp(d.biggest_expense.amount)}</p>`);
  }
  el.innerHTML = parts.join('');
}

// --- Finances: Net worth + manual assets (inline CRUD, mirrors tradespeople) ---
const ASSET_TYPES = [
  ['property', 'Property'],
  ['vehicle', 'Vehicle'],
  ['savings', 'Savings'],
  ['investment', 'Investment'],
  ['other', 'Other'],
];
const ASSET_TYPE_LABELS = { property: 'Property', vehicle: 'Vehicle', savings: 'Savings', investment: 'Investment', other: 'Other' };

// Net worth and assets share the same data, so one loader refreshes both.
async function loadNetWorth() {
  const headEl = document.getElementById('networth-headline');
  const listEl = document.getElementById('assets-list');
  if (!headEl || !listEl) return;
  try {
    const [nw, assetsData] = await Promise.all([api('/finances/networth'), api('/assets')]);
    store.assets = assetsData.assets || [];
    renderNetWorth(nw);
    renderAssets(store.assets);
  } catch {
    // Older backend without these endpoints — leave the card as-is.
  }
}

function renderNetWorth(nw) {
  const el = document.getElementById('networth-headline');
  if (!el || !nw) return;
  el.innerHTML = `
    <div class="networth-headline">${fmt.gbp(nw.net_worth)}</div>
    <div class="networth-stats">
      <div class="networth-stat"><span>${fmt.gbp(nw.cash_total)}</span><label>Cash</label></div>
      <div class="networth-stat"><span>${fmt.gbp(nw.assets_total)}</span><label>Assets</label></div>
      <div class="networth-stat"><span class="networth-neg">${fmt.gbp(nw.liabilities_total)}</span><label>Liabilities</label></div>
    </div>`;
}

function findAsset(id) {
  return (store.assets || []).find((a) => String(a.id) === String(id));
}

function assetRowInner(a) {
  return `
        <div>
          <strong>${esc(a.name)}</strong>
          <span class="asset-type-badge ${esc(a.type)}">${esc(ASSET_TYPE_LABELS[a.type] || a.type)}</span>
          ${a.notes ? `<p class="hint-small">${esc(a.notes)}</p>` : ''}
        </div>
        <div class="subscription-actions">
          <span class="asset-value">${fmt.gbp(a.value)}</span>
          <button class="bill-edit-btn wf-action" data-action="edit-asset" data-asset-id="${a.id}" title="Edit asset" aria-label="Edit asset">✎</button>
        </div>`;
}

function assetEditInner(a) {
  const opts = ASSET_TYPES.map(([v, l]) => `<option value="${v}"${v === a.type ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" data-asset-id="${a.id}">
      <input type="text" class="te-input" data-f="name" value="${esc(a.name)}" placeholder="Name">
      <div class="row-edit-fields">
        <label>Type<select data-f="type">${opts}</select></label>
        <label>Value £<input type="number" step="0.01" min="0" data-f="value" value="${a.value}"></label>
        <label>Notes<input type="text" data-f="notes" value="${esc(a.notes || '')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-asset-inline" data-asset-id="${a.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-asset-inline" data-asset-id="${a.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-asset" data-asset-id="${a.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function assetAddInner() {
  const opts = ASSET_TYPES.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  return `
    <div class="row-edit" id="asset-add-form">
      <input type="text" class="te-input" data-f="name" placeholder="Name (e.g. Family home, VW Golf)">
      <div class="row-edit-fields">
        <label>Type<select data-f="type">${opts}</select></label>
        <label>Value £<input type="number" step="0.01" min="0" data-f="value" placeholder="0"></label>
        <label>Notes<input type="text" data-f="notes" placeholder="Optional detail"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-asset-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="assets-list">Cancel</button>
      </div>
    </div>`;
}

function renderAssets(assets) {
  const list = document.getElementById('assets-list');
  if (!list) return;
  list.innerHTML = (assets && assets.length)
    ? assets.map((a) => `<div class="maintenance-row" data-asset-id="${a.id}">${assetRowInner(a)}</div>`).join('')
    : '<div class="vault-empty"><p>No assets added yet.</p><p class="hint-small">Add your house, cars and valuables to see your true net worth.</p></div>';
}

// --- Finances: Trend charts (spending bars + net-worth line) ----------------
// Inline SVGs only — no external chart libraries (CSP blocks CDNs). All colours
// go through CSS variables (var(--accent) etc.) so both light and dark work.

// Compact currency for tight chart axes/bar labels; hovers still use full fmt.gbp.
function compactGbp(n) {
  const v = Number(n) || 0;
  if (Math.abs(v) >= 1000) return `£${(v / 1000).toFixed(1)}k`;
  return `£${Math.round(v)}`;
}

async function loadTrends() {
  const spendEl = document.getElementById('trend-spend');
  const nwEl = document.getElementById('trend-networth');
  if (!spendEl || !nwEl) return;
  try {
    const [spend, nw] = await Promise.all([
      api('/finances/spend-trend'),
      api('/finances/networth-trend'),
    ]);
    spendEl.innerHTML = renderSpendTrend(spend?.months || []);
    nwEl.innerHTML = renderNetWorthTrend(nw?.points || []);
  } catch {
    // Older backend without these endpoints — leave a gentle placeholder.
    spendEl.innerHTML = '<p class="hint-small">Trends unavailable.</p>';
    nwEl.innerHTML = '';
  }
}

// Bar chart: last 6 months of spend. Bars scale to the max; all-zero → note.
function renderSpendTrend(months) {
  if (!months.length) return '<p class="hint-small">No spending data yet.</p>';
  const max = Math.max(...months.map((m) => m.spend || 0), 0);
  if (max <= 0) return '<p class="hint-small">No spending recorded in the last 6 months yet.</p>';
  const W = 320, H = 170, padL = 8, padR = 8, padT = 20, padB = 30;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const baseY = padT + plotH;
  const n = months.length;
  const slot = plotW / n;
  const barW = Math.min(slot * 0.6, 46);
  const bars = months.map((m, i) => {
    const spend = m.spend || 0;
    const h = (spend / max) * plotH;
    const x = padL + i * slot + (slot - barW) / 2;
    const y = baseY - h;
    const cx = x + barW / 2;
    const valLabel = spend > 0
      ? `<text x="${cx.toFixed(1)}" y="${(y - 5).toFixed(1)}" text-anchor="middle" class="trend-bar-val">${compactGbp(spend)}</text>`
      : '';
    return `<g>
        <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3" class="trend-bar"><title>${esc(m.label)}: ${fmt.gbp(spend)}</title></rect>
        ${valLabel}
        <text x="${cx.toFixed(1)}" y="${H - 10}" text-anchor="middle" class="trend-axis-label">${esc(m.label)}</text>
      </g>`;
  }).join('');
  return `<svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Spending over the last 6 months">
    <line x1="${padL}" y1="${baseY}" x2="${W - padR}" y2="${baseY}" class="trend-axis-line"/>
    ${bars}
  </svg>`;
}

// Area+line chart: net worth over time. 0/1 points → friendly "history builds up" note.
function renderNetWorthTrend(points) {
  if (!points || points.length <= 1) {
    return '<p class="hint-small">Net-worth history will build up over the coming days — snapshots are saved automatically.</p>';
  }
  const W = 320, H = 170, padL = 46, padR = 10, padT = 14, padB = 24;
  const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB;
  const vals = points.map((p) => Number(p.net_worth) || 0);
  const rawMin = Math.min(...vals), rawMax = Math.max(...vals);
  let min = rawMin, max = rawMax;
  if (max === min) { max += 1; min -= 1; } // flat line → centre it vertically
  const n = points.length;
  const sx = (i) => x0 + (n === 1 ? 0 : (i / (n - 1)) * (x1 - x0));
  const sy = (v) => y1 - ((v - min) / (max - min)) * (y1 - y0);
  const pts = points.map((p, i) => `${sx(i).toFixed(1)},${sy(vals[i]).toFixed(1)}`);
  const linePath = 'M' + pts.join(' L');
  const areaPath = `M${x0.toFixed(1)},${y1.toFixed(1)} L${pts.join(' L')} L${x1.toFixed(1)},${y1.toFixed(1)} Z`;
  const shortDate = (d) => {
    const dt = new Date(d);
    return isNaN(dt) ? '' : dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  };
  const last = n - 1;
  return `<svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Net worth over time">
    <line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}" class="trend-axis-line"/>
    <path d="${areaPath}" class="trend-area"/>
    <path d="${linePath}" class="trend-line"/>
    <circle cx="${sx(last).toFixed(1)}" cy="${sy(vals[last]).toFixed(1)}" r="3" class="trend-dot"><title>${esc(shortDate(points[last].date))}: ${fmt.gbp(vals[last])}</title></circle>
    <text x="${x0 - 6}" y="${y0 + 4}" text-anchor="end" class="trend-axis-label">${compactGbp(rawMax)}</text>
    <text x="${x0 - 6}" y="${y1}" text-anchor="end" class="trend-axis-label">${compactGbp(rawMin)}</text>
    <text x="${x0}" y="${H - 8}" text-anchor="start" class="trend-axis-label">${esc(shortDate(points[0].date))}</text>
    <text x="${x1}" y="${H - 8}" text-anchor="end" class="trend-axis-label">${esc(shortDate(points[last].date))}</text>
  </svg>`;
}

// --- Home care: Chores rotation (inline CRUD, mirrors tradespeople) ----------
const CHORE_CADENCES = [['weekly', 'Weekly'], ['fortnightly', 'Fortnightly'], ['monthly', 'Monthly']];
const CADENCE_LABELS = { weekly: 'Weekly', fortnightly: 'Fortnightly', monthly: 'Monthly' };

async function loadChores() {
  const list = document.getElementById('chores-list');
  if (!list) return;
  try {
    const data = await api('/chores');
    store.chores = data.chores || [];
    renderChores(store.chores);
  } catch {
    // Older backend without the endpoint — leave a gentle placeholder.
    list.innerHTML = '<p class="hint-small">Chores unavailable.</p>';
  }
}

function findChore(id) {
  return (store.chores || []).find((c) => String(c.id) === String(id));
}

// Compare next_due (YYYY-MM-DD) to today for the overdue/due-today styling.
function choreDueMeta(nextDue) {
  if (!nextDue) return { cls: '', label: 'No date set' };
  const due = String(nextDue).slice(0, 10);
  const today = todayIsoDate();
  if (due < today) return { cls: 'overdue', label: `Overdue · ${fmt.date(nextDue)}` };
  if (due === today) return { cls: 'due-today', label: 'Due today' };
  return { cls: '', label: `Due ${fmt.date(nextDue)}` };
}

// "Anyone" (null) + the two household members — reuses dashboard user list.
function choreAssigneeOptions(selectedId) {
  const users = store.dashboard?.users || [];
  const anyoneSel = (selectedId == null || selectedId === '') ? ' selected' : '';
  const opts = users
    .map((u) => `<option value="${esc(u.id)}"${String(u.id) === String(selectedId ?? '') ? ' selected' : ''}>${esc(u.name)}</option>`)
    .join('');
  return `<option value=""${anyoneSel}>Anyone</option>${opts}`;
}

function choreRowInner(c) {
  const due = choreDueMeta(c.next_due);
  const who = c.assignee_name ? esc(c.assignee_name) : 'Anyone';
  return `
        <div>
          <strong>${esc(c.title)}</strong>
          <div class="subscription-meta">
            <span class="chore-turn-badge${c.assignee_name ? '' : ' anyone'}">${who}</span>
            <span>${esc(CADENCE_LABELS[c.cadence] || c.cadence)}</span>
            <span class="chore-due ${due.cls}">${due.label}</span>
            ${c.rotate ? '<span class="chore-rotate">🔁 Auto-swaps</span>' : ''}
          </div>
        </div>
        <div class="subscription-actions">
          <button class="btn btn-sm btn-primary wf-action" data-action="chore-done" data-chore-id="${c.id}">Done ✓</button>
          <button class="bill-edit-btn wf-action" data-action="edit-chore" data-chore-id="${c.id}" title="Edit chore" aria-label="Edit chore">✎</button>
        </div>`;
}

function choreEditInner(c) {
  const cadOpts = CHORE_CADENCES.map(([v, l]) => `<option value="${v}"${v === c.cadence ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" data-chore-id="${c.id}">
      <input type="text" class="te-input" data-f="title" value="${esc(c.title)}" placeholder="Chore (e.g. Take the bins out)">
      <div class="row-edit-fields">
        <label>Cadence<select data-f="cadence">${cadOpts}</select></label>
        <label>Whose turn<select data-f="assignee_id">${choreAssigneeOptions(c.assignee_id)}</select></label>
        <label>Next due<input type="date" data-f="next_due" value="${esc((c.next_due || '').slice(0, 10))}"></label>
        <label class="row-edit-check"><input type="checkbox" data-f="rotate"${c.rotate ? ' checked' : ''}> Auto-swap each time</label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-chore-inline" data-chore-id="${c.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-chore-inline" data-chore-id="${c.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-chore" data-chore-id="${c.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function choreAddInner() {
  const cadOpts = CHORE_CADENCES.map(([v, l]) => `<option value="${v}"${v === 'weekly' ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" id="chore-add-form">
      <input type="text" class="te-input" data-f="title" placeholder="Chore (e.g. Take the bins out)">
      <div class="row-edit-fields">
        <label>Cadence<select data-f="cadence">${cadOpts}</select></label>
        <label>Whose turn<select data-f="assignee_id">${choreAssigneeOptions('')}</select></label>
        <label>Next due<input type="date" data-f="next_due" value="${todayIsoDate()}"></label>
        <label class="row-edit-check"><input type="checkbox" data-f="rotate" checked> Auto-swap each time</label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-chore-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="chores-list">Cancel</button>
      </div>
    </div>`;
}

function renderChores(chores) {
  const list = document.getElementById('chores-list');
  if (!list) return;
  list.innerHTML = (chores && chores.length)
    ? chores.map((c) => `<div class="maintenance-row" data-chore-id="${c.id}">${choreRowInner(c)}</div>`).join('')
    : '<div class="vault-empty"><p>No chores yet</p><p class="hint-small">Add recurring jobs like bins, hoovering, or changing the bedding and they\'ll rotate between you.</p></div>';
}

// --- Home: Family occasions (birthdays & anniversaries) ---------------------
// Own endpoint (/api/occasions), already sorted soonest-first with countdowns
// computed server-side. We only format the countdown/next_date client-side.

const OCCASION_KINDS = [['birthday', '🎂 Birthday'], ['anniversary', '💍 Anniversary'], ['other', '📅 Other']];
const OCCASION_EMOJI = { birthday: '🎂', anniversary: '💍', other: '📅' };

// Format a YYYY-MM-DD as "18 Sep" (or "18 Sep 2027" with year). Parsed as a
// LOCAL date (not new Date(iso), which is UTC) to avoid an off-by-one shift.
function fmtShortDate(iso, withYear = false) {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return '';
  const opts = withYear
    ? { day: 'numeric', month: 'short', year: 'numeric' }
    : { day: 'numeric', month: 'short' };
  return new Date(y, m - 1, d).toLocaleDateString('en-GB', opts);
}

async function loadOccasions() {
  const list = document.getElementById('occasions-list');
  if (!list) return;
  try {
    const data = await api('/occasions');
    store.occasions = data.occasions || [];
    renderOccasions(store.occasions);
  } catch {
    list.innerHTML = '<div class="vault-empty"><p>Couldn\'t load occasions.</p></div>';
  }
}

function findOccasion(id) {
  return (store.occasions || []).find((o) => String(o.id) === String(id));
}

// Countdown label + highlight class from the server's days_until.
function occasionCountdown(o) {
  const d = o.days_until;
  if (d == null) return { label: '', cls: '' };
  if (d <= 0) return { label: 'Today! 🎉', cls: 'today' };
  const label = d === 1 ? 'in 1 day' : `in ${d} days`;
  return { label, cls: d <= 7 ? 'soon' : '' };
}

function occasionRowInner(o) {
  const emoji = OCCASION_EMOJI[o.kind] || '📅';
  const cd = occasionCountdown(o);
  const meta = [];
  if (o.person) meta.push(esc(o.person));
  if (o.next_date) meta.push(fmtShortDate(o.next_date));
  if (o.kind === 'birthday' && o.years > 0) meta.push(`turns ${o.years}`);
  return `
        <div class="occasion-main">
          <div class="occasion-title"><span class="occasion-emoji">${emoji}</span>${esc(o.title)}</div>
          <div class="subscription-meta">${meta.map((m) => `<span>${m}</span>`).join('')}</div>
          ${o.notes ? `<p class="hint-small">${esc(o.notes)}</p>` : ''}
        </div>
        <div class="occasion-side">
          ${cd.label ? `<span class="occasion-countdown ${cd.cls}">${cd.label}</span>` : ''}
          <button class="bill-edit-btn wf-action" data-action="edit-occasion" data-occasion-id="${o.id}" title="Edit occasion" aria-label="Edit occasion">✎</button>
        </div>`;
}

function occasionEditInner(o) {
  const kindOpts = OCCASION_KINDS.map(([v, l]) => `<option value="${v}"${v === o.kind ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" data-occasion-id="${o.id}">
      <input type="text" class="te-input" data-f="title" value="${esc(o.title)}" placeholder="Title">
      <div class="row-edit-fields">
        <label>Type<select data-f="kind">${kindOpts}</select></label>
        <label>Date (birth/wedding date)<input type="date" data-f="date" value="${esc((o.date || '').slice(0, 10))}"></label>
        <label>Person<input type="text" data-f="person" value="${esc(o.person || '')}" placeholder="e.g. Mum"></label>
        <label>Gift ideas / notes<input type="text" data-f="notes" value="${esc(o.notes || '')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-occasion-inline" data-occasion-id="${o.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-occasion-inline" data-occasion-id="${o.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-occasion" data-occasion-id="${o.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function occasionAddInner() {
  const kindOpts = OCCASION_KINDS.map(([v, l]) => `<option value="${v}"${v === 'birthday' ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" id="occasion-add-form">
      <input type="text" class="te-input" data-f="title" placeholder="Title (e.g. Mum's birthday)">
      <div class="row-edit-fields">
        <label>Type<select data-f="kind">${kindOpts}</select></label>
        <label>Date (birth/wedding date)<input type="date" data-f="date"></label>
        <label>Person<input type="text" data-f="person" placeholder="e.g. Mum"></label>
        <label>Gift ideas / notes<input type="text" data-f="notes" placeholder="Optional"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-occasion-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="occasions-list">Cancel</button>
      </div>
    </div>`;
}

function renderOccasions(list) {
  const el = document.getElementById('occasions-list');
  if (!el) return;
  el.innerHTML = (list && list.length)
    ? list.map((o) => `<div class="maintenance-row" data-occasion-id="${o.id}">${occasionRowInner(o)}</div>`).join('')
    : '<div class="vault-empty"><p>No occasions yet</p><p class="hint-small">Add birthdays and anniversaries to get a countdown and a reminder a week before.</p></div>';
}

// --- Home: Gift ideas / wishlists -------------------------------------------
// Own endpoint (/api/wishlist). Items are grouped by person (blank person →
// "Anyone / general"); within a group, purchased items sink to the bottom and
// render muted + struck-through. Reuses the .maintenance-row + .row-edit pattern.

const WISHLIST_GENERAL = '__general__';

async function loadWishlist() {
  const list = document.getElementById('wishlist-list');
  if (!list) return;
  try {
    const data = await api('/wishlist');
    store.wishlist = data.items || [];
    renderWishlist(store.wishlist);
  } catch {
    list.innerHTML = '<div class="vault-empty"><p>Couldn\'t load gift ideas.</p></div>';
  }
}

function findWishlist(id) {
  return (store.wishlist || []).find((w) => String(w.id) === String(id));
}

// Build a create/update payload from the inline row's fields (shared by add + edit).
function wishlistPayload(f) {
  const price = parseFloat(f.price);
  return {
    person: (f.person || '').trim() || null,
    title: (f.title || '').trim(),
    url: (f.url || '').trim() || null,
    price: Number.isFinite(price) ? price : null,
    notes: (f.notes || '').trim() || null,
  };
}

// Render the URL as a safe new-tab link only when it parses as a real http(s)
// URL; otherwise show it as plain muted text. Href is escaped in both cases.
function wishlistLink(url) {
  const u = (url || '').trim();
  if (!u) return '';
  let ok = false;
  try { const p = new URL(u); ok = p.protocol === 'http:' || p.protocol === 'https:'; } catch { ok = false; }
  if (ok) {
    return `<a class="wishlist-link" href="${esc(u)}" target="_blank" rel="noopener">Link ↗</a>`;
  }
  return `<span class="wishlist-link-plain">${esc(u)}</span>`;
}

function wishlistRowInner(w) {
  const meta = [];
  const price = parseFloat(w.price);
  if (Number.isFinite(price)) meta.push(fmt.gbp(price));
  const link = wishlistLink(w.url);
  if (link) meta.push(link);
  return `
        <div class="wishlist-main">
          <input type="checkbox" class="wishlist-check" data-wish-id="${w.id}"${w.purchased ? ' checked' : ''} title="${w.purchased ? 'Bought' : 'Mark as bought'}" aria-label="Mark as bought">
          <div class="wishlist-body">
            <div class="wishlist-title">${esc(w.title)}</div>
            ${meta.length ? `<div class="subscription-meta">${meta.map((m) => `<span>${m}</span>`).join('')}</div>` : ''}
            ${w.notes ? `<p class="hint-small">${esc(w.notes)}</p>` : ''}
          </div>
        </div>
        <div class="wishlist-side">
          <button class="bill-edit-btn wf-action" data-action="edit-wishlist" data-wish-id="${w.id}" title="Edit gift idea" aria-label="Edit gift idea">✎</button>
        </div>`;
}

function wishlistEditInner(w) {
  return `
    <div class="row-edit" data-wish-id="${w.id}">
      <input type="text" class="te-input" data-f="title" value="${esc(w.title)}" placeholder="Gift idea">
      <div class="row-edit-fields">
        <label>Person<input type="text" data-f="person" value="${esc(w.person || '')}" placeholder="e.g. Arthur"></label>
        <label>Link<input type="url" data-f="url" value="${esc(w.url || '')}" placeholder="https://…"></label>
        <label>Price £<input type="number" step="0.01" min="0" data-f="price" value="${Number.isFinite(parseFloat(w.price)) ? w.price : ''}"></label>
        <label>Notes<input type="text" data-f="notes" value="${esc(w.notes || '')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-wishlist-inline" data-wish-id="${w.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-wishlist-inline" data-wish-id="${w.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-wishlist" data-wish-id="${w.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function wishlistAddInner() {
  return `
    <div class="row-edit" id="wishlist-add-form">
      <input type="text" class="te-input" data-f="title" placeholder="Gift idea (e.g. Lego set)">
      <div class="row-edit-fields">
        <label>Person<input type="text" data-f="person" placeholder="e.g. Arthur"></label>
        <label>Link<input type="url" data-f="url" placeholder="https://…"></label>
        <label>Price £<input type="number" step="0.01" min="0" data-f="price" placeholder="0"></label>
        <label>Notes<input type="text" data-f="notes" placeholder="Optional"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-wishlist-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="wishlist-list">Cancel</button>
      </div>
    </div>`;
}

function renderWishlist(items) {
  const el = document.getElementById('wishlist-list');
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = '<div class="vault-empty"><p>No gift ideas yet</p><p class="hint-small">Jot down presents for birthdays and Christmas so you\'re never stuck.</p></div>';
    return;
  }
  // Group by person; blank person → "Anyone / general".
  const groups = new Map();
  items.forEach((w) => {
    const key = (w.person && w.person.trim()) ? w.person.trim() : WISHLIST_GENERAL;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(w);
  });
  // Named people first (alphabetical), the general group last.
  const keys = [...groups.keys()].filter((k) => k !== WISHLIST_GENERAL).sort((a, b) => a.localeCompare(b));
  if (groups.has(WISHLIST_GENERAL)) keys.push(WISHLIST_GENERAL);
  el.innerHTML = keys.map((key) => {
    const label = key === WISHLIST_GENERAL ? 'Anyone / general' : key;
    // Purchased items sink to the bottom of their group.
    const rows = groups.get(key).slice().sort((a, b) => (a.purchased ? 1 : 0) - (b.purchased ? 1 : 0));
    const rowsHtml = rows
      .map((w) => `<div class="maintenance-row wishlist-row${w.purchased ? ' wishlist-purchased' : ''}" data-wish-id="${w.id}">${wishlistRowInner(w)}</div>`)
      .join('');
    return `<div class="wishlist-group"><h4 class="wishlist-group-head">${esc(label)}</h4>${rowsHtml}</div>`;
  }).join('');
}

// Toggle an item's "Bought" state, then reload so it re-sorts within its group.
function toggleWishlistPurchased(id, purchased) {
  api(`/wishlist/${id}/purchased`, {
    method: 'POST',
    body: JSON.stringify({ purchased }),
  }).then(() => loadWishlist())
    .then(() => showToast(purchased ? 'Marked as bought ✓' : 'Marked as not bought'))
    .catch((err) => showToast(err.message, true));
}

// --- Home care: Home inventory / warranty tracker ---------------------------
// Own endpoint (/api/inventory). Warranty status is computed client-side from
// warranty_expiry vs today so the pill stays live without a server round-trip.

const INVENTORY_CATEGORIES = [['appliance', 'Appliance'], ['electronics', 'Electronics'], ['furniture', 'Furniture'], ['valuable', 'Valuable'], ['other', 'Other']];

// Red (expired) / amber (ends within 30 days) / green (in warranty) pill.
function warrantyPill(expiry) {
  if (!expiry) return '';
  const [y, m, d] = expiry.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return '';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const exp = new Date(y, m - 1, d);
  const days = Math.round((exp - today) / 86400000);
  const dateLabel = fmtShortDate(expiry, true);
  if (days < 0) return '<span class="warranty-pill expired">Warranty expired</span>';
  if (days <= 30) return `<span class="warranty-pill ending">Warranty ends ${dateLabel}</span>`;
  return `<span class="warranty-pill active">In warranty (${dateLabel})</span>`;
}

async function loadInventory() {
  const list = document.getElementById('inventory-list');
  if (!list) return;
  try {
    const data = await api('/inventory');
    store.inventory = data.items || [];
    renderInventory(store.inventory);
  } catch {
    list.innerHTML = '<div class="vault-empty"><p>Couldn\'t load inventory.</p></div>';
  }
}

function findInventory(id) {
  return (store.inventory || []).find((it) => String(it.id) === String(id));
}

// Build a create/update payload from the inline row's fields (shared by add + edit).
function inventoryPayload(f) {
  const price = parseFloat(f.price);
  return {
    name: f.name.trim(),
    category: f.category || 'other',
    brand: (f.brand || '').trim() || null,
    model: (f.model || '').trim() || null,
    serial: (f.serial || '').trim() || null,
    purchase_date: f.purchase_date || null,
    price: Number.isFinite(price) ? price : null,
    warranty_expiry: f.warranty_expiry || null,
    notes: (f.notes || '').trim() || null,
  };
}

function inventoryRowInner(it) {
  const catLabel = (INVENTORY_CATEGORIES.find(([v]) => v === it.category) || [null, 'Other'])[1];
  const meta = [];
  const bm = [it.brand, it.model].filter(Boolean).join(' ');
  if (bm) meta.push(esc(bm));
  if (it.serial) meta.push(`SN ${esc(it.serial)}`);
  if (it.price) meta.push(fmt.gbp(it.price));
  return `
        <div class="inventory-main">
          <div class="inventory-title">${esc(it.name)}<span class="inv-cat-badge ${esc(it.category)}">${esc(catLabel)}</span></div>
          <div class="subscription-meta">${meta.map((m) => `<span>${m}</span>`).join('')}</div>
          ${it.notes ? `<p class="hint-small">${esc(it.notes)}</p>` : ''}
        </div>
        <div class="inventory-side">
          ${warrantyPill(it.warranty_expiry) || '<span class="warranty-pill none">—</span>'}
          <button class="bill-edit-btn wf-action" data-action="edit-inventory" data-inv-id="${it.id}" title="Edit item" aria-label="Edit inventory item">✎</button>
        </div>`;
}

function inventoryEditInner(it) {
  const catOpts = INVENTORY_CATEGORIES.map(([v, l]) => `<option value="${v}"${v === it.category ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" data-inv-id="${it.id}">
      <input type="text" class="te-input" data-f="name" value="${esc(it.name)}" placeholder="Name">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${catOpts}</select></label>
        <label>Brand<input type="text" data-f="brand" value="${esc(it.brand || '')}"></label>
        <label>Model<input type="text" data-f="model" value="${esc(it.model || '')}"></label>
        <label>Serial<input type="text" data-f="serial" value="${esc(it.serial || '')}"></label>
        <label>Purchased<input type="date" data-f="purchase_date" value="${esc((it.purchase_date || '').slice(0, 10))}"></label>
        <label>Price £<input type="number" step="0.01" min="0" data-f="price" value="${it.price ?? ''}"></label>
        <label>Warranty expiry<input type="date" data-f="warranty_expiry" value="${esc((it.warranty_expiry || '').slice(0, 10))}"></label>
        <label>Notes<input type="text" data-f="notes" value="${esc(it.notes || '')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-inventory-inline" data-inv-id="${it.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-inventory-inline" data-inv-id="${it.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-inventory" data-inv-id="${it.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function inventoryAddInner() {
  const catOpts = INVENTORY_CATEGORIES.map(([v, l]) => `<option value="${v}"${v === 'other' ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" id="inventory-add-form">
      <input type="text" class="te-input" data-f="name" placeholder="Name (e.g. Samsung fridge)">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${catOpts}</select></label>
        <label>Brand<input type="text" data-f="brand" placeholder="e.g. Samsung"></label>
        <label>Model<input type="text" data-f="model" placeholder="e.g. RB38"></label>
        <label>Serial<input type="text" data-f="serial"></label>
        <label>Purchased<input type="date" data-f="purchase_date"></label>
        <label>Price £<input type="number" step="0.01" min="0" data-f="price" placeholder="0"></label>
        <label>Warranty expiry<input type="date" data-f="warranty_expiry"></label>
        <label>Notes<input type="text" data-f="notes"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-inventory-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="inventory-list">Cancel</button>
      </div>
    </div>`;
}

function renderInventory(items) {
  const el = document.getElementById('inventory-list');
  if (!el) return;
  el.innerHTML = (items && items.length)
    ? items.map((it) => `<div class="maintenance-row" data-inv-id="${it.id}">${inventoryRowInner(it)}</div>`).join('')
    : '<div class="vault-empty"><p>No items yet</p><p class="hint-small">Add appliances, electronics and valuables to track warranties and keep records for insurance.</p></div>';
}

// --- Home care: Vehicles ----------------------------------------------------
// Own endpoint (/api/vehicles). Mirrors the Home-inventory card exactly: a card
// of .maintenance-row rows with inline add/edit/delete + date-status pills.
// Each vehicle shows FOUR due-date pills (MOT / Tax / Insurance / Service) via
// the shared duePill() helper, plus an optional DVLA reg lookup on both forms.

// Date-status pill for a vehicle renewal. No date → muted; past → red overdue;
// within 30 days → amber "due {date}"; else → green "{date}". Colours are all
// semantic vars via the .due-pill.* classes so it reads correctly in dark mode.
function duePill(label, dateStr) {
  const safe = esc(label);
  if (!dateStr) return `<span class="due-pill none">${safe} —</span>`;
  const [y, m, d] = dateStr.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return `<span class="due-pill none">${safe} —</span>`;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(y, m - 1, d);
  const days = Math.round((due - today) / 86400000);
  if (days < 0) return `<span class="due-pill overdue">${safe} overdue</span>`;
  if (days <= 30) return `<span class="due-pill soon">${safe} due ${fmtShortDate(dateStr)}</span>`;
  return `<span class="due-pill ok">${safe} ${fmtShortDate(dateStr)}</span>`;
}

async function loadVehicles() {
  const list = document.getElementById('vehicles-list');
  if (!list) return;
  try {
    const data = await api('/vehicles');
    store.vehicles = data.vehicles || [];
    renderVehicles(store.vehicles);
  } catch {
    list.innerHTML = '<div class="vault-empty"><p>Couldn\'t load vehicles.</p></div>';
  }
}

function findVehicle(id) {
  return (store.vehicles || []).find((v) => String(v.id) === String(id));
}

// Build a create/update payload from the inline row's fields (shared by add + edit).
function vehiclePayload(f) {
  return {
    name: (f.name || '').trim(),
    reg: (f.reg || '').trim() || null,
    make: (f.make || '').trim() || null,
    model: (f.model || '').trim() || null,
    mot_due: f.mot_due || null,
    tax_due: f.tax_due || null,
    insurance_due: f.insurance_due || null,
    service_due: f.service_due || null,
    notes: (f.notes || '').trim() || null,
  };
}

function vehicleRowInner(v) {
  const mm = [v.make, v.model].filter(Boolean).join(' ');
  return `
        <div class="inventory-main">
          <div class="inventory-title">${esc(v.name)}${v.reg ? `<span class="veh-reg">${esc(v.reg)}</span>` : ''}</div>
          ${mm ? `<div class="subscription-meta"><span>${esc(mm)}</span></div>` : ''}
          <div class="veh-pills">
            ${duePill('MOT', v.mot_due)}
            ${duePill('Tax', v.tax_due)}
            ${duePill('Insurance', v.insurance_due)}
            ${duePill('Service', v.service_due)}
          </div>
          ${v.notes ? `<p class="hint-small">${esc(v.notes)}</p>` : ''}
        </div>
        <div class="inventory-side">
          <button class="bill-edit-btn wf-action" data-action="edit-vehicle" data-veh-id="${v.id}" title="Edit vehicle" aria-label="Edit vehicle">✎</button>
        </div>`;
}

// Shared field markup for the inline add + edit forms. Both use a .row-edit root
// so the reg-lookup handler can find its fields the same way for either form.
function vehicleFields(v) {
  return `
      <div class="row-edit-fields">
        <label>Reg<input type="text" data-f="reg" value="${esc(v.reg || '')}" placeholder="e.g. AB12 CDE"></label>
        <label>Make<input type="text" data-f="make" value="${esc(v.make || '')}" placeholder="e.g. Volkswagen"></label>
        <label>Model<input type="text" data-f="model" value="${esc(v.model || '')}" placeholder="e.g. Golf"></label>
        <label>MOT due<input type="date" data-f="mot_due" value="${esc((v.mot_due || '').slice(0, 10))}"></label>
        <label>Tax due<input type="date" data-f="tax_due" value="${esc((v.tax_due || '').slice(0, 10))}"></label>
        <label>Insurance due<input type="date" data-f="insurance_due" value="${esc((v.insurance_due || '').slice(0, 10))}"></label>
        <label>Service due<input type="date" data-f="service_due" value="${esc((v.service_due || '').slice(0, 10))}"></label>
        <label>Notes<input type="text" data-f="notes" value="${esc(v.notes || '')}"></label>
      </div>`;
}

function vehicleEditInner(v) {
  return `
    <div class="row-edit" data-veh-id="${v.id}">
      <input type="text" class="te-input" data-f="name" value="${esc(v.name)}" placeholder="Name (e.g. Laura's Golf)">
      ${vehicleFields(v)}
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-vehicle-inline" data-veh-id="${v.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-vehicle-inline" data-veh-id="${v.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="lookup-vehicle">Look up from reg ↺</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-vehicle" data-veh-id="${v.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function vehicleAddInner() {
  return `
    <div class="row-edit" id="vehicle-add-form">
      <input type="text" class="te-input" data-f="name" placeholder="Name (e.g. Laura's Golf)">
      ${vehicleFields({})}
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-vehicle-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="vehicles-list">Cancel</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="lookup-vehicle">Look up from reg ↺</button>
      </div>
    </div>`;
}

function renderVehicles(items) {
  const el = document.getElementById('vehicles-list');
  if (!el) return;
  el.innerHTML = (items && items.length)
    ? items.map((v) => `<div class="maintenance-row" data-veh-id="${v.id}">${vehicleRowInner(v)}</div>`).join('')
    : '<div class="vault-empty"><p>No vehicles yet</p><p class="hint-small">Add your cars to track MOT, tax, insurance and servicing (and get a reminder before each is due).</p></div>';
}

function renderAppointments(data, filter = 'all', category = 'all') {
  const { users, appointments } = data;
  let filtered = appointments.filter((a) => filter === 'all' || a.status === filter);
  if (category !== 'all') filtered = filtered.filter((a) => a.category === category);

  const cats = [...new Set(appointments.map((a) => a.category))];
  document.getElementById('appt-categories').innerHTML =
    `<button class="cat-btn active wf-action" data-appt-cat="all">All</button>` +
    cats.map((c) => `<button class="cat-btn wf-action" data-appt-cat="${esc(c)}">${esc(c)}</button>`).join('');

  document.getElementById('appointments-body').innerHTML = filtered
    .map(
      (a) => `
    <tr>
      <td>${fmt.datetime(a.datetime)}</td>
      <td><strong>${esc(a.title)}</strong><br><span style="font-size:0.75rem;color:var(--text-muted)">Reminder ${a.reminder_days}d before</span></td>
      <td>${esc(a.provider)}</td>
      <td>${esc(a.location || '—')}</td>
      <td><span class="member-dot" style="background:${userColour(users, a.user_id)};display:inline-block;vertical-align:middle;margin-right:6px"></span>${userName(users, a.user_id)}</td>
      <td><span class="cat-pill ${esc(a.category)}">${esc(a.category)}</span></td>
      <td><span class="status-tag ${esc(a.status)}">${esc(a.status)}</span></td>
      <td>
        <button class="btn btn-sm btn-ghost wf-action" data-action="edit-appointment" data-appt-id="${a.id}">Edit</button>
      </td>
    </tr>`
    )
    .join('') || '<tr><td colspan="8" class="hint-small">No appointments here yet — tap New appointment to add one.</td></tr>';
}

function renderHolidays(data, filter = tripFilter) {
  const { trips, ideas } = data;
  const shownTrips = filter === 'all' ? trips : trips.filter((t) => t.status === filter);

  document.getElementById('holiday-trips').innerHTML = shownTrips.length
    ? shownTrips
    .map((t) => {
      const checklist = (t.checklist || [])
        .map((c) => `<li class="wf-action${c.done ? ' done' : ''}" data-action="toggle-checklist" data-trip-id="${t.id}" data-item-id="${esc(c.id ?? c.label)}" style="cursor:pointer" title="Tap to toggle"><span class="checklist-box">${c.done ? '✓' : ''}</span>${esc(c.label)}</li>`)
        .join('');
      const budgetPct = t.budget ? Math.round((t.spent / t.budget) * 100) : 0;
      return `
      <article class="holiday-card">
        <div class="holiday-card-header">
          <span class="status-tag ${esc(t.status)}">${esc(t.status)}</span>
          <h3>${esc(t.title)}</h3>
          ${t.start ? `<p style="font-size:0.8125rem;opacity:0.85;margin-top:4px">${fmt.date(t.start)} → ${fmt.date(t.end)}</p>` : '<p style="font-size:0.8125rem;opacity:0.85;margin-top:4px">Dates TBC</p>'}
        </div>
        <div class="holiday-card-body">
          ${t.days_until != null ? `<div class="holiday-countdown">${t.days_until} days</div>` : ''}
          <p style="font-size:0.875rem;color:var(--text-muted);margin-top:8px">Budget: ${fmt.gbp(t.spent)} / ${fmt.gbp(t.budget)}</p>
          <div class="progress-bar"><div class="progress-fill" style="width:${Math.min(budgetPct, 100)}%"></div></div>
          ${checklist ? `<ul class="checklist">${checklist}</ul>` : ''}
          ${(t.packing || []).length ? `<p style="font-size:0.75rem;color:var(--text-muted);margin-top:8px">📦 ${t.packing.filter((p) => !p.done).length} packing items left</p>` : ''}
          ${t.media_count ? `<p style="font-size:0.75rem;color:var(--text-muted)">📷 ${t.media_count} photos</p>` : ''}
          <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
            <button class="btn btn-sm btn-primary wf-action" data-action="view-trip" data-trip-id="${t.id}">Details</button>
            <button class="btn btn-sm btn-soft wf-action" data-action="toggle-itinerary" data-trip-id="${t.id}" id="itin-toggle-${t.id}">🗓️ Itinerary</button>
            <button class="btn btn-sm btn-soft wf-action" data-action="add-packing" data-trip-id="${t.id}">Packing</button>
            <button class="btn btn-sm btn-soft wf-action" data-tab-link="media" data-media-trip="${t.id}">Photos</button>
            <button class="btn btn-sm btn-outline wf-action" data-action="edit-trip" data-trip-id="${t.id}">Edit</button>
          </div>
          <div class="itinerary-wrap" id="itin-wrap-${t.id}" hidden>
            <div class="itinerary-body" id="itin-body-${t.id}"></div>
          </div>
        </div>
      </article>`;
    })
    .join('')
    : '<div class="vault-empty"><p>No trips in this filter.</p></div>';

  document.getElementById('holiday-ideas').innerHTML = ideas
    .map(
      (i) => `
    <article class="idea-card">
      <div class="idea-tags">${(i.tags || []).map((t) => `<span class="idea-tag">${esc(t)}</span>`).join('')}</div>
      <h4>${esc(i.destination)}</h4>
      <p>${esc(i.summary)}</p>
      <p style="font-size:0.8125rem;color:var(--text-muted);margin-bottom:12px">Est. ${fmt.gbp(i.budget_estimate)}</p>
      <div style="display:flex;gap:8px">
        <button class="btn btn-sm ${i.saved ? 'btn-secondary' : 'btn-primary'} wf-action" data-action="save-idea" data-idea-id="${i.id}">${i.saved ? 'Saved ✓' : 'Save'}</button>
        <button class="btn btn-sm btn-soft wf-action" data-action="new-trip" data-modal="new-trip">Plan trip</button>
      </div>
    </article>`
    )
    .join('') || '<p class="hint-small">No ideas yet — describe a trip in the AI box above to generate some.</p>';
}

// --- Per-trip day-by-day itinerary (Holidays tab) ---
// Items come from GET /api/itinerary?trip_id= (already ordered: dated+timed
// first, undated last). We cache them per trip on store.itineraries so an
// add/edit/delete only reloads that one trip's timeline, not the whole tab.
const ITINERARY_KINDS = [
  ['flight', '✈️ Flight'],
  ['hotel', '🏨 Hotel'],
  ['activity', '🎡 Activity'],
  ['food', '🍽️ Food'],
  ['transport', '🚗 Transport'],
  ['other', '📋 Other'],
];
const ITINERARY_EMOJI = { flight: '✈️', hotel: '🏨', activity: '🎡', food: '🍽️', transport: '🚗', other: '📋' };

function findItin(tripId, id) {
  return (store.itineraries?.[tripId] || []).find((x) => String(x.id) === String(id));
}

function itinKindSelect(selected) {
  return ITINERARY_KINDS.map(([v, l]) => `<option value="${v}"${v === selected ? ' selected' : ''}>${l}</option>`).join('');
}

// Group items by day_date, preserving the backend's order. Dated groups get a
// numbered "Day N — <date>" header; anything without a date collects under a
// single trailing "Any time / unscheduled" group.
function groupItinerary(items) {
  const map = new Map();
  items.forEach((it) => {
    const key = it.day_date ? String(it.day_date).slice(0, 10) : '';
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(it);
  });
  const groups = [];
  let dayNum = 0;
  for (const [key, its] of map) {
    if (key) {
      dayNum += 1;
      groups.push({ label: `Day ${dayNum} — ${fmtShortDate(key, true)}`, items: its });
    } else {
      groups.push({ label: 'Any time / unscheduled', items: its });
    }
  }
  return groups;
}

function itinRowInner(it) {
  const emoji = ITINERARY_EMOJI[it.kind] || ITINERARY_EMOJI.other;
  const time = it.start_time ? `<span class="itin-time">${esc(String(it.start_time).slice(0, 5))}</span>` : '';
  const loc = it.location ? `<span class="itin-loc">${esc(it.location)}</span>` : '';
  const notes = it.notes ? `<div class="itin-notes">${esc(it.notes)}</div>` : '';
  return `
    <div class="itin-main">
      <span class="itin-emoji">${emoji}</span>
      <div class="itin-detail">
        <div class="itin-line">${time}<span class="itin-title">${esc(it.title)}</span>${loc}</div>
        ${notes}
      </div>
      <button class="bill-edit-btn wf-action" data-action="edit-itinerary" data-trip-id="${esc(it.trip_id)}" data-itin-id="${esc(it.id)}" title="Edit item" aria-label="Edit itinerary item">✎</button>
    </div>`;
}

// Shared field markup for the inline add + edit forms (both use .row-edit).
function itinFieldsInner(it = {}) {
  return `
    <input type="text" class="te-input" data-f="title" value="${esc(it.title || '')}" placeholder="e.g. Flight to Barcelona">
    <div class="row-edit-fields">
      <label>Type<select data-f="kind">${itinKindSelect(it.kind || 'activity')}</select></label>
      <label>Day<input type="date" data-f="day_date" value="${esc((it.day_date || '').slice(0, 10))}"></label>
      <label>Time<input type="time" data-f="start_time" value="${esc((it.start_time || '').slice(0, 5))}"></label>
      <label>Location<input type="text" data-f="location" value="${esc(it.location || '')}" placeholder="Optional"></label>
      <label class="row-edit-full">Notes<input type="text" data-f="notes" value="${esc(it.notes || '')}" placeholder="Optional"></label>
    </div>`;
}

function itinEditInner(it) {
  return `
    <div class="row-edit" data-itin-id="${esc(it.id)}">
      ${itinFieldsInner(it)}
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-itinerary-inline" data-trip-id="${esc(it.trip_id)}" data-itin-id="${esc(it.id)}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-itinerary-inline" data-trip-id="${esc(it.trip_id)}" data-itin-id="${esc(it.id)}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-itinerary" data-trip-id="${esc(it.trip_id)}" data-itin-id="${esc(it.id)}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function itinAddInner(tripId) {
  return `
    <div class="row-edit itin-add-form" data-trip-id="${esc(tripId)}">
      ${itinFieldsInner()}
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-itinerary-new" data-trip-id="${esc(tripId)}">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-itinerary-add">Cancel</button>
      </div>
    </div>`;
}

// Paint the cached itinerary for one trip into its expanded body. Also keeps
// the toggle label in sync with the item count.
function renderItinerary(tripId) {
  const body = document.getElementById(`itin-body-${tripId}`);
  if (!body) return;
  const items = store.itineraries?.[tripId] || [];
  const groupsHtml = groupItinerary(items)
    .map((g) => `
      <div class="itin-day">
        <div class="itin-day-head">${esc(g.label)}</div>
        <div class="itin-rows">
          ${g.items.map((it) => `<div class="itin-row" data-itin-id="${esc(it.id)}">${itinRowInner(it)}</div>`).join('')}
        </div>
      </div>`)
    .join('');
  body.innerHTML = `
    <div class="itin-head">
      <button type="button" class="btn btn-sm btn-soft wf-action" data-action="add-itinerary" data-trip-id="${esc(tripId)}">+ Add itinerary item</button>
      <button type="button" class="btn btn-sm btn-soft wf-action" data-action="scan-trip-email" data-trip-id="${esc(tripId)}">✨ Build from email</button>
    </div>
    <div class="itin-scan-slot"></div>
    ${items.length ? groupsHtml : '<p class="hint-small itin-empty">No plans yet — add flights, hotels and activities to build your day-by-day itinerary.</p>'}
    <div class="itin-add-slot"></div>`;
  const toggle = document.getElementById(`itin-toggle-${tripId}`);
  if (toggle) toggle.textContent = `🗓️ Itinerary (${items.length})`;
}

async function loadItinerary(tripId) {
  const body = document.getElementById(`itin-body-${tripId}`);
  const wrap = document.getElementById(`itin-wrap-${tripId}`);
  if (body && !body.innerHTML) body.innerHTML = '<p class="hint-small">Loading itinerary…</p>';
  try {
    const data = await api(`/itinerary?trip_id=${encodeURIComponent(tripId)}`);
    if (!store.itineraries) store.itineraries = {};
    store.itineraries[tripId] = data.items || [];
    if (wrap) wrap.dataset.loaded = '1';
    renderItinerary(tripId);
  } catch (err) {
    if (body) body.innerHTML = '<p class="hint-small">Couldn\'t load itinerary.</p>';
    showToast(err.message, true);
  }
}

// --- "Build from email": scan a trip's inbox for bookings, review, import ---
// POST /api/trips/{id}/scan-email returns { candidates, scanned, needs_reconnect }.
// Candidates are cached per-trip so a checked box can resolve back to the full
// candidate object (all fields) when we POST the selection to itinerary/import.
const TRIP_SCAN_EMOJI = { flight: '✈️', hotel: '🏨', activity: '🎡', food: '🍽️', transport: '🚗', other: '📋' };

function tripScanSlot(tripId) {
  return document.getElementById(`itin-body-${tripId}`)?.querySelector('.itin-scan-slot');
}

async function scanTripEmail(tripId, btn) {
  const slot = tripScanSlot(tripId);
  if (!slot) return;
  slot.innerHTML = '<div class="itin-scan-box"><p class="hint-small">✨ Scanning your inbox…</p></div>';
  if (btn) btn.disabled = true;
  try {
    const res = await api(`/trips/${encodeURIComponent(tripId)}/scan-email`, { method: 'POST' });
    renderTripScanReview(tripId, res);
  } catch (err) {
    slot.innerHTML = '';
    showToast(err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderTripScanReview(tripId, res) {
  const slot = tripScanSlot(tripId);
  if (!slot) return;
  const cands = res.candidates || [];
  if (!store.tripScanCands) store.tripScanCands = {};
  store.tripScanCands[tripId] = cands;
  const reconnect = (res.needs_reconnect || []).length
    ? '<p class="hint-small itin-scan-note">Reconnect Gmail in Settings to scan every inbox.</p>'
    : '';
  if (!cands.length) {
    const emptyMsg = res.no_account
      ? 'Connect your Gmail in Settings to build itineraries from your travel emails.'
      : 'No travel bookings found in your email for this trip.';
    slot.innerHTML = `
      <div class="itin-scan-box">
        ${reconnect}
        <p class="hint-small">${emptyMsg}</p>
        <div class="row-edit-actions">
          <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-trip-scan" data-trip-id="${esc(tripId)}">Close</button>
        </div>
      </div>`;
    return;
  }
  const rows = cands.map((c, i) => {
    const emoji = TRIP_SCAN_EMOJI[c.kind] || TRIP_SCAN_EMOJI.other;
    const meta = [fmtShortDate(c.day_date), c.start_time ? String(c.start_time).slice(0, 5) : '', c.location || '']
      .filter(Boolean).map((s) => esc(s)).join(' · ');
    return `
      <label class="mem-cand">
        <input type="checkbox" class="mem-cand-cb scan-cand-cb" data-idx="${i}" checked>
        <span class="itin-emoji">${emoji}</span>
        <span class="mem-cand-body">
          <span class="mem-cand-text">${esc(c.title || 'Untitled')}</span>
          <span class="mem-cand-meta">${meta || '—'}</span>
        </span>
      </label>`;
  }).join('');
  slot.innerHTML = `
    <div class="itin-scan-box">
      ${reconnect}
      <div class="itin-scan-head">Found ${cands.length} · scanned ${esc(String(res.scanned ?? 0))} emails</div>
      <div class="scan-cand-list">${rows}</div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="import-scanned-itinerary" data-trip-id="${esc(tripId)}">Add ${cands.length} to itinerary</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-trip-scan" data-trip-id="${esc(tripId)}">Cancel</button>
      </div>
    </div>`;
  // Keep the "Add N" button label in step with the checked count.
  slot.querySelector('.scan-cand-list')?.addEventListener('change', () => {
    const n = slot.querySelectorAll('.scan-cand-cb:checked').length;
    const b = slot.querySelector('[data-action="import-scanned-itinerary"]');
    if (b) b.textContent = `Add ${n} to itinerary`;
  });
}

// --- "Find trips in my email": propose whole trips from booking emails ---
// GET /api/trips/detect-email returns { proposals: [{title,destination,start_date,end_date,summary}] }.
async function findTripsInEmail(btn) {
  const wrap = document.getElementById('trip-proposals');
  if (!wrap) return;
  wrap.hidden = false;
  wrap.innerHTML = '<p class="hint-small">✨ Scanning your inbox for trips…</p>';
  if (btn) btn.disabled = true;
  try {
    const res = await api('/trips/detect-email');
    renderTripProposals(res.proposals || []);
  } catch (err) {
    wrap.innerHTML = '<p class="hint-small">Couldn\'t scan your email for trips.</p>';
    showToast(err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderTripProposals(proposals) {
  const wrap = document.getElementById('trip-proposals');
  if (!wrap) return;
  if (!proposals.length) {
    wrap.innerHTML = '<p class="hint-small">No new trips found in your email.</p>';
    return;
  }
  store.tripProposals = {};
  wrap.innerHTML = proposals.map((p, i) => {
    store.tripProposals[i] = p;
    const dates = [fmtShortDate(p.start_date, true), fmtShortDate(p.end_date, true)].filter(Boolean).join(' → ');
    return `
      <article class="idea-card">
        <div class="idea-tags"><span class="idea-tag">✨ From email</span></div>
        <h4>${esc(p.title || p.destination || 'Trip')}</h4>
        ${p.destination ? `<p style="font-size:0.875rem;color:var(--text-muted)">${esc(p.destination)}</p>` : ''}
        ${dates ? `<p style="font-size:0.8125rem;color:var(--text-muted);margin-top:4px">${esc(dates)}</p>` : ''}
        ${p.summary ? `<p style="font-size:0.875rem;margin-top:8px">${esc(p.summary)}</p>` : ''}
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="btn btn-sm btn-primary wf-action" data-action="create-trip-from-proposal" data-proposal-idx="${i}">Create trip</button>
        </div>
      </article>`;
  }).join('');
}

function docStatusLabel(status) {
  if (status === 'renew_soon') return 'Renew soon';
  if (status === 'expired') return 'Expired';
  return 'OK';
}

function docStatusClass(status) {
  if (status === 'renew_soon') return 'planning';
  if (status === 'expired') return 'cancelled';
  return 'booked';
}

// Resolve a document's expiry from either the new (expiry_date) or legacy (expiry) field.
function docExpiryValue(d) {
  return d.expiry_date || d.expiry || '';
}

// Small client-side badge: amber when a document expires within ~30 days, red once it's past.
function expiryBadge(dateStr) {
  if (!dateStr) return '';
  const target = new Date(dateStr);
  if (isNaN(target.getTime())) return '';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  const diff = Math.round((day - today) / 86400000);
  if (diff < 0) return '<span class="expiry-badge expired">Expired</span>';
  if (diff <= 30) return '<span class="expiry-badge soon">Expires soon</span>';
  return '';
}

function renderDocuments(data, filter = vaultFilter) {
  const { documents = [], categories = [] } = data;
  const filtered =
    filter === 'all' ? documents : documents.filter((d) => d.category === filter);
  const renewSoon = documents.filter((d) => d.status === 'renew_soon').length;
  const withFiles = documents.filter((d) => d.has_file).length;

  document.getElementById('vault-stats').innerHTML = `
    <div class="stat"><span>${documents.length}</span><label>Total documents</label></div>
    <div class="stat"><span>${withFiles}</span><label>Files uploaded</label></div>
    <div class="stat"><span>${renewSoon}</span><label>Renew soon</label></div>
    <div class="stat"><span>${documents.filter((d) => d.status === 'expired').length}</span><label>Expired</label></div>`;

  const cats = categories.length
    ? categories
    : Object.entries(DOC_CATEGORY_LABELS).map(([id, label]) => ({ id, label }));

  document.getElementById('vault-filters').innerHTML =
    `<button class="filter-chip-btn wf-action ${filter === 'all' ? 'active' : ''}" data-vault-cat="all">All</button>` +
    cats
      .map(
        (c) =>
          `<button class="filter-chip-btn wf-action ${filter === c.id ? 'active' : ''}" data-vault-cat="${c.id}">${c.label}</button>`
      )
      .join('');

  document.getElementById('vault-grid').innerHTML = filtered.length
    ? filtered
        .map(
          (d) => `
      <article class="vault-card ${d.has_file ? 'has-file' : ''}">
        <div class="vault-card-top">
          <span class="vault-cat-pill">${esc(DOC_CATEGORY_LABELS[d.category] || d.category)}</span>
          <span class="status-tag ${docStatusClass(d.status)}">${docStatusLabel(d.status)}</span>
        </div>
        <h3 class="vault-card-title">${esc(d.name)}</h3>
        ${d.notes ? `<p class="vault-card-notes">${esc(d.notes)}</p>` : ''}
        <div class="vault-card-meta">
          ${docExpiryValue(d) ? `<span>Expires ${fmt.date(docExpiryValue(d))} ${expiryBadge(docExpiryValue(d))}</span>` : '<span>No expiry set</span>'}
          ${d.has_file ? `<span>${fmt.fileSize(d.file_size)}</span>` : '<span class="vault-no-file">No file yet</span>'}
        </div>
        <div class="vault-card-actions">
          ${
            d.has_file
              ? `<a class="btn btn-sm btn-primary" href="${API}/documents/${d.id}/file" target="_blank" rel="noopener">View / download</a>`
              : `<button class="btn btn-sm btn-soft wf-action" data-action="add-document" data-modal="add-document">Add reminder</button>`
          }
          <button class="btn btn-sm btn-ghost wf-action" data-action="delete-document" data-doc-id="${d.id}">Delete</button>
        </div>
      </article>`
        )
        .join('')
    : `<div class="vault-empty"><p>No documents in this category yet.</p><p class="hint-small">Upload your home insurance, passports, MOT or other files above.</p></div>`;
}

// Human-readable byte size for the storage meter: 12 KB / 340 MB / 1.2 GB.
function humanBytes(bytes) {
  const b = Number(bytes);
  if (!isFinite(b) || b <= 0) return '0 B';
  if (b < 1024) return `${Math.round(b)} B`;
  if (b < 1024 * 1024) return `${Math.round(b / 1024)} KB`;
  if (b < 1024 * 1024 * 1024) return `${Math.round(b / (1024 * 1024))} MB`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

// Prominent storage card: media size + count, disk-usage bar, free/total, low warning.
function renderMediaStorage(s) {
  const el = document.getElementById('media-storage');
  if (!el) return;
  if (!s) { el.innerHTML = ''; return; }
  const pct = Math.max(0, Math.min(100, Math.round(
    s.disk_pct_used != null ? s.disk_pct_used : (s.disk_total ? (s.disk_used / s.disk_total) * 100 : 0)
  )));
  const count = s.media_count || 0;
  el.innerHTML = `
    <div class="storage-card${s.low ? ' storage-low' : ''}">
      <div class="storage-head">
        <div class="storage-title">
          <span class="storage-count">${count} ${count === 1 ? 'photo &amp; video' : 'photos &amp; videos'}</span>
          <span class="storage-sub">${humanBytes(s.media_bytes)} of memories</span>
        </div>
        <span class="storage-pct">${pct}%</span>
      </div>
      <div class="storage-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
        <div class="storage-bar-fill" style="width:${pct}%"></div>
      </div>
      <div class="storage-foot">
        <span>${humanBytes(s.disk_free)} free of ${humanBytes(s.disk_total)}</span>
      </div>
      ${s.low ? `<p class="storage-warn">⚠️ Running low on space — free up room or ask to expand storage.</p>` : ''}
    </div>`;
}

// Fetch the storage stats and paint the meter (own endpoint, called from load()).
async function loadMediaStorage() {
  try {
    mediaStorage = await api('/media/storage');
  } catch {
    mediaStorage = null;
  }
  renderMediaStorage(mediaStorage);
}

// Re-fetch gallery + storage and repaint just the Photos tab (after uploads/deletes).
async function refreshMedia() {
  try {
    const [media, storage] = await Promise.all([
      api('/media'),
      api('/media/storage').catch(() => null),
    ]);
    store.media = media;
    renderMedia(media, mediaFilter);
    if (storage) { mediaStorage = storage; renderMediaStorage(storage); }
  } catch (err) {
    console.error('refreshMedia failed', err);
  }
}

function renderMedia(data, filter = mediaFilter) {
  const { items = [], trips = [] } = data;
  const filtered =
    filter === 'all'
      ? items
      : filter === 'none'
      ? items.filter((m) => !m.trip_id)
      : items.filter((m) => String(m.trip_id) === String(filter));

  // Optional trip filter — only shown when trips exist; defaults to All.
  const filtersEl = document.getElementById('media-filters');
  if (filtersEl) {
    filtersEl.innerHTML = trips.length
      ? `<button class="filter-chip-btn wf-action ${filter === 'all' ? 'active' : ''}" data-media-trip="all">All</button>` +
        trips
          .map(
            (t) =>
              `<button class="filter-chip-btn wf-action ${String(filter) === String(t.id) ? 'active' : ''}" data-media-trip="${esc(t.id)}">${esc(t.title)}</button>`
          )
          .join('')
      : '';
  }

  document.getElementById('media-grid').innerHTML = filtered.length
    ? filtered
        .map((m) => {
          const fileUrl = `/api/media/${m.id}/file`;
          const isVideo = m.media_type === 'video';
          const alt = esc(m.title || m.caption || m.file_name || (isVideo ? 'Video' : 'Photo'));
          const capAttr = m.caption ? ` title="${esc(m.caption)}"` : '';
          const media = isVideo
            ? `<video class="media-tile-media" src="${fileUrl}" muted preload="metadata" playsinline></video><span class="media-play" aria-hidden="true">▶</span>`
            : `<img class="media-tile-media" src="${fileUrl}" alt="${alt}" loading="lazy">`;
          const badge = m.source === 'whatsapp' ? `<span class="media-src-badge">via WhatsApp</span>` : '';
          return `
      <div class="media-tile${isVideo ? ' is-video' : ''}" data-media-open="${esc(m.id)}" data-media-type="${isVideo ? 'video' : 'photo'}"${capAttr}>
        ${media}
        ${badge}
        <button type="button" class="media-del wf-action" data-action="delete-media" data-media-id="${esc(m.id)}" title="Delete" aria-label="Delete">&times;</button>
      </div>`;
        })
        .join('')
    : `<div class="vault-empty"><p>No photos yet — tap Upload, or send a photo to the Hub on WhatsApp and it'll appear here.</p></div>`;
}

// --- Frictionless upload: hidden file input → immediate XHR uploads with progress ---

function mediaProgressRow(name, i) {
  return `
    <div class="mup-row" data-mup="${i}">
      <div class="mup-head">
        <span class="mup-name">${esc(name)}</span>
        <span class="mup-status" aria-hidden="true"></span>
      </div>
      <div class="mup-bar"><div class="mup-bar-fill"></div></div>
      <p class="mup-msg"></p>
    </div>`;
}

function setMupState(row, state, msg) {
  if (!row) return;
  row.classList.remove('mup-done', 'mup-error', 'mup-skip');
  const status = row.querySelector('.mup-status');
  const msgEl = row.querySelector('.mup-msg');
  const fill = row.querySelector('.mup-bar-fill');
  if (state === 'done') {
    row.classList.add('mup-done');
    if (status) status.textContent = '✔';
    if (fill) fill.style.width = '100%';
  } else if (state === 'error') {
    row.classList.add('mup-error');
    if (status) status.textContent = '✗';
  } else if (state === 'skip') {
    row.classList.add('mup-skip');
    if (status) status.textContent = '⤼';
  }
  if (msgEl) msgEl.textContent = msg || '';
}

// Upload a single file via XMLHttpRequest so we get real upload progress.
function uploadOneMedia(file, row) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append('file', file);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}/media/upload`);
    xhr.withCredentials = true;
    const fill = row && row.querySelector('.mup-bar-fill');
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && fill) {
        fill.style.width = `${Math.round((ev.loaded / ev.total) * 100)}%`;
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        let item = null;
        try { item = JSON.parse(xhr.responseText); } catch { /* non-JSON ok */ }
        resolve(item);
      } else {
        let msg = 'Upload failed';
        try {
          const j = JSON.parse(xhr.responseText);
          if (Array.isArray(j.detail)) msg = j.detail.map((d) => d.msg).join('; ');
          else if (j.detail) msg = j.detail;
        } catch { /* keep default */ }
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error('Network error — upload failed'));
    xhr.send(fd);
  });
}

const MEDIA_SPACE_MARGIN = 100 * 1024 * 1024; // keep 100 MB headroom on disk

// Orchestrate: pre-flight space check, type guard, then upload with concurrency 2.
async function handleMediaFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;

  const listEl = document.getElementById('media-progress');
  if (listEl) {
    listEl.hidden = false;
    listEl.innerHTML = files.map((f, i) => mediaProgressRow(f.name, i)).join('');
  }
  const rows = files.map((_, i) => listEl && listEl.querySelector(`.mup-row[data-mup="${i}"]`));

  // Latest disk figures for the pre-flight check; track a running projection as we go.
  let storage = null;
  try { storage = await api('/media/storage'); } catch { storage = null; }
  let projectedFree = storage && isFinite(storage.disk_free) ? storage.disk_free : Infinity;

  let next = 0;
  const worker = async () => {
    while (next < files.length) {
      const i = next++;
      const file = files[i];
      const row = rows[i];

      // Client-side type guard — mirror the backend image/* + video/* allow-list.
      // Fall back to the file extension when the browser reports no MIME type
      // (iPhone HEIC and some videos come through with an empty file.type).
      const okType = /^(image|video)\//.test(file.type || '')
        || /\.(jpe?g|png|webp|heic|gif|mp4|mov|webm|m4v)$/i.test(file.name || '');
      if (!okType) {
        setMupState(row, 'skip', 'Not a photo or video — skipped');
        continue;
      }
      // Pre-flight space check against the latest free space (minus safety margin).
      if (isFinite(projectedFree) && file.size > projectedFree - MEDIA_SPACE_MARGIN) {
        setMupState(row, 'error', 'Not enough space — free up room or expand storage');
        continue;
      }
      try {
        await uploadOneMedia(file, row);
        projectedFree -= file.size;
        setMupState(row, 'done', humanBytes(file.size));
        // Repaint just the gallery per file; disk/storage stats refreshed once at the end.
        try { const media = await api('/media'); store.media = media; renderMedia(media, mediaFilter); } catch {}
      } catch (err) {
        setMupState(row, 'error', err.message || 'Upload failed');
      }
    }
  };

  // Small concurrency (2) so a batch uploads briskly without hammering the box.
  await Promise.all([worker(), worker()]);
  // Recompute disk/storage stats ONCE after the whole batch (scandir is O(files),
  // so refreshing per-upload would be O(n²) on a large gallery).
  await loadMediaStorage();
}

// Lightweight lightbox overlay — click a tile to view it large.
function openMediaLightbox(id, type) {
  closeMediaLightbox();
  const fileUrl = `/api/media/${id}/file`;
  const inner = type === 'video'
    ? `<video class="media-lightbox-media" src="${fileUrl}" controls autoplay playsinline></video>`
    : `<img class="media-lightbox-media" src="${fileUrl}" alt="">`;
  const overlay = document.createElement('div');
  overlay.id = 'media-lightbox';
  overlay.className = 'media-lightbox';
  overlay.innerHTML = `
    <button type="button" class="media-lightbox-close" aria-label="Close">&times;</button>
    ${inner}`;
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay || e.target.closest('.media-lightbox-close')) closeMediaLightbox();
  });
  document.addEventListener('keydown', mediaLightboxKey);
  document.body.appendChild(overlay);
}

function mediaLightboxKey(e) {
  if (e.key === 'Escape') closeMediaLightbox();
}

function closeMediaLightbox() {
  document.removeEventListener('keydown', mediaLightboxKey);
  document.getElementById('media-lightbox')?.remove();
}

function subscriptionStatusLabel(status) {
  if (status === 'confirmed') return 'Confirmed';
  if (status === 'ignored') return 'Hidden';
  return 'Detected';
}

function frequencyLabel(freq) {
  return { monthly: 'Monthly', weekly: 'Weekly', yearly: 'Yearly', quarterly: 'Quarterly' }[freq] || freq;
}

// Is this subscription already tracked by (matched/locked to) a bill?
function subscriptionHasBill(subId) {
  return (store.finances?.bills || []).some((b) => String(b.subscription_id || '') === String(subId));
}

// Day-of-month for a new bill, from the sub's expected/last charge date, clamped 1–28.
function billDueDayFromDates(nextDate, lastDate) {
  const src = nextDate || lastDate;
  const day = src ? new Date(src).getDate() : NaN;
  if (!day || isNaN(day)) return 1;
  return Math.min(Math.max(day, 1), 28);
}

function renderSubscriptions(data) {
  const { subscriptions = [], summary = {} } = data;

  document.getElementById('subscription-stats').innerHTML = `
    <div class="stat"><span>${summary.active_count || 0}</span><label>Active subscriptions</label></div>
    <div class="stat"><span>${fmt.gbp(summary.monthly_total || 0)}</span><label>Est. monthly</label></div>
    <div class="stat"><span>${fmt.gbp(summary.yearly_estimate || 0)}</span><label>Est. yearly</label></div>`;

  document.getElementById('subscription-list').innerHTML = subscriptions.length
    ? subscriptions
        .map(
          (s) => `
      <div class="subscription-row">
        <div class="subscription-main">
          <div class="subscription-name">${esc(s.display_name)}</div>
          <div class="subscription-meta">
            <span class="status-tag ${s.status === 'confirmed' ? 'booked' : s.status === 'detected' ? 'planning' : 'idea'}">${subscriptionStatusLabel(s.status)}</span>
            <span>${esc(frequencyLabel(s.frequency))}</span>
            <span>${s.occurrence_count} charges found</span>
            ${s.account ? `<span>${esc(s.account)}</span>` : ''}
          </div>
          ${s.next_expected_date ? `<div class="subscription-next">Next expected: ${fmt.date(s.next_expected_date)}</div>` : ''}
        </div>
        <div class="subscription-amount">${fmt.gbp(s.amount)}</div>
        <div class="subscription-actions">
          ${s.status !== 'confirmed' ? `<button class="btn btn-sm btn-primary wf-action" data-action="confirm-subscription" data-sub-id="${s.id}">Confirm</button>` : ''}
          ${!subscriptionHasBill(s.id) ? `<button class="btn btn-sm btn-soft wf-action" data-action="track-as-bill" data-sub-id="${esc(s.id)}">Track as bill</button>` : ''}
          <button class="btn btn-sm btn-ghost wf-action" data-action="ignore-subscription" data-sub-id="${s.id}">Hide</button>
        </div>
      </div>`
        )
        .join('')
    : `<div class="vault-empty"><p>No recurring subscriptions detected yet.</p><p class="hint-small">Connect your bank and tap <strong>Scan transactions</strong>, or import CSV data on the Finances tab.</p></div>`;
}

function renderBriefing(data) {
  const el = document.getElementById('briefing-card');
  if (!el || !data) return;
  el.innerHTML = `
    <div class="briefing-inner">
      <div>
        <h3>${esc(data.greeting)}, ${esc(data.user_name)}</h3>
        <p>${esc(data.summary_text)}</p>
      </div>
      <div class="briefing-pills">
        ${data.today_events?.length ? `<span>${data.today_events.length} events today</span>` : ''}
        ${data.due_tasks?.length ? `<span>${data.due_tasks.length} tasks due</span>` : ''}
        ${data.urgent_renewals?.length ? `<span>${data.urgent_renewals.length} renewals soon</span>` : ''}
      </div>
    </div>`;
}

function renderActivityFeed(data) {
  const el = document.getElementById('activity-feed');
  if (!el) return;
  const items = data?.items || [];
  el.innerHTML = items.length
    ? items.map((a) => `
      <div class="activity-row">
        <div class="activity-dot"></div>
        <div>
          <div class="activity-summary">${esc(a.summary)}</div>
          <div class="activity-meta">${esc(a.user_name || 'System')} · ${fmt.datetime(a.created_at)} · ${esc(a.entity_type)}</div>
        </div>
      </div>`).join('')
    : '<p class="hint-small">Activity will appear here as you use the portal.</p>';
}

function renderRenewals(data) {
  document.getElementById('renewal-stats').innerHTML = `
    <div class="stat"><span>${data.overdue_count || 0}</span><label>Overdue</label></div>
    <div class="stat"><span>${data.this_month_count || 0}</span><label>Next 30 days</label></div>
    <div class="stat"><span>${data.items?.length || 0}</span><label>Total tracked</label></div>`;
  document.getElementById('renewal-timeline').innerHTML = (data.items || []).length
    ? data.items.map((r) => `
      <div class="renewal-row ${r.days_until < 0 ? 'overdue' : ''}">
        <div class="renewal-date">${fmt.date(r.date)}<small>${r.days_until === 0 ? 'Today' : r.days_until < 0 ? `${Math.abs(r.days_until)}d overdue` : `in ${r.days_until}d`}</small></div>
        <div class="renewal-body">
          <strong>${esc(r.title)}</strong>
          <span class="renewal-type">${esc(r.type)}</span>
          ${r.detail ? `<span class="renewal-detail">${esc(String(r.detail))}</span>` : ''}
        </div>
      </div>`).join('')
    : '<div class="vault-empty"><p>No renewals in the next 90 days.</p></div>';
}

function findMaintenance(id) {
  return (store.maintenance?.items || []).find((m) => String(m.id) === String(id));
}

function maintRowInner(m) {
  return `
        <div>
          <strong>${esc(m.title)}</strong>
          <div class="subscription-meta"><span>${esc(m.category)}</span>${m.vendor ? `<span>${esc(m.vendor)}</span>` : ''}${m.next_due_date ? `<span>Due ${fmt.date(m.next_due_date)}</span>` : ''}</div>
          ${m.notes ? `<p class="hint-small">${esc(m.notes)}</p>` : ''}
        </div>
        <div class="subscription-actions">
          <button class="btn btn-sm btn-primary wf-action" data-action="maintenance-done" data-maint-id="${m.id}">Mark done</button>
          <button class="bill-edit-btn wf-action" data-action="edit-maintenance" data-maint-id="${m.id}" title="Edit item" aria-label="Edit maintenance item">✎</button>
        </div>`;
}

// Inline edit form for a maintenance row — mirrors the bill-row pattern.
function maintEditInner(m) {
  const catOpts = ['heating', 'exterior', 'appliance', 'general']
    .map((c) => `<option value="${c}"${c === m.category ? ' selected' : ''}>${c}</option>`)
    .join('');
  return `
    <div class="row-edit" data-maint-id="${m.id}">
      <input type="text" class="te-input" data-f="title" value="${esc(m.title)}" placeholder="Title">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${catOpts}</select></label>
        <label>Next due<input type="date" data-f="next_due_date" value="${esc((m.next_due_date || '').slice(0, 10))}"></label>
        <label>Interval (months)<input type="number" min="0" data-f="interval_months" value="${m.interval_months ?? 12}"></label>
        <label>Vendor<input type="text" data-f="vendor" value="${esc(m.vendor || '')}"></label>
        <label>Notes<input type="text" data-f="notes" value="${esc(m.notes || '')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-maintenance-inline" data-maint-id="${m.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-maintenance-inline" data-maint-id="${m.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-maintenance-inline" data-maint-id="${m.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function renderMaintenance(data) {
  const items = data?.items || [];
  document.getElementById('maintenance-list').innerHTML = items.length
    ? items.map((m) => `<div class="maintenance-row" data-maint-id="${m.id}">${maintRowInner(m)}</div>`).join('')
    : '<div class="vault-empty"><p>No maintenance items yet.</p></div>';
}

function findTradesperson(id) {
  return (store.tradespeople?.tradespeople || []).find((t) => String(t.id) === String(id));
}

function tradespersonRowInner(t) {
  const telHref = (t.phone || '').replace(/[^\d+]/g, '');
  const meta = [];
  if (t.trade) meta.push(`<span>${esc(t.trade)}</span>`);
  if (t.phone) meta.push(`<a href="tel:${esc(telHref)}" class="trade-link">📞 ${esc(t.phone)}</a>`);
  if (t.email) meta.push(`<a href="mailto:${esc(t.email)}" class="trade-link">✉️ ${esc(t.email)}</a>`);
  return `
        <div>
          <strong>${esc(t.name)}</strong>
          <div class="subscription-meta">${meta.join('') || '<span class="hint-small">No contact details yet</span>'}</div>
          ${t.notes ? `<p class="hint-small">${esc(t.notes)}</p>` : ''}
        </div>
        <div class="subscription-actions">
          <button class="bill-edit-btn wf-action" data-action="edit-tradesperson" data-trade-id="${t.id}" title="Edit contact" aria-label="Edit contact">✎</button>
        </div>`;
}

// Inline edit form for a tradesperson row — mirrors the maintenance-row pattern.
function tradespersonEditInner(t) {
  return `
    <div class="row-edit" data-trade-id="${t.id}">
      <input type="text" class="te-input" data-f="name" value="${esc(t.name)}" placeholder="Name">
      <div class="row-edit-fields">
        <label>Trade<input type="text" data-f="trade" value="${esc(t.trade || '')}" placeholder="e.g. Plumber"></label>
        <label>Phone<input type="tel" data-f="phone" value="${esc(t.phone || '')}" placeholder="07700 900123"></label>
        <label>Email<input type="email" data-f="email" value="${esc(t.email || '')}" placeholder="name@example.com"></label>
        <label>Notes<input type="text" data-f="notes" value="${esc(t.notes || '')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-tradesperson-inline" data-trade-id="${t.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-tradesperson-inline" data-trade-id="${t.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-tradesperson" data-trade-id="${t.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function tradespersonAddInner() {
  return `
    <div class="row-edit" id="tradesperson-add-form">
      <input type="text" class="te-input" data-f="name" placeholder="Name (e.g. Dave the plumber)">
      <div class="row-edit-fields">
        <label>Trade<input type="text" data-f="trade" placeholder="e.g. Plumber"></label>
        <label>Phone<input type="tel" data-f="phone" placeholder="07700 900123"></label>
        <label>Email<input type="email" data-f="email" placeholder="name@example.com"></label>
        <label>Notes<input type="text" data-f="notes" placeholder="Fitted the boiler in 2024"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-tradesperson-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="tradespeople-list">Cancel</button>
      </div>
    </div>`;
}

function renderTradespeople(data) {
  const list = document.getElementById('tradespeople-list');
  if (!list) return;
  const items = data?.tradespeople || [];
  list.innerHTML = items.length
    ? items.map((t) => `<div class="maintenance-row" data-trade-id="${t.id}">${tradespersonRowInner(t)}</div>`).join('')
    : '<div class="vault-empty"><p>No tradespeople saved yet.</p><p class="hint-small">Add plumbers, electricians and other trusted contacts — tap a number to call.</p></div>';
}

function renderMergedRecurring(data) {
  const el = document.getElementById('merged-recurring');
  if (!el || !data) return;
  const items = data.items || [];
  el.innerHTML = items.length
    ? items.map((x) => `
      <div class="subscription-row">
        <div class="subscription-main">
          <div class="subscription-name">${esc(x.name)} ${x.matched ? '<span class="media-trip-pill">Matched</span>' : ''}</div>
          <div class="subscription-meta"><span>${esc(x.source)}</span><span>${esc(x.frequency || 'monthly')}</span>${x.amount_note ? `<span>${esc(x.amount_note)}</span>` : ''}</div>
        </div>
        <div class="subscription-amount">${fmt.gbp(x.amount)}</div>
        ${x.source === 'subscription' && !x.matched && !x.bill_id
          ? `<div class="subscription-actions"><button class="btn btn-sm btn-soft wf-action" data-action="track-as-bill" data-sub-id="${esc(x.subscription_id)}">Track as bill</button></div>`
          : ''}
      </div>`).join('')
    : '<p class="hint-small">No recurring items yet.</p>';
}

// Choose one of the backend packing templates (server/services/trips.py PACKING_TEMPLATES).
function openPackingTemplateModal(tripId) {
  const templates = [
    { id: 'default', label: 'Essentials', desc: 'Passports, chargers, toiletries, meds' },
    { id: 'beach', label: 'Beach', desc: 'Swimwear, sun cream, towels, flip flops' },
    { id: 'city', label: 'City break', desc: 'Walking shoes, day bag, maps, charger' },
    { id: 'weekend', label: 'Weekend', desc: 'Overnight bag, change of clothes, snacks' },
  ];
  const tiles = templates
    .map(
      (t) => `
      <button type="button" class="bank-provider-tile wf-action" data-action="add-packing" data-trip-id="${tripId}" data-template="${t.id}">
        <strong>${t.label}</strong>
        <span>${t.desc}</span>
      </button>`
    )
    .join('');
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Add packing list</h3><p>Pick a starter template — items appear on the trip card.</p></div>
      <div class="wf-modal-body"><div class="bank-provider-grid">${tiles}</div></div>
      <div class="wf-modal-footer"><button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button></div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
}

async function openTripDetailModal(tripId) {
  try {
    const trip = await api(`/holidays/trips/${tripId}`);
    const timeline = (trip.timeline || []).map((day) => `
      <div class="timeline-day">
        <strong>${esc(day.label)}</strong>
        ${day.media?.length ? day.media.map((m) => `<span class="media-trip-pill">${esc(m.title)}</span>`).join(' ') : '<span class="hint-small">No media</span>'}
      </div>`).join('');
    const packing = (trip.packing || [])
      .map((p) => `<li class="wf-action${p.done ? ' done' : ''}" data-action="toggle-checklist" data-trip-id="${tripId}" data-item-type="packing" data-item-id="${esc(p.id ?? p.label)}" style="cursor:pointer" title="Tap to toggle"><span class="checklist-box">${p.done ? '✓' : ''}</span>${esc(p.label)}</li>`)
      .join('');
    const docs = (trip.linked_documents || [])
      .map((d) => `<li style="display:flex;align-items:center;justify-content:space-between;gap:8px"><span>${esc(d.name)} (${esc(d.category)})</span><button type="button" class="btn btn-sm btn-ghost wf-action" data-action="unlink-trip-doc" data-trip-id="${tripId}" data-doc-id="${d.id}">Unlink</button></li>`)
      .join('');
    const linkedIds = new Set((trip.linked_documents || []).map((d) => String(d.id)));
    const docOptions = (store.documents?.documents || [])
      .filter((d) => !linkedIds.has(String(d.id)))
      .map((d) => `<option value="${d.id}">${esc(d.name)}</option>`)
      .join('');
    document.getElementById('modal-root').innerHTML = `
      <div class="modal-backdrop" id="modal-backdrop"></div>
      <div class="wf-modal wf-modal-wide" role="dialog">
        <div class="wf-modal-header"><h3>${esc(trip.title)}</h3><p>Trip timeline, packing &amp; travel documents</p></div>
        <div class="wf-modal-body">
          <h4>Timeline</h4>${timeline || '<p class="hint-small">Add dates and photos to build a timeline.</p>'}
          <h4 style="margin-top:16px">Packing</h4><ul class="checklist">${packing || '<li>Add a packing list from the trip card</li>'}</ul>
          <h4 style="margin-top:16px">Travel documents</h4><ul>${docs || '<li>No documents linked yet</li>'}</ul>
          ${docOptions ? `
          <div class="trip-doc-link" style="margin-top:12px;display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
            <label class="field" style="flex:1;min-width:180px"><span>Link from vault</span>
              <select id="trip-doc-select">${docOptions}</select>
            </label>
            <button type="button" class="btn btn-sm btn-primary wf-action" data-action="link-trip-doc" data-trip-id="${tripId}">Link</button>
          </div>` : ''}
        </div>
        <div class="wf-modal-footer"><button class="btn btn-secondary wf-action" data-action="close-modal">Close</button></div>
      </div>`;
    document.getElementById('modal-backdrop').onclick = closeModal;
  } catch (err) {
    showToast(err.message, true);
  }
}

const MEMORY_CATS = {
  people: { label: 'People & family', icon: '👪' },
  places: { label: 'Places', icon: '📍' },
  preferences: { label: 'Likes & preferences', icon: '⭐' },
  possessions: { label: 'Home, cars & things', icon: '🚗' },
};
const MEMORY_CAT_ORDER = ['people', 'places', 'preferences', 'possessions'];
let memorySearchWired = false;

function findMemory(id) {
  return (store.memory?.facts || []).find((f) => String(f.id) === String(id));
}

function memorySubjectName(subject) {
  if (!subject || subject === 'family') return 'Family';
  const u = (store.dashboard?.users || store.memory?.subjects || []).find((x) => x.id === subject);
  return u ? (u.name || subject) : subject;
}

function memorySubjectOptions(selected) {
  const subs = store.memory?.subjects || [{ id: 'family', name: 'Family' }];
  return subs.map((s) => `<option value="${esc(s.id)}"${s.id === selected ? ' selected' : ''}>${esc(s.name)}</option>`).join('');
}

function memoryCatOptions(selected) {
  return MEMORY_CAT_ORDER.map((c) => `<option value="${c}"${c === selected ? ' selected' : ''}>${MEMORY_CATS[c].label}</option>`).join('');
}

function memoryFactInner(f) {
  const src = f.source === 'auto'
    ? '<span class="mem-badge auto" title="Learned from a conversation">✨ auto</span>'
    : '<span class="mem-badge manual" title="You added this">✍ added</span>';
  const pin = f.pinned
    ? '<span class="mem-badge pinned" title="Pinned — always considered">📌 pinned</span>'
    : '';
  return `
    <div class="mem-fact-main">
      <span class="mem-fact-text">${esc(f.text)}</span>
      <div class="mem-fact-meta"><span class="mem-subject">${esc(memorySubjectName(f.subject))}</span>${src}${pin}</div>
    </div>
    <div class="mem-fact-actions">
      <button type="button" class="bill-edit-btn wf-action" data-action="toggle-pin-memory" data-mem-id="${f.id}" title="${f.pinned ? 'Unpin' : 'Pin — always consider this'}">${f.pinned ? '📌' : '📎'}</button>
      <button type="button" class="bill-edit-btn wf-action" data-action="edit-memory" data-mem-id="${f.id}" title="Edit">✎</button>
      <button type="button" class="bill-edit-btn wf-action" data-action="delete-memory" data-mem-id="${f.id}" title="Forget">🗑</button>
    </div>`;
}

function memoryEditInner(f) {
  return `
    <div class="row-edit" data-mem-id="${f.id}">
      <input type="text" class="te-input" data-f="text" value="${esc(f.text)}">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${memoryCatOptions(f.category)}</select></label>
        <label>About<select data-f="subject">${memorySubjectOptions(f.subject)}</select></label>
        <label class="row-edit-check"><input type="checkbox" data-f="pinned"${f.pinned ? ' checked' : ''}> Always consider (pin)</label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-memory-inline" data-mem-id="${f.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-memory-inline" data-mem-id="${f.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-memory" data-mem-id="${f.id}" style="margin-left:auto">Forget</button>
      </div>
    </div>`;
}

function memoryAddInner() {
  return `
    <div class="row-edit mem-add" id="memory-add-form">
      <input type="text" class="te-input" data-f="text" placeholder="e.g. We have a dog called Bella">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${memoryCatOptions('preferences')}</select></label>
        <label>About<select data-f="subject">${memorySubjectOptions('family')}</select></label>
        <label class="row-edit-check"><input type="checkbox" data-f="pinned"> Always consider (pin)</label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-memory-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="memory-content">Cancel</button>
      </div>
    </div>`;
}

function renderMemory(data) {
  const el = document.getElementById('memory-content');
  if (!el) return;
  if (!data.enabled) {
    el.innerHTML = '<p class="hint-small">Memory needs OpenRouter — set OPENROUTER_API_KEY to switch it on.</p>';
    return;
  }
  const q = (document.getElementById('memory-search')?.value || '').toLowerCase().trim();
  let facts = data.facts || [];
  if (q) {
    facts = facts.filter((f) => f.text.toLowerCase().includes(q) || memorySubjectName(f.subject).toLowerCase().includes(q));
  }
  if (!facts.length) {
    el.innerHTML = q
      ? '<p class="hint-small">No memories match your search.</p>'
      : '<p class="hint-small">Nothing remembered yet. Add facts here, or just chat with the assistant — it learns as you go.</p>';
  } else {
    el.innerHTML = MEMORY_CAT_ORDER.map((cat) => {
      const items = facts.filter((f) => (MEMORY_CATS[f.category] ? f.category : 'preferences') === cat);
      if (!items.length) return '';
      const rows = items.map((f) => `<div class="mem-fact" data-mem-id="${f.id}">${memoryFactInner(f)}</div>`).join('');
      return `<div class="mem-group"><h3 class="mem-group-title">${MEMORY_CATS[cat].icon} ${MEMORY_CATS[cat].label} <span class="mem-count">${items.length}</span></h3>${rows}</div>`;
    }).join('');
  }
  if (!memorySearchWired) {
    const s = document.getElementById('memory-search');
    if (s) { s.addEventListener('input', () => renderMemory(store.memory || { enabled: true, facts: [] })); memorySearchWired = true; }
  }
}

// --- Feature B: Download all our data --------------------------------------
// Pulls the whole-household export from the backend and saves it as a dated
// JSON file. Non-200s and network errors both surface as a toast rather than
// a broken/empty download.
async function downloadAllData() {
  try {
    const res = await fetch(`${API}/export`, { credentials: 'include' });
    if (!res.ok) {
      showToast(`Export failed (${res.status}) — please try again`, true);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `hub-export-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('Your data is downloading');
  } catch {
    showToast('Export failed — please try again', true);
  }
}

function renderSettings(data) {
  const { users, sync = {}, notification_log = [], integrations = {}, google_accounts = [] } = data;
  const googleOk = integrations.google_calendar;
  const aiOk = integrations.openrouter;
  const bankOk = integrations.open_banking;
  const bankConns = store.finances?.connections || [];
  const accounts = store.finances?.accounts || [];
  const docCount = store.documents?.documents?.length || 0;

  const counts = [
    { n: store.calendar?.events?.length || 0, label: 'Events' },
    { n: (store.dashboard?.tasks || []).filter((t) => !t.done).length, label: 'Open tasks' },
    { n: store.appointments?.appointments?.length || 0, label: 'Appointments' },
    { n: accounts.length, label: 'Accounts' },
    { n: store.finances?.transactions?.length || 0, label: 'Transactions' },
    { n: store.holidays?.trips?.length || 0, label: 'Trips' },
    { n: docCount, label: 'Documents' },
  ];
  const integ = [
    { key: 'google_calendar', icon: '📅', name: 'Google Calendar', on: 'Calendars sync hourly', off: 'Add GOOGLE_CLIENT_ID to .env' },
    { key: 'open_banking', icon: '🏦', name: 'Open Banking (TrueLayer)', on: 'Balances & transactions', off: 'Add TRUELAYER_CLIENT_ID to .env' },
    { key: 'openrouter', icon: '✨', name: 'OpenRouter AI', on: 'Holiday ideas, assistant & receipt scan', off: 'Add OPENROUTER_API_KEY to .env' },
    { key: 'whatsapp', icon: '💬', name: 'WhatsApp (Twilio)', on: '7am digest + two-way assistant', off: 'Configure Twilio in .env' },
    { key: 'weather', icon: '🌤️', name: 'Weather', on: 'Daily forecast, holiday-aware', off: 'Add WEATHER_LATITUDE/LONGITUDE to .env' },
    { key: 'email', icon: '✉️', name: 'Email reminders (SMTP)', on: 'Renewal alerts configured', off: 'Add SMTP_* and NOTIFY_EMAIL to .env' },
    { key: 'receipt_scan', icon: '🧾', name: 'Receipt scanning', on: 'Vision OCR ready on Finances', off: 'Add OPENROUTER_API_KEY to .env' },
    { key: 'google_writeback', icon: '↩️', name: 'Calendar write-back', on: 'Portal events push to Google', off: 'Configure Google OAuth' },
  ];

  const themePref = getThemePref();
  const themeSeg = (val, label, iconKey) =>
    `<button type="button" class="theme-seg wf-action${themePref === val ? ' active' : ''}" data-action="set-theme" data-theme="${val}">${iconKey ? THEME_ICONS[iconKey] : ''}${label}</button>`;

  document.getElementById('settings-content').innerHTML = `
    <div class="settings-section">
      <h3>Appearance</h3>
      <p>Choose a theme. <strong>System</strong> follows your device's light or dark setting automatically.</p>
      <div class="theme-seg-group" role="group" aria-label="Theme">
        ${themeSeg('light', 'Light', 'sun')}
        ${themeSeg('dark', 'Dark', 'moon')}
        ${themeSeg('system', 'System', '')}
      </div>
    </div>
    <div class="settings-section">
      <h3>System status</h3>
      <p>The Hub keeps itself up to date — Google Calendar and banks re-sync automatically every hour.</p>
      <div class="sync-status-row">
        <div class="sync-status-main"><span class="sync-dot"></span> Auto-sync <strong>hourly</strong></div>
        <div class="sync-status-time">Last sync: ${sync.last_sync ? fmt.relative(sync.last_sync) : 'not yet'}</div>
      </div>
      <div class="settings-stat-grid">
        ${counts.map((c) => `<div class="settings-stat"><span class="settings-stat-num">${c.n}</span><span class="settings-stat-label">${c.label}</span></div>`).join('')}
      </div>
    </div>
    <div class="settings-section">
      <h3>Integrations</h3>
      <p>Connected services powering The Hub. Configure in the server <code>.env</code>.</p>
      ${integ
        .map(
          (i) => `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">${i.icon}</div>
            <div>
              <div class="connection-name">${i.name}</div>
              <div class="connection-status ${integrations[i.key] ? 'connected' : ''}">${integrations[i.key] ? i.on : i.off}</div>
            </div>
          </div>
          <span class="status-badge ${integrations[i.key] ? 'ok' : 'off'}">${integrations[i.key] ? 'On' : 'Off'}</span>
        </div>`
        )
        .join('')}
    </div>
    <div class="settings-section">
      <h3>Calendar connections</h3>
      <p>Connect as many Google accounts as you like — personal and work both sync in. Add each while signed in as its owner. ${googleOk ? '' : 'Add GOOGLE_CLIENT_ID to .env first.'}</p>
      ${google_accounts.length
        ? google_accounts
            .map(
              (a) => `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">📅</div>
            <div>
              <div class="connection-name">${esc(a.email)}</div>
              <div class="connection-status connected">${userName(users, a.user_id)} · ${a.last_synced_at ? 'synced ' + fmt.datetime(a.last_synced_at) : 'connected'}</div>
            </div>
          </div>
          <button class="btn btn-sm btn-outline wf-action" data-action="disconnect-google" data-account-id="${a.id}" data-email="${esc(a.email)}">Remove</button>
        </div>`
            )
            .join('')
        : `<p style="font-size:0.875rem;color:var(--text-muted)">No Google accounts connected yet.</p>`}
      <button class="btn btn-sm btn-primary wf-action" data-action="connect-google" style="margin-top:10px" ${googleOk ? '' : 'disabled title="Configure Google OAuth in .env"'}>+ Add Google account${currentUser ? ' (as ' + esc(currentUser.name) + ')' : ''}</button>
    </div>
    <div class="settings-section">
      <h3>Bank connections</h3>
      <p>Open Banking via TrueLayer — ${bankOk ? 'configured' : 'add TRUELAYER_CLIENT_ID to .env'}.</p>
      ${bankConns.length
        ? bankConns
            .map(
              (c) => `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">🏦</div>
            <div>
              <div class="connection-name">${esc(c.provider_name)}</div>
              <div class="connection-status ${c.status === 'needs_reauth' ? '' : 'connected'}">${c.status === 'needs_reauth'
                ? '⚠️ Needs re-connect'
                : (c.last_synced_at ? 'Last sync ' + fmt.datetime(c.last_synced_at) : 'Connected')}</div>
            </div>
          </div>
          <button class="btn btn-sm btn-secondary wf-action" data-action="connect-bank-provider" data-provider-id="${esc(c.provider_id)}">Reconnect</button>
        </div>`
            )
            .join('')
        : `<p style="font-size:0.875rem;color:var(--text-muted)">No banks connected yet — use Finances → Connect bank.</p>`}
      <button class="btn btn-sm btn-primary wf-action" data-action="connect-bank" style="margin-top:10px" ${bankOk ? '' : 'disabled'}>Connect Starling / Revolut / Amex / Virgin</button>
      ${accounts.length ? `
      <div class="settings-accounts">
        ${accounts
          .map(
            (a) => `<div class="acct-line"><span class="acct-line-name">${esc(a.name)} <span class="acct-line-type">${esc(a.type)}</span></span><span class="acct-line-bal ${a.balance < 0 ? 'neg' : ''}">${fmt.gbp(a.balance)}</span></div>`
          )
          .join('')}
      </div>
      <p class="hint-small" style="margin-top:8px">Credit cards show what you owe as a negative balance. An account stuck at £0.00 (e.g. Amex) needs reconnecting above to re-sync.</p>` : ''}
    </div>
    <div class="settings-section">
      <h3>WhatsApp assistant</h3>
      <p>Morning digest at 7am + two-way chat with the AI — ${integrations.whatsapp ? 'configured' : 'connect Twilio to enable'}.</p>
      ${users
        .map(
          (u) => `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">💬</div>
            <div>
              <div class="connection-name">${userName(users, u.id)}</div>
              <div class="connection-status ${u.phone ? 'connected' : ''}">${u.phone ? esc(u.phone) : 'No number — add via Edit on the Household card'}</div>
            </div>
          </div>
        </div>`
        )
        .join('')}
      <button class="btn btn-sm btn-primary wf-action" data-action="whatsapp-test" style="margin-top:10px" ${integrations.whatsapp ? '' : 'disabled title="Configure WhatsApp in .env first"'}>Send me a test digest</button>
      <div id="voice-notes-status" class="voice-notes-line" hidden></div>
      <label class="notif-pref-row snap-sort-row" id="snap-sort-row" hidden>
        <span class="notif-pref-text"><strong>Auto-sort photos sent to WhatsApp</strong><small>Receipts become expenses, documents go to your Vault, everything else to Photos.</small></span>
        <input type="checkbox" class="notif-pref-toggle" id="snap-sort-toggle">
      </label>
    </div>
    <div class="settings-section">
      <h3>Weather</h3>
      <p>Daily forecast in the header and morning digest — ${integrations.weather ? 'configured' : 'set WEATHER_LATITUDE / WEATHER_LONGITUDE in .env'}. Automatically switches to your holiday destination when a trip is coming up.</p>
      <div class="connection-row">
        <div class="connection-info">
          <div class="connection-icon">🌤️</div>
          <div>
            <div class="connection-name">Home forecast${weatherData && weatherData.label ? ' — ' + esc(weatherData.label) : ''}</div>
            <div class="connection-status ${integrations.weather ? 'connected' : ''}">${integrations.weather ? (weatherData && weatherData.current && weatherData.current.temp != null ? `${weatherData.current.emoji || ''} ${weatherData.current.temp}°C, ${esc(weatherData.current.desc || '')}` : 'Configured') : 'Not configured'}${weatherData && weatherData.holiday ? ' · following holiday' : ''}</div>
          </div>
        </div>
        <button class="btn btn-sm btn-outline" id="settings-weather-open">View forecast</button>
      </div>
    </div>
    <div class="settings-section">
      <h3>Email renewal reminders</h3>
      <p>SMTP alerts before documents &amp; policies expire — ${integrations.email ? 'configured' : 'add SMTP_* and NOTIFY_EMAIL to .env'}.</p>
      <button class="btn btn-sm btn-primary wf-action" data-action="send-reminders" ${integrations.email ? '' : 'disabled'}>Send test reminders</button>
    </div>
    <div class="settings-section" id="notif-prefs-section" hidden></div>
    <div class="settings-section" id="push-settings">
      <h3>Push notifications</h3>
      <p>Loading…</p>
    </div>
    <div class="settings-section" id="install-app">
      <h3>Add to your phone</h3>
      <p>Install The Hub as an app to get a home-screen icon, push notifications, and an <strong>alert badge on the icon</strong> showing how many reminders are waiting.</p>
      <div class="install-steps">
        <div class="install-os"><strong>iPhone / iPad</strong><ol><li>Open The Hub in <em>Safari</em></li><li>Tap the <em>Share</em> button</li><li>Tap <em>Add to Home Screen</em></li><li>Open it from the new icon, then turn on push above</li></ol></div>
        <div class="install-os"><strong>Android</strong><ol><li>Open The Hub in <em>Chrome</em></li><li>Tap the <em>⋮</em> menu</li><li>Tap <em>Install app</em> / <em>Add to Home screen</em></li></ol></div>
      </div>
    </div>
    <div class="settings-section">
      <h3>Household members</h3>
      <p>Colour labels used across calendar, tasks and appointments.</p>
      ${users
        .map(
          (u) => `
        <div class="connection-row">
          <div class="connection-info">
            <span class="member-dot" style="background:${safeColour(u.colour)};width:12px;height:12px"></span>
            <div class="connection-name">${esc(u.name)}</div>
          </div>
          <button class="btn btn-sm btn-ghost wf-action" data-action="edit-member" data-user-id="${u.id}">Edit</button>
        </div>`
        )
        .join('')}
    </div>
    <div class="settings-section">
      <h3>Document vault</h3>
      <p>${docCount} documents stored — upload insurance, passports and other files.</p>
      <button class="btn btn-sm btn-primary wf-action" data-tab-link="documents">Open document vault</button>
    </div>
    <div class="settings-section">
      <h3>Your data</h3>
      <p>Download everything The Hub holds for your household as a single JSON file — a portable backup you can keep safe or move elsewhere.</p>
      <button class="btn btn-sm btn-primary wf-action" data-action="export-data">Download all our data</button>
    </div>
    <div class="settings-section">
      <h3>Login &amp; access</h3>
      <p>Change your password, sign out, or preview the login screen.</p>
      <button class="btn btn-primary wf-action" data-action="change-password">Change password</button>
      <button class="btn btn-outline wf-action" data-action="preview-login" style="margin-left:8px">Preview login screen</button>
      <button class="btn btn-ghost wf-action" data-action="sign-out" style="margin-left:8px">Sign out</button>
    </div>
    <div class="settings-section">
      <h3>Recent notifications</h3>
      ${notification_log.length ? notification_log.map((n) => `<div class="list-item" style="padding:10px 0"><div class="list-item-body"><div class="list-item-title">${esc(n.subject || n.recipient || 'Email')}</div><div class="list-item-meta">${esc(n.sent_at || '')} · ${esc(n.status || '')}</div></div></div>`).join('') : '<p class="hint-small">No emails sent yet.</p>'}
    </div>`;

  const swBtn = document.getElementById('settings-weather-open');
  if (swBtn) swBtn.onclick = openWeather;

  const pill = document.getElementById('sync-pill');
  if (pill) pill.innerHTML = `<span class="sync-dot"></span> ${sync.last_sync ? 'Synced ' + fmt.relative(sync.last_sync) : 'Not synced yet'}`;
}

// --- Notifications & reminders settings card ---
let notifPrefs = null;

const NOTIF_PREF_ROWS = [
  ['morning_digest', 'Morning digest', 'A short summary each morning'],
  ['evening_digest', 'Evening digest', 'A wrap-up each evening'],
  ['appointment_reminders', 'Appointment reminders', 'Ahead of health, dental, car & vet visits'],
  ['bill_reminders', 'Bill reminders', 'Before recurring bills fall due'],
  ['renewal_reminders', 'Renewal reminders', 'Insurance, MOT and other renewals'],
  ['document_expiry_reminders', 'Document expiry', 'When a vault document is about to expire'],
  ['weekly_finance_summary', 'Weekly finance recap', 'A money round-up each Sunday evening'],
  ['budget_alerts', 'Budget alerts', 'A heads-up when a spending category nears or exceeds its monthly budget'],
  ['proactive_inbox', 'Email suggestions', 'Let the Hub scan your inbox for bookings, renewals & bills and nudge you'],
];

// Fetch notification preferences and render the settings card. Hides the card
// gracefully if the endpoint is missing (older backend) or errors.
async function loadNotificationPrefs() {
  const section = document.getElementById('notif-prefs-section');
  if (!section) return;
  try {
    notifPrefs = await api('/notifications/prefs');
    renderNotificationPrefs(notifPrefs);
  } catch {
    notifPrefs = null;
    section.hidden = true;
    section.innerHTML = '';
  }
}

// Voice notes: a read-only status line in the WhatsApp assistant settings.
// Enabling is a server-side env change (VOICE_NOTES_ENABLED), so there's no
// toggle here — just tell the user whether it's on. Hide the line if the
// endpoint is unavailable so the section degrades gracefully.
async function loadVoiceStatus() {
  const el = document.getElementById('voice-notes-status');
  if (!el) return;
  try {
    const res = await api('/whatsapp/voice-status');
    const on = !!(res && res.enabled);
    el.hidden = false;
    el.classList.toggle('is-on', on);
    el.textContent = on
      ? "🎙️ Voice notes: On — send the Hub a WhatsApp voice note and it'll transcribe + act on it"
      : "🎙️ Voice notes: Off — send a voice note to the Hub's WhatsApp and it gets transcribed once enabled (set VOICE_NOTES_ENABLED on the server).";
  } catch {
    el.hidden = true;
    el.textContent = '';
  }
}

// Snap-and-sort: a toggle in the WhatsApp assistant settings bound to the
// snap_sort_enabled notification pref. Kept self-contained (its own load/PATCH)
// so it doesn't depend on the notif-prefs card rendering. Hides gracefully when
// the pref is unavailable (older backend). PATCHes the same prefs endpoint.
async function loadSnapSortStatus() {
  const row = document.getElementById('snap-sort-row');
  const toggle = document.getElementById('snap-sort-toggle');
  if (!row || !toggle) return;
  try {
    const prefs = await api('/notifications/prefs');
    if (!prefs || typeof prefs.snap_sort_enabled === 'undefined') {
      row.hidden = true;
      return;
    }
    toggle.checked = !!prefs.snap_sort_enabled;
    row.hidden = false;
    toggle.onchange = async () => {
      const value = toggle.checked;
      try {
        await api('/notifications/prefs', { method: 'PATCH', body: JSON.stringify({ snap_sort_enabled: value }) });
        showToast('Saved');
      } catch (err) {
        toggle.checked = !value; // revert on failure
        showToast(err.message, true);
      }
    };
  } catch {
    row.hidden = true;
  }
}

function renderNotificationPrefs(prefs) {
  const section = document.getElementById('notif-prefs-section');
  if (!section || !prefs) return;
  section.hidden = false;
  const master = !!prefs.master_enabled;
  const lead = Number.isFinite(prefs.reminder_lead_days) ? prefs.reminder_lead_days : 3;
  const largeOn = !!prefs.large_transaction_alerts;
  const threshold = Number.isFinite(prefs.large_transaction_threshold) ? prefs.large_transaction_threshold : 200;
  const rows = NOTIF_PREF_ROWS.map(([key, label, desc]) => `
      <label class="notif-pref-row${master ? '' : ' disabled'}">
        <span class="notif-pref-text"><strong>${label}</strong><small>${desc}</small></span>
        <input type="checkbox" class="notif-pref-toggle" data-pref="${key}"${prefs[key] ? ' checked' : ''}${master ? '' : ' disabled'}>
      </label>`).join('');
  section.innerHTML = `
    <h3>Notifications &amp; reminders</h3>
    <p>Decide what The Hub sends you. Turn the master switch off to pause everything without losing your choices.</p>
    <div class="notif-pref-list">
      <label class="notif-pref-row notif-pref-master">
        <span class="notif-pref-text"><strong>All notifications</strong><small>Master switch — off silences every reminder below</small></span>
        <input type="checkbox" class="notif-pref-toggle" data-pref="master_enabled"${master ? ' checked' : ''}>
      </label>
      ${rows}
      <label class="notif-pref-row${master ? '' : ' disabled'}">
        <span class="notif-pref-text"><strong>Large transaction alerts</strong><small>Get pinged when a big payment lands</small></span>
        <input type="checkbox" class="notif-pref-toggle" data-pref="large_transaction_alerts"${largeOn ? ' checked' : ''}${master ? '' : ' disabled'}>
      </label>
      <label class="notif-pref-row${master && largeOn ? '' : ' disabled'}">
        <span class="notif-pref-text"><strong>Alert me over</strong><small>Threshold for a “large” transaction</small></span>
        <span class="notif-pref-amount">£<input type="number" min="0" step="10" class="notif-pref-lead" data-pref="large_transaction_threshold" value="${threshold}"${master && largeOn ? '' : ' disabled'}></span>
      </label>
      <label class="notif-pref-row${master ? '' : ' disabled'}">
        <span class="notif-pref-text"><strong>Remind me this many days ahead</strong><small>How far in advance reminders arrive</small></span>
        <input type="number" min="0" max="60" class="notif-pref-lead" data-pref="reminder_lead_days" value="${lead}"${master ? '' : ' disabled'}>
      </label>
    </div>`;
}

// PATCH a single preference immediately (optimistic) and toast "Saved".
async function handleNotifPrefChange(el) {
  if (!notifPrefs) return;
  const key = el.dataset.pref;
  let value;
  if (el.type === 'checkbox') {
    value = el.checked;
  } else {
    value = parseInt(el.value, 10);
    if (!Number.isFinite(value) || value < 0) value = 0;
    // reminder_lead_days is capped at 60; the large-transaction threshold has no upper bound.
    if (key === 'reminder_lead_days' && value > 60) value = 60;
    el.value = value;
  }
  notifPrefs[key] = value;
  // The master switch and the large-transaction toggle enable/disable other rows —
  // re-render for instant feedback.
  if (key === 'master_enabled' || key === 'large_transaction_alerts') renderNotificationPrefs(notifPrefs);
  try {
    const updated = await api('/notifications/prefs', { method: 'PATCH', body: JSON.stringify({ [key]: value }) });
    if (updated && typeof updated === 'object') {
      notifPrefs = updated;
      if (key === 'master_enabled' || key === 'large_transaction_alerts') renderNotificationPrefs(notifPrefs);
    }
    showToast('Saved');
  } catch (err) {
    showToast(err.message, true);
    loadNotificationPrefs(); // re-sync the card with the server on failure
  }
}

// --- Web push notifications (browser) ---
// Standard helper: turn a base64url VAPID key into the Uint8Array subscribe() wants.
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i);
  return output;
}

function pushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

async function currentPushSubscription() {
  if (!pushSupported()) return null;
  try {
    // Don't block forever on serviceWorker.ready (it never resolves if no SW ever
    // activates) — race it against a short timeout so the settings card always paints.
    const reg = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((res) => setTimeout(() => res(null), 3000)),
    ]);
    if (!reg) return null;
    return await reg.pushManager.getSubscription();
  } catch {
    return null;
  }
}

// Paint the push card in Settings to reflect the current subscription state.
async function refreshPushUI() {
  const section = document.getElementById('push-settings');
  if (!section) return;
  if (!pushSupported()) {
    section.innerHTML = `
      <h3>Push notifications</h3>
      <p>This browser doesn't support web push notifications.</p>`;
    return;
  }
  const sub = await currentPushSubscription();
  const on = !!sub;
  const denied = Notification.permission === 'denied';
  section.innerHTML = `
    <h3>Push notifications</h3>
    <p>Get reminders on this device even when The Hub isn't open.${denied && !on ? ' Notifications are blocked in your browser settings — allow them there first.' : ''}</p>
    <div class="connection-row">
      <div class="connection-info">
        <div class="connection-icon">🔔</div>
        <div>
          <div class="connection-name">This device</div>
          <div class="connection-status ${on ? 'connected' : ''}">${on ? 'Notifications on' : 'Not enabled'}</div>
        </div>
      </div>
      <span class="status-badge ${on ? 'ok' : 'off'}">${on ? 'On' : 'Off'}</span>
    </div>
    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
      ${on
        ? `<button class="btn btn-sm btn-soft wf-action" data-action="push-test">Send test</button>
           <button class="btn btn-sm btn-ghost wf-action" data-action="disable-push">Turn off</button>`
        : `<button class="btn btn-sm btn-primary wf-action" data-action="enable-push"${denied ? ' disabled title="Blocked in browser settings"' : ''}>Enable push notifications</button>`}
    </div>`;
}

async function enablePush() {
  if (!pushSupported()) return showToast('Push notifications not supported on this device', true);
  try {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return showToast('Notification permission denied', true);
    let keyInfo;
    try {
      keyInfo = await api('/push/vapid-key');
    } catch {
      return showToast('Push not configured on server', true);
    }
    if (!keyInfo || !keyInfo.enabled || !keyInfo.key) {
      return showToast('Push not configured on server', true);
    }
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(keyInfo.key),
      });
    }
    const json = sub.toJSON();
    await api('/push/subscribe', {
      method: 'POST',
      body: JSON.stringify({
        endpoint: sub.endpoint,
        p256dh: json.keys?.p256dh,
        auth: json.keys?.auth,
      }),
    });
    showToast('Notifications on');
    await refreshPushUI();
  } catch (err) {
    showToast(err.message || 'Could not enable notifications', true);
    await refreshPushUI();
  }
}

async function disablePush() {
  try {
    const sub = await currentPushSubscription();
    if (sub) {
      // Tell the server first (so it stops sending) then drop the local subscription.
      try {
        await api('/push/unsubscribe', { method: 'POST', body: JSON.stringify({ endpoint: sub.endpoint }) });
      } catch {
        /* server may already have pruned it — unsubscribe locally regardless */
      }
      await sub.unsubscribe();
    }
    showToast('Notifications off');
  } catch (err) {
    showToast(err.message, true);
  }
  await refreshPushUI();
}

async function sendPushTest() {
  try {
    await api('/push/test', { method: 'POST' });
    showToast('Test notification sent');
  } catch (err) {
    showToast(err.message, true);
  }
}

// Emoji per result type for the unified-search rows (falls back to a magnifier).
const SEARCH_TYPE_ICONS = {
  event: '📅',
  appointment: '🩺',
  bill: '💷',
  transaction: '💷',
  task: '✅',
  trip: '🧳',
  holiday: '🧳',
  document: '📄',
  subscription: '🔁',
  memory: '🧠',
  contact: '👤',
  tradesperson: '🛠️',
  maintenance: '🛠️',
};

function openSearchModal() {
  closeModal();
  closeNotif();

  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal wf-modal-wide" role="dialog">
      <div class="wf-modal-header">
        <h3>Search</h3>
        <p>Events, bills, appointments, tasks, trips, documents and more</p>
      </div>
      <div class="wf-modal-body">
        <label class="field field-full">Search<input type="text" id="search-input" placeholder="Try dentist, netflix, boiler…" autofocus></label>
        <div id="search-results" class="search-results"><p class="hint-small">Type to search the household</p></div>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;

  let searchTimer;
  const input = document.getElementById('search-input');
  const resultsEl = document.getElementById('search-results');

  async function runSearch(q) {
    if (!q.trim()) {
      resultsEl.innerHTML = '<p class="hint-small">Type to search the household</p>';
      return;
    }
    try {
      const data = await api(`/search?q=${encodeURIComponent(q.trim())}`);
      const results = data.results || [];
      resultsEl.innerHTML = results.length
        ? results.map((r) => {
            // Backend contract: {type, title, subtitle, tab, id}. Fall back to the
            // older {label, meta} shape so a mixed-version backend still renders.
            const title = r.title || r.label || 'Untitled';
            const subtitle = r.subtitle ?? r.meta ?? '';
            const ic = SEARCH_TYPE_ICONS[r.type] || '🔎';
            return `
          <button type="button" class="search-result wf-action" data-tab-link="${esc(r.tab || 'home')}">
            <span class="search-result-type">${ic} ${esc(r.type || '')}</span>
            <strong>${esc(title)}</strong>
            ${subtitle ? `<span class="search-result-meta">${esc(subtitle)}</span>` : ''}
          </button>`;
          }).join('')
        : '<p class="hint-small">No matches found.</p>';
    } catch (err) {
      resultsEl.innerHTML = `<p class="hint-small">${esc(err.message)}</p>`;
    }
  }

  input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(input.value), 250);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      runSearch(input.value);
    }
  });
}

function openLoginPreview() {
  closeModal();
  closeNotif();
  showLogin(); // shows the "Back to preview" button because currentUser is set
}

function closeLoginPreview() {
  document.getElementById('login-overlay').hidden = true;
}

const NOTIF_SEEN_KEY = 'hub-notif-seen';

function reminderFingerprint(list) {
  return (list || []).map((r) => `${r.type}|${r.text}|${r.when}`).sort().join('||');
}

// Set/clear the home-screen app-icon badge (installed PWA, incl. iOS 16.4+).
function updateAppBadge(count) {
  try {
    if (!('setAppBadge' in navigator)) return;
    if (count > 0) navigator.setAppBadge(count);
    else navigator.clearAppBadge();
  } catch {
    /* Badging unsupported / not installed — ignore */
  }
}

function renderNotifications(reminders, unread) {
  const badge = document.getElementById('notif-badge');
  let seen = null;
  try {
    seen = localStorage.getItem(NOTIF_SEEN_KEY);
  } catch {
    /* private browsing etc. — badge just behaves as before */
  }
  // Hide the count once the user has opened the panel for this exact set of reminders.
  const showing = unread > 0 && reminderFingerprint(reminders) !== seen;
  if (showing) {
    badge.hidden = false;
    badge.textContent = unread;
  } else {
    badge.hidden = true;
  }
  updateAppBadge(showing ? unread : 0);  // mirror the count onto the app icon
  const list = reminders || [];
  document.getElementById('notif-list').innerHTML = list.length
    ? list
        .map((n) => `<div class="notif-item unread">${esc(n.text)}<time>${esc(n.when || '')}</time></div>`)
        .join('')
    : '<p class="hint-small" style="padding:14px">No reminders right now.</p>';
}

function initTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });
}

function initActions() {
  // Show the breed field only for pets in the dependent add/edit forms.
  document.addEventListener('change', (e) => {
    const sel = e.target.closest('.dependent-kind-select');
    if (!sel) return;
    const breed = sel.closest('.row-edit')?.querySelector('.dependent-breed-field');
    if (breed) breed.style.display = sel.value === 'pet' ? '' : 'none';
  });

  document.addEventListener('click', (e) => {
    const tabLink = e.target.closest('[data-tab-link]');
    if (tabLink) {
      if (tabLink.dataset.mediaTrip) {
        mediaFilter = tabLink.dataset.mediaTrip;
      }
      switchTab(tabLink.dataset.tabLink);
      closeModal();
      if (tabLink.dataset.mediaTrip && store.media) {
        renderMedia(store.media, mediaFilter);
      }
      return;
    }

    const mediaTripBtn = e.target.closest('[data-media-trip]');
    if (mediaTripBtn) {
      mediaFilter = mediaTripBtn.dataset.mediaTrip;
      renderMedia(store.media, mediaFilter);
      return;
    }

    // Open a photo/video large in the lightbox — but let the delete button (a
    // .wf-action inside the tile) fall through to the action dispatch below.
    const mediaTile = e.target.closest('[data-media-open]');
    if (mediaTile && !e.target.closest('.wf-action')) {
      openMediaLightbox(mediaTile.dataset.mediaOpen, mediaTile.dataset.mediaType);
      return;
    }

    const catBtn = e.target.closest('[data-vault-cat]');
    if (catBtn) {
      vaultFilter = catBtn.dataset.vaultCat;
      renderDocuments(store.documents, vaultFilter);
      return;
    }

    const catBtnAppt = e.target.closest('[data-appt-cat]');
    if (catBtnAppt) {
      document.querySelectorAll('#appt-categories .cat-btn').forEach((b) => b.classList.remove('active'));
      catBtnAppt.classList.add('active');
      renderAppointments(store.appointments, document.querySelector('input[name="appt-filter"]:checked')?.value || 'all', catBtnAppt.dataset.apptCat);
      return;
    }

    const btn = e.target.closest('.wf-action');
    if (!btn) return;

    const action = btn.dataset.action;
    const modal = btn.dataset.modal;
    if (!action) return; // e.g. #login-close carries wf-action styling but no action

    if (action === 'search') {
      openSearchModal();
      return;
    }
    if (action === 'close-modal') {
      closeModal();
      return;
    }
    if (action === 'connect-google') {
      window.location.href = `${API}/auth/google/start`;
      return;
    }
    if (action === 'disconnect-google') {
      const email = btn.dataset.email || 'this account';
      if (!confirm(`Remove ${email}? Its calendar events will be deleted from the portal.`)) return;
      api(`/google/accounts/${btn.dataset.accountId}`, { method: 'DELETE' })
        .then(() => {
          showToast(`Removed ${email}`);
          load();
        })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'sync-calendar') {
      api('/calendar/sync', { method: 'POST' })
        .then((r) => {
          showToast(`Synced — ${JSON.stringify(r.synced)}`);
          load();
        })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action && action.startsWith('cal-')) {
      if (!calCursor) calCursor = new Date();
      if (action === 'cal-prev') {
        if (calView === 'week') calCursor.setDate(calCursor.getDate() - 7);
        else calCursor = new Date(calCursor.getFullYear(), calCursor.getMonth() - 1, 1);
      } else if (action === 'cal-next') {
        if (calView === 'week') calCursor.setDate(calCursor.getDate() + 7);
        else calCursor = new Date(calCursor.getFullYear(), calCursor.getMonth() + 1, 1);
      } else if (action === 'cal-today') {
        calCursor = new Date();
      } else if (action === 'cal-view-month') {
        calView = 'month';
      } else if (action === 'cal-view-week') {
        calView = 'week';
      } else if (action === 'cal-view-agenda') {
        calView = 'agenda';
      }
      if (store.calendar) renderCalendar(store.calendar);
      return;
    }
    if (['filter-all-trips', 'filter-booked', 'filter-planning', 'filter-ideas'].includes(action)) {
      const map = { 'filter-all-trips': 'all', 'filter-booked': 'booked', 'filter-planning': 'planning', 'filter-ideas': 'idea' };
      tripFilter = map[action] || 'all';
      document.querySelectorAll('[data-action^="filter-"]').forEach((b) => b.classList.toggle('active', b.dataset.action === action));
      if (store.holidays) renderHolidays(store.holidays);
      return;
    }
    if (action === 'preview-login') {
      openLoginPreview();
      return;
    }
    if (action === 'change-password') {
      openChangePasswordModal();
      return;
    }
    if (action === 'transfer') {
      openTransferModal();
      return;
    }
    if (action === 'export-transactions') {
      const a = document.createElement('a');
      a.href = `${API}/finances/export`;
      a.download = 'transactions.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
      showToast('Exported transactions.csv');
      return;
    }
    if (action === 'sync-appointments') {
      api('/appointments/sync-calendar', { method: 'POST' })
        .then((r) => {
          showToast(r.created ? `Synced ${r.created} appointment(s) to calendar` : 'Calendar already up to date');
          load();
        })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'compare-trips') {
      openCompareTripsModal();
      return;
    }
    if (action === 'find-trips-email') {
      findTripsInEmail(btn);
      return;
    }
    if (action === 'create-trip-from-proposal') {
      const p = store.tripProposals?.[btn.dataset.proposalIdx];
      if (!p) return;
      btn.disabled = true;
      btn.textContent = 'Creating…';
      api('/holidays/trips', {
        method: 'POST',
        body: JSON.stringify({ title: p.title || p.destination || 'Trip', destination: p.destination || null }),
      }).then(async () => {
        showToast('Trip created from your email');
        await load();
      }).catch((err) => { showToast(err.message, true); btn.disabled = false; btn.textContent = 'Create trip'; });
      return;
    }
    if (action === 'edit-trip') {
      if (btn.dataset.tripId) openEditTripModal(btn.dataset.tripId);
      return;
    }
    if (action === 'edit-member') {
      if (btn.dataset.userId) openEditMemberModal(btn.dataset.userId);
      return;
    }
    if (action === 'event-detail') {
      if (btn.dataset.eventId) openEventDetailModal(btn.dataset.eventId);
      return;
    }
    if (action === 'edit-event') {
      if (btn.dataset.eventId) openEditEventModal(btn.dataset.eventId);
      return;
    }
    if (action === 'delete-event') {
      const evId = btn.dataset.eventId;
      if (evId && confirm('Delete this event?')) {
        api(`/events/${evId}`, { method: 'DELETE' })
          .then(() => {
            closeModal();
            showToast('Event deleted');
            load();
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'edit-appointment') {
      if (btn.dataset.apptId) openEditAppointmentModal(btn.dataset.apptId);
      return;
    }
    if (action === 'import-csv') {
      document.getElementById('csv-file-input')?.click();
      return;
    }
    if (action === 'connect-bank') {
      openConnectBankModal();
      return;
    }
    if (action === 'connect-bank-provider') {
      const pid = btn.dataset.providerId;
      if (pid) window.location.href = `${API}/banking/connect/${pid}`;
      return;
    }
    if (action === 'sync-banks') {
      api('/banking/sync', { method: 'POST' })
        .then((r) => {
          const ok = (r.synced || []).filter((s) => !s.error);
          showToast(`Synced ${ok.length} bank connection(s)`);
          load();
        })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'categorize') {
      showToast('Categorising…');
      api('/finances/categorize', { method: 'POST' })
        .then((r) => { showToast(`Categorised ${r.updated} transactions`); load(); })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'categorize-ai') {
      showToast('Asking AI to categorise…');
      api('/finances/categorize-ai', { method: 'POST' })
        .then((r) => { showToast(r.suggested ? `AI labelled ${r.suggested} merchant(s) · ${r.reclassified} txns` : 'Nothing left to categorise'); load(); })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'rename-account') {
      openRenameAccountModal(btn.dataset.accountId, btn.dataset.accountName || '');
      return;
    }
    if (action === 'hide-account') {
      const aid = btn.dataset.accountId;
      if (aid && confirm('Hide this account from the finances view?')) {
        api(`/accounts/${aid}`, { method: 'PATCH', body: JSON.stringify({ hidden: true }) })
          .then(() => { showToast('Account hidden'); load(); })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'show-hidden-accounts') {
      openHiddenAccountsModal();
      return;
    }
    if (action === 'unhide-account') {
      const aid = btn.dataset.accountId;
      if (aid) {
        api(`/accounts/${aid}`, { method: 'PATCH', body: JSON.stringify({ hidden: false }) })
          .then(() => { showToast('Account restored'); closeModal(); load(); })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'disconnect-bank') {
      const cid = btn.dataset.connectionId;
      if (cid && confirm('Disconnect this bank? Linked balances stay but stop updating.')) {
        api(`/banking/connections/${cid}`, { method: 'DELETE' })
          .then(() => {
            showToast('Bank disconnected');
            load();
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'delete-document') {
      const docId = btn.dataset.docId;
      if (docId && confirm('Delete this document and its file?')) {
        api(`/documents/${docId}`, { method: 'DELETE' })
          .then(() => {
            showToast('Document deleted');
            load();
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'delete-media') {
      const mediaId = btn.dataset.mediaId;
      if (mediaId && confirm('Delete this photo/video?')) {
        api(`/media/${mediaId}`, { method: 'DELETE' })
          .then(() => {
            showToast('Media deleted');
            refreshMedia();
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'scan-subscriptions') {
      api('/subscriptions/scan', { method: 'POST' })
        .then((r) => {
          store.subscriptions = r;
          renderSubscriptions(r);
          showToast(`Found ${r.subscriptions?.length || 0} subscriptions`);
        })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'confirm-subscription') {
      const subId = btn.dataset.subId;
      if (subId) {
        api(`/subscriptions/${subId}`, { method: 'PATCH', body: JSON.stringify({ status: 'confirmed' }) })
          .then((r) => {
            store.subscriptions = { subscriptions: r.subscriptions, summary: r.summary };
            renderSubscriptions(store.subscriptions);
            showToast('Subscription confirmed');
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'ignore-subscription') {
      const subId = btn.dataset.subId;
      if (subId && confirm('Hide this subscription from the list?')) {
        api(`/subscriptions/${subId}`, { method: 'PATCH', body: JSON.stringify({ status: 'ignored' }) })
          .then((r) => {
            store.subscriptions = { subscriptions: r.subscriptions, summary: r.summary };
            renderSubscriptions(store.subscriptions);
            showToast('Subscription hidden');
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'track-as-bill') {
      const subId = btn.dataset.subId;
      let sub = (store.subscriptions?.subscriptions || []).find((s) => String(s.id) === String(subId));
      if (!sub) {
        const merged = (store.finances?.merged_recurring?.items || []).find(
          (x) => String(x.subscription_id || '') === String(subId)
        );
        if (merged) {
          sub = {
            id: merged.subscription_id,
            display_name: merged.name,
            amount: merged.amount,
            frequency: merged.frequency,
            category: merged.category,
            next_expected_date: merged.next_expected_date,
            last_charge_date: merged.last_charge_date,
          };
        }
      }
      if (!sub) return showToast('Subscription not found', true);
      btn.disabled = true;
      api('/bills', {
        method: 'POST',
        body: JSON.stringify({
          name: sub.display_name,
          amount: sub.amount,
          due_day: billDueDayFromDates(sub.next_expected_date, sub.last_charge_date),
          recurrence: sub.frequency || 'monthly',
          category: sub.category || 'Subscriptions',
        }),
      })
        .then((bill) => api(`/bills/${bill.id}/lock`, { method: 'POST', body: JSON.stringify({ subscription_id: sub.id }) }))
        .then(() => load())
        .then(() => showToast(`${sub.display_name} is now tracked as a bill`))
        .catch((err) => {
          btn.disabled = false;
          showToast(err.message, true);
        });
      return;
    }
    if (action === 'holiday-idea' && btn.id === 'ai-generate-btn') {
      submitHolidayAI(document.getElementById('ai-prompt-input')?.value);
      return;
    }
    if (modal && MODALS[modal]) {
      openModal(modal);
      return;
    }

    if (action === 'open-settings') {
      switchTab('settings');
      return;
    }
    if (action === 'set-theme') {
      setThemePref(btn.dataset.theme || 'system');
      return;
    }
    if (action === 'toggle-home-customise') {
      toggleHomeCustomise();
      return;
    }
    if (action === 'home-move-card') {
      moveHomeCard(btn.dataset.card, btn.dataset.dir);
      return;
    }
    if (action === 'home-toggle-card-hidden') {
      toggleHomeCardHidden(btn.dataset.card);
      return;
    }
    if (action === 'export-data') {
      downloadAllData();
      return;
    }
    if (action === 'toggle-task') {
      const taskId = btn.dataset.taskId;
      const nowDone = btn.dataset.done !== '1';
      const inAllTasksModal = btn.closest('#modal-root') && document.querySelector('.wf-modal-header h3')?.textContent === 'All tasks';
      if (taskId) {
        api(`/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify({ done: nowDone }) })
          .then(() => load())
          .then(() => { if (inAllTasksModal) openAllTasksModal(); })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'view-all-tasks') {
      openAllTasksModal();
      return;
    }
    if (action === 'edit-task') {
      const row = btn.closest('.task-item');
      const t = (store.dashboard?.tasks || []).find((x) => String(x.id) === String(btn.dataset.taskId));
      if (row && t) {
        row.classList.add('editing');
        row.innerHTML = taskEditInner(store.dashboard.users, t);
        row.querySelector('[data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'save-task-inline') {
      const row = btn.closest('.task-item');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Task needs a title', true); return; }
      const inModal = !!btn.closest('#modal-root');
      api(`/tasks/${btn.dataset.taskId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: f.title.trim(), assignee_id: f.assignee || null, priority: f.priority,
          due: f.due || null, remind_at: f.remind_at || null, notify: !!f.notify,
        }),
      }).then(() => load()).then(() => { if (inModal) openAllTasksModal(); showToast('Task updated'); })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-task-inline') {
      const row = btn.closest('.task-item');
      const t = (store.dashboard?.tasks || []).find((x) => String(x.id) === String(btn.dataset.taskId));
      if (row && t) { row.className = `task-item${t.done ? ' done' : ''}`; row.innerHTML = taskRowInner(store.dashboard.users, t); }
      return;
    }
    if (action === 'delete-task-inline') {
      if (!confirm('Delete this task?')) return;
      const inModal = !!btn.closest('#modal-root');
      api(`/tasks/${btn.dataset.taskId}`, { method: 'DELETE' })
        .then(() => load()).then(() => { if (inModal) openAllTasksModal(); showToast('Task deleted'); })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'mark-paid') {
      const billId = btn.dataset.billId;
      if (billId) {
        api(`/bills/${billId}/pay`, { method: 'POST' })
          .then(() => load())
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'edit-bill') {
      const row = btn.closest('.list-item');
      const b = findBill(btn.dataset.billId);
      if (row && b) { row.classList.add('editing'); row.innerHTML = billEditInner(b); row.querySelector('[data-f="name"]')?.focus(); }
      return;
    }
    if (action === 'save-bill-inline') {
      const row = btn.closest('.list-item');
      const f = readInlineFields(row);
      if (!f.name || !f.name.trim()) { showToast('Bill needs a name', true); return; }
      api(`/bills/${btn.dataset.billId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: f.name.trim(), amount: parseFloat(f.amount) || 0,
          due_day: parseInt(f.due_day, 10) || 1, category: f.category, recurrence: f.recurrence,
        }),
      }).then(() => load()).then(() => showToast('Bill updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-bill-inline') {
      const row = btn.closest('.list-item');
      const b = findBill(btn.dataset.billId);
      if (row && b) { row.className = `list-item${b.paid ? ' bill-paid' : ''}`; row.innerHTML = billRowInner(b); }
      return;
    }
    if (action === 'delete-bill-inline') {
      if (!confirm('Delete this bill?')) return;
      api(`/bills/${btn.dataset.billId}`, { method: 'DELETE' })
        .then(() => load()).then(() => showToast('Bill deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'lock-bill') {
      api(`/bills/${btn.dataset.billId}/lock`, { method: 'POST', body: JSON.stringify({ subscription_id: btn.dataset.subId || null }) })
        .then(() => load()).then(() => showToast('Locked — auto-marks paid when the bank payment lands'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'unlock-bill') {
      api(`/bills/${btn.dataset.billId}/unlock`, { method: 'POST' })
        .then(() => load()).then(() => showToast('Unlocked'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'add-budget') {
      const budgeted = new Set((store.finances?.budgets || []).map((b) => b.category));
      const cats = (store.finances?.categories || BILL_CATEGORIES).filter((c) => !budgeted.has(c) && c !== 'Income');
      btn.outerHTML = budgetAddInner(cats);
      document.querySelector('#budget-add-form [data-f="monthly_limit"]')?.focus();
      return;
    }
    if (action === 'save-budget-new') {
      const f = readInlineFields(document.getElementById('budget-add-form'));
      const limit = parseFloat(f.monthly_limit);
      if (!f.category) { showToast('Pick a category', true); return; }
      if (!(limit > 0)) { showToast('Enter a limit above £0', true); return; }
      api('/budgets', { method: 'POST', body: JSON.stringify({ category: f.category, monthly_limit: limit }) })
        .then(() => load()).then(() => showToast('Budget added'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'edit-budget') {
      const row = btn.closest('.budget-item');
      const b = findBudget(btn.dataset.budgetCat);
      if (row && b) { row.classList.add('editing'); row.innerHTML = budgetEditInner(b); row.querySelector('[data-f="monthly_limit"]')?.focus(); }
      return;
    }
    if (action === 'save-budget-inline') {
      const row = btn.closest('.budget-item');
      const f = readInlineFields(row);
      const limit = parseFloat(f.monthly_limit);
      if (!(limit > 0)) { showToast('Enter a limit above £0', true); return; }
      api(`/budgets/${encodeURIComponent(btn.dataset.budgetCat)}`, { method: 'PATCH', body: JSON.stringify({ monthly_limit: limit }) })
        .then(() => load()).then(() => showToast('Budget updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-budget-inline') {
      const row = btn.closest('.budget-item');
      const b = findBudget(btn.dataset.budgetCat);
      if (row && b) { row.className = 'budget-item'; row.innerHTML = budgetRowInner(b); }
      return;
    }
    if (action === 'delete-budget') {
      if (!confirm(`Remove the ${btn.dataset.budgetCat} budget?`)) return;
      api(`/budgets/${encodeURIComponent(btn.dataset.budgetCat)}`, { method: 'DELETE' })
        .then(() => load()).then(() => showToast('Budget removed'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'add-savings') {
      btn.outerHTML = savingsAddInner();
      document.querySelector('#savings-add-form [data-f="name"]')?.focus();
      return;
    }
    if (action === 'save-savings-new') {
      const f = readInlineFields(document.getElementById('savings-add-form'));
      const target = parseFloat(f.target);
      if (!f.name || !f.name.trim()) { showToast('Goal needs a name', true); return; }
      if (!(target > 0)) { showToast('Enter a target above £0', true); return; }
      api('/savings-goals', {
        method: 'POST',
        body: JSON.stringify({ name: f.name.trim(), target, current: parseFloat(f.current) || 0, colour: f.colour }),
      }).then(() => load()).then(() => showToast('Savings goal added'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'edit-savings') {
      const row = btn.closest('.savings-card');
      const g = findSavings(btn.dataset.goalId);
      if (row && g) { row.classList.add('editing'); row.innerHTML = savingsEditInner(g); row.querySelector('[data-f="name"]')?.focus(); }
      return;
    }
    if (action === 'save-savings-inline') {
      const row = btn.closest('.savings-card');
      const f = readInlineFields(row);
      const target = parseFloat(f.target);
      if (!f.name || !f.name.trim()) { showToast('Goal needs a name', true); return; }
      if (!(target > 0)) { showToast('Enter a target above £0', true); return; }
      api(`/savings-goals/${btn.dataset.goalId}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: f.name.trim(), target, current: parseFloat(f.current) || 0, colour: f.colour }),
      }).then(() => load()).then(() => showToast('Savings goal updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-savings-inline') {
      const row = btn.closest('.savings-card');
      const g = findSavings(btn.dataset.goalId);
      if (row && g) { row.className = 'savings-card'; row.innerHTML = savingsRowInner(g); }
      return;
    }
    if (action === 'delete-savings' || action === 'delete-savings-inline') {
      if (!confirm('Delete this savings goal?')) return;
      api(`/savings-goals/${btn.dataset.goalId}`, { method: 'DELETE' })
        .then(() => load()).then(() => showToast('Savings goal deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-add-row') {
      load();
      return;
    }
    if (action === 'add-memory') {
      const host = document.getElementById('memory-content');
      if (host && !document.getElementById('memory-add-form')) {
        host.insertAdjacentHTML('afterbegin', memoryAddInner());
        document.querySelector('#memory-add-form [data-f="text"]')?.focus();
      }
      return;
    }
    if (action === 'scan-email-memory') {
      scanEmailMemory();
      return;
    }
    if (action === 'save-memory-new') {
      const f = readInlineFields(document.getElementById('memory-add-form'));
      if (!f.text || !f.text.trim()) { showToast('Type something to remember', true); return; }
      btn.disabled = true;
      api('/memory', {
        method: 'POST',
        body: JSON.stringify({ text: f.text.trim(), category: f.category, subject: f.subject, pinned: !!f.pinned }),
      }).then(() => load()).then(() => showToast('Added to memory'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-memory') {
      const row = btn.closest('.mem-fact');
      const f = findMemory(btn.dataset.memId);
      if (row && f) { row.classList.add('editing'); row.innerHTML = memoryEditInner(f); row.querySelector('[data-f="text"]')?.focus(); }
      return;
    }
    if (action === 'save-memory-inline') {
      const row = btn.closest('.mem-fact');
      const f = readInlineFields(row);
      if (!f.text || !f.text.trim()) { showToast('Memory text can’t be empty', true); return; }
      btn.disabled = true;
      api(`/memory/${btn.dataset.memId}`, {
        method: 'PATCH',
        body: JSON.stringify({ text: f.text.trim(), category: f.category, subject: f.subject, pinned: !!f.pinned }),
      }).then(() => load()).then(() => showToast('Memory updated'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'cancel-memory-inline') {
      const row = btn.closest('.mem-fact');
      const f = findMemory(btn.dataset.memId);
      if (row && f) { row.classList.remove('editing'); row.innerHTML = memoryFactInner(f); }
      return;
    }
    if (action === 'toggle-pin-memory') {
      const f = findMemory(btn.dataset.memId);
      api(`/memory/${btn.dataset.memId}`, { method: 'PATCH', body: JSON.stringify({ pinned: !(f && f.pinned) }) })
        .then(() => load()).then(() => showToast(f && f.pinned ? 'Unpinned' : 'Pinned — always considered'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'delete-memory') {
      if (!confirm('Forget this memory?')) return;
      api(`/memory/${btn.dataset.memId}`, { method: 'DELETE' })
        .then(() => load()).then(() => showToast('Forgotten'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'view-trip') {
      const tripId = btn.dataset.tripId;
      if (tripId) openTripDetailModal(tripId);
      return;
    }
    if (action === 'add-packing') {
      const tripId = btn.dataset.tripId;
      const template = btn.dataset.template;
      if (!tripId) return;
      if (!template) {
        openPackingTemplateModal(tripId);
        return;
      }
      api(`/holidays/trips/${tripId}/packing`, { method: 'POST', body: JSON.stringify({ template }) })
        .then(() => {
          closeModal();
          showToast('Packing list added');
          load();
        })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'toggle-checklist') {
      const tripId = btn.dataset.tripId;
      const itemId = btn.dataset.itemId;
      if (!tripId || !itemId) return;
      const box = btn.querySelector('.checklist-box');
      const flip = () => {
        btn.classList.toggle('done');
        if (box) box.textContent = btn.classList.contains('done') ? '✓' : '';
      };
      flip(); // optimistic — counters refresh on reload
      const body = { item_id: itemId };
      if (btn.dataset.itemType) body.item_type = btn.dataset.itemType; // packing rows are matched by label + type
      api(`/holidays/trips/${tripId}/checklist/toggle`, { method: 'POST', body: JSON.stringify(body) })
        .then(() => load())
        .catch((err) => {
          flip();
          showToast(err.message, true);
        });
      return;
    }
    if (action === 'link-trip-doc') {
      const tripId = btn.dataset.tripId;
      const docId = document.getElementById('trip-doc-select')?.value;
      if (tripId && docId) {
        api(`/holidays/trips/${tripId}/documents/${docId}`, { method: 'POST' })
          .then(() => {
            showToast('Document linked');
            openTripDetailModal(tripId);
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'unlink-trip-doc') {
      const tripId = btn.dataset.tripId;
      const docId = btn.dataset.docId;
      if (tripId && docId) {
        api(`/holidays/trips/${tripId}/documents/${docId}`, { method: 'DELETE' })
          .then(() => {
            showToast('Document unlinked');
            openTripDetailModal(tripId);
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }

    // --- Holidays: per-trip day-by-day itinerary ---
    if (action === 'toggle-itinerary') {
      const tripId = btn.dataset.tripId;
      const wrap = document.getElementById(`itin-wrap-${tripId}`);
      if (!wrap) return;
      const opening = wrap.hidden;
      wrap.hidden = !wrap.hidden;
      btn.classList.toggle('open', opening);
      if (opening && !wrap.dataset.loaded) loadItinerary(tripId);
      return;
    }
    if (action === 'add-itinerary') {
      const tripId = btn.dataset.tripId;
      const body = document.getElementById(`itin-body-${tripId}`);
      const slot = body?.querySelector('.itin-add-slot');
      if (slot && !slot.querySelector('.itin-add-form')) {
        slot.innerHTML = itinAddInner(tripId);
        slot.querySelector('[data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'cancel-itinerary-add') {
      btn.closest('.itin-add-form')?.remove();
      return;
    }
    if (action === 'save-itinerary-new') {
      const form = btn.closest('.itin-add-form');
      const f = readInlineFields(form);
      if (!f.title || !f.title.trim()) { showToast('Itinerary item needs a title', true); return; }
      const tripId = btn.dataset.tripId;
      btn.disabled = true;
      api('/itinerary', {
        method: 'POST',
        body: JSON.stringify({
          trip_id: tripId,
          title: f.title.trim(),
          kind: f.kind || 'other',
          day_date: f.day_date || null,
          start_time: f.start_time || null,
          location: (f.location || '').trim() || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadItinerary(tripId)).then(() => showToast('Itinerary item added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-itinerary') {
      const row = btn.closest('.itin-row');
      const it = findItin(btn.dataset.tripId, btn.dataset.itinId);
      if (row && it) { row.classList.add('editing'); row.innerHTML = itinEditInner(it); row.querySelector('[data-f="title"]')?.focus(); }
      return;
    }
    if (action === 'save-itinerary-inline') {
      const f = readInlineFields(btn.closest('.row-edit'));
      if (!f.title || !f.title.trim()) { showToast('Itinerary item needs a title', true); return; }
      const tripId = btn.dataset.tripId;
      api(`/itinerary/${btn.dataset.itinId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: f.title.trim(),
          kind: f.kind,
          day_date: f.day_date || null,
          start_time: f.start_time || null,
          location: (f.location || '').trim() || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadItinerary(tripId)).then(() => showToast('Itinerary updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-itinerary-inline') {
      const row = btn.closest('.itin-row');
      const it = findItin(btn.dataset.tripId, btn.dataset.itinId);
      if (row && it) { row.classList.remove('editing'); row.innerHTML = itinRowInner(it); }
      return;
    }
    if (action === 'delete-itinerary') {
      if (!confirm('Delete this itinerary item?')) return;
      const tripId = btn.dataset.tripId;
      api(`/itinerary/${btn.dataset.itinId}`, { method: 'DELETE' })
        .then(() => loadItinerary(tripId)).then(() => showToast('Itinerary item deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'scan-trip-email') {
      scanTripEmail(btn.dataset.tripId, btn);
      return;
    }
    if (action === 'cancel-trip-scan') {
      const slot = tripScanSlot(btn.dataset.tripId);
      if (slot) slot.innerHTML = '';
      return;
    }
    if (action === 'import-scanned-itinerary') {
      const tripId = btn.dataset.tripId;
      const slot = tripScanSlot(tripId);
      const cands = store.tripScanCands?.[tripId] || [];
      const items = [...(slot?.querySelectorAll('.scan-cand-cb') || [])]
        .filter((cb) => cb.checked)
        .map((cb) => cands[parseInt(cb.dataset.idx, 10)])
        .filter(Boolean);
      if (!items.length) { showToast('Tick at least one booking to add', true); return; }
      btn.disabled = true;
      api(`/trips/${encodeURIComponent(tripId)}/itinerary/import`, {
        method: 'POST',
        body: JSON.stringify({ items }),
      }).then((r) => {
        if (slot) slot.innerHTML = '';
        return loadItinerary(tripId).then(() => showToast(`Added ${r.added ?? items.length} to your itinerary.`));
      }).catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }

    if (action === 'maintenance-done') {
      const maintId = btn.dataset.maintId;
      if (maintId) {
        api(`/maintenance/${maintId}/done`, { method: 'POST' })
          .then(() => {
            showToast('Maintenance marked done');
            load();
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'edit-maintenance') {
      const row = btn.closest('.maintenance-row');
      const m = findMaintenance(btn.dataset.maintId);
      if (row && m) {
        row.classList.add('editing');
        row.innerHTML = maintEditInner(m);
        row.querySelector('[data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'save-maintenance-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Item needs a title', true); return; }
      api(`/maintenance/${btn.dataset.maintId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: f.title.trim(),
          category: f.category,
          next_due_date: f.next_due_date || '',
          interval_months: parseInt(f.interval_months, 10) || 0,
          vendor: f.vendor || '',
          notes: f.notes || '',
        }),
      }).then(() => load()).then(() => showToast('Maintenance item updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-maintenance-inline') {
      const row = btn.closest('.maintenance-row');
      const m = findMaintenance(btn.dataset.maintId);
      if (row && m) {
        row.classList.remove('editing');
        row.innerHTML = maintRowInner(m);
      }
      return;
    }
    if (action === 'delete-maintenance-inline') {
      if (!confirm('Delete this maintenance item?')) return;
      api(`/maintenance/${btn.dataset.maintId}`, { method: 'DELETE' })
        .then(() => load()).then(() => showToast('Maintenance item deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'add-tradesperson') {
      const host = document.getElementById('tradespeople-list');
      if (host && !document.getElementById('tradesperson-add-form')) {
        host.insertAdjacentHTML('afterbegin', tradespersonAddInner());
        document.querySelector('#tradesperson-add-form [data-f="name"]')?.focus();
      }
      return;
    }
    if (action === 'save-tradesperson-new') {
      const f = readInlineFields(document.getElementById('tradesperson-add-form'));
      if (!f.name || !f.name.trim()) { showToast('Contact needs a name', true); return; }
      btn.disabled = true;
      api('/tradespeople', {
        method: 'POST',
        body: JSON.stringify({
          name: f.name.trim(),
          trade: (f.trade || '').trim() || null,
          phone: (f.phone || '').trim() || null,
          email: (f.email || '').trim() || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => load()).then(() => showToast('Contact added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-tradesperson') {
      const row = btn.closest('.maintenance-row');
      const t = findTradesperson(btn.dataset.tradeId);
      if (row && t) {
        row.classList.add('editing');
        row.innerHTML = tradespersonEditInner(t);
        row.querySelector('[data-f="name"]')?.focus();
      }
      return;
    }
    if (action === 'save-tradesperson-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.name || !f.name.trim()) { showToast('Contact needs a name', true); return; }
      api(`/tradespeople/${btn.dataset.tradeId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: f.name.trim(),
          trade: (f.trade || '').trim() || null,
          phone: (f.phone || '').trim() || null,
          email: (f.email || '').trim() || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => load()).then(() => showToast('Contact updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-tradesperson-inline') {
      const row = btn.closest('.maintenance-row');
      const t = findTradesperson(btn.dataset.tradeId);
      if (row && t) {
        row.classList.remove('editing');
        row.innerHTML = tradespersonRowInner(t);
      }
      return;
    }
    if (action === 'delete-tradesperson') {
      if (!confirm('Delete this contact?')) return;
      api(`/tradespeople/${btn.dataset.tradeId}`, { method: 'DELETE' })
        .then(() => load()).then(() => showToast('Contact deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'add-chore') {
      const host = document.getElementById('chores-list');
      if (host && !document.getElementById('chore-add-form')) {
        host.insertAdjacentHTML('afterbegin', choreAddInner());
        document.querySelector('#chore-add-form [data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'save-chore-new') {
      const f = readInlineFields(document.getElementById('chore-add-form'));
      if (!f.title || !f.title.trim()) { showToast('Chore needs a title', true); return; }
      btn.disabled = true;
      api('/chores', {
        method: 'POST',
        body: JSON.stringify({
          title: f.title.trim(),
          cadence: f.cadence || 'weekly',
          assignee_id: f.assignee_id || null,
          rotate: !!f.rotate,
          next_due: f.next_due || null,
        }),
      }).then(() => loadChores()).then(() => showToast('Chore added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-chore') {
      const row = btn.closest('.maintenance-row');
      const c = findChore(btn.dataset.choreId);
      if (row && c) {
        row.classList.add('editing');
        row.innerHTML = choreEditInner(c);
        row.querySelector('[data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'save-chore-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Chore needs a title', true); return; }
      api(`/chores/${btn.dataset.choreId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: f.title.trim(),
          cadence: f.cadence,
          assignee_id: f.assignee_id || null,
          rotate: !!f.rotate,
          next_due: f.next_due || null,
        }),
      }).then(() => loadChores()).then(() => showToast('Chore updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-chore-inline') {
      const row = btn.closest('.maintenance-row');
      const c = findChore(btn.dataset.choreId);
      if (row && c) {
        row.classList.remove('editing');
        row.innerHTML = choreRowInner(c);
      }
      return;
    }
    if (action === 'delete-chore') {
      if (!confirm('Delete this chore?')) return;
      api(`/chores/${btn.dataset.choreId}`, { method: 'DELETE' })
        .then(() => loadChores()).then(() => showToast('Chore deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'chore-done') {
      const choreId = btn.dataset.choreId;
      if (!choreId) return;
      btn.disabled = true;
      api(`/chores/${choreId}/done`, { method: 'POST' })
        .then((res) => {
          const next = res?.chore?.assignee_name;
          loadChores();
          showToast(next ? `Done — ${next}'s turn next` : 'Chore done ✓');
        })
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    // --- Recipe book (Home) ---
    if (action === 'add-recipe') {
      const host = document.getElementById('recipes-list');
      if (host && !document.getElementById('recipe-add-form')) {
        host.insertAdjacentHTML('afterbegin', recipeAddInner());
        document.querySelector('#recipe-add-form [data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'save-recipe-new') {
      const f = readInlineFields(document.getElementById('recipe-add-form'));
      if (!f.title || !f.title.trim()) { showToast('Recipe needs a title', true); return; }
      btn.disabled = true;
      api('/recipes', { method: 'POST', body: JSON.stringify(recipePayload(f)) })
        .then(() => loadRecipes()).then(() => showToast('Recipe saved'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-recipe') {
      const row = btn.closest('.maintenance-row');
      const r = findRecipe(btn.dataset.recipeId);
      if (row && r) { row.classList.add('editing'); row.innerHTML = recipeEditInner(r); row.querySelector('[data-f="title"]')?.focus(); }
      return;
    }
    if (action === 'save-recipe-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Recipe needs a title', true); return; }
      api(`/recipes/${btn.dataset.recipeId}`, { method: 'PATCH', body: JSON.stringify(recipePayload(f)) })
        .then(() => loadRecipes()).then(() => showToast('Recipe updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-recipe-inline') {
      const row = btn.closest('.maintenance-row');
      const r = findRecipe(btn.dataset.recipeId);
      if (row && r) { row.classList.remove('editing'); row.innerHTML = recipeRowInner(r); }
      return;
    }
    if (action === 'delete-recipe') {
      if (!confirm('Delete this recipe?')) return;
      api(`/recipes/${btn.dataset.recipeId}`, { method: 'DELETE' })
        .then(() => loadRecipes()).then(() => showToast('Recipe deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'recipe-plan-toggle') {
      const row = btn.closest('.maintenance-row');
      const bar = row?.querySelector('.recipe-plan-bar');
      if (bar) {
        bar.hidden = !bar.hidden;
        if (!bar.hidden) bar.querySelector('.recipe-plan-date')?.focus();
      }
      return;
    }
    if (action === 'recipe-plan-cancel') {
      const bar = btn.closest('.recipe-plan-bar');
      if (bar) bar.hidden = true;
      return;
    }
    if (action === 'recipe-plan-confirm') {
      const bar = btn.closest('.recipe-plan-bar');
      const date = bar?.querySelector('.recipe-plan-date')?.value;
      if (!date) { showToast('Pick a date', true); return; }
      const r = findRecipe(btn.dataset.recipeId);
      btn.disabled = true;
      api(`/recipes/${btn.dataset.recipeId}/plan`, { method: 'POST', body: JSON.stringify({ date }) })
        .then(() => {
          showToast(`Planned ${r ? r.title : 'recipe'} for ${fmtShortDate(date, true)}`);
          if (bar) bar.hidden = true;
          btn.disabled = false;
          if (typeof loadMeals === 'function') loadMeals(); // refresh the meal planner card
        })
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }

    // --- Little ones: dependents (Home care) ---
    if (action === 'add-dependent') {
      const host = document.getElementById('dependents-list');
      if (host && !document.getElementById('dependent-add-form')) {
        host.insertAdjacentHTML('afterbegin', dependentAddInner());
        document.querySelector('#dependent-add-form [data-f="name"]')?.focus();
      }
      return;
    }
    if (action === 'save-dependent-new') {
      const f = readInlineFields(document.getElementById('dependent-add-form'));
      if (!f.name || !f.name.trim()) { showToast('Give them a name', true); return; }
      btn.disabled = true;
      api('/dependents', { method: 'POST', body: JSON.stringify(dependentPayload(f)) })
        .then(() => loadDependents()).then(() => showToast('Added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-dependent') {
      const panel = btn.closest('.dependent-panel');
      const d = findDependent(btn.dataset.dependentId);
      if (panel && d) { panel.outerHTML = dependentEditInner(d); document.querySelector(`.dependent-panel.editing[data-dependent-id="${d.id}"] [data-f="name"]`)?.focus(); }
      return;
    }
    if (action === 'save-dependent-inline') {
      const panel = btn.closest('.dependent-panel');
      const f = readInlineFields(panel);
      if (!f.name || !f.name.trim()) { showToast('Give them a name', true); return; }
      api(`/dependents/${btn.dataset.dependentId}`, { method: 'PATCH', body: JSON.stringify(dependentPayload(f)) })
        .then(() => loadDependents()).then(() => showToast('Updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-dependent-inline') {
      renderDependents(store.dependents);
      return;
    }
    if (action === 'delete-dependent') {
      if (!confirm('Delete this dependent? This also removes their care records.')) return;
      api(`/dependents/${btn.dataset.dependentId}`, { method: 'DELETE' })
        .then(() => loadDependents()).then(() => showToast('Removed'))
        .catch((err) => showToast(err.message, true));
      return;
    }

    // --- Little ones: care items ---
    if (action === 'add-care') {
      const depId = btn.dataset.dependentId;
      const list = document.getElementById(`care-list-${depId}`);
      if (list && !list.querySelector('.care-add-form')) {
        list.insertAdjacentHTML('afterbegin', careAddInner(depId));
        list.querySelector('.care-add-form [data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'cancel-care-add') {
      btn.closest('.care-add-form')?.remove();
      return;
    }
    if (action === 'save-care-new') {
      const form = btn.closest('.care-add-form');
      const f = readInlineFields(form);
      if (!f.title || !f.title.trim()) { showToast('Care item needs a title', true); return; }
      btn.disabled = true;
      api('/care', {
        method: 'POST',
        body: JSON.stringify({
          dependent_id: btn.dataset.dependentId,
          title: f.title.trim(),
          category: f.category || 'other',
          due_date: f.due_date || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadDependents()).then(() => showToast('Care item added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-care') {
      const row = btn.closest('.care-row');
      const it = findCare(btn.dataset.careId);
      if (row && it) { row.classList.add('editing'); row.innerHTML = careEditInner(it); row.querySelector('[data-f="title"]')?.focus(); }
      return;
    }
    if (action === 'save-care-inline') {
      const row = btn.closest('.care-row');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Care item needs a title', true); return; }
      api(`/care/${btn.dataset.careId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: f.title.trim(),
          category: f.category,
          due_date: f.due_date || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadDependents()).then(() => showToast('Care item updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-care-inline') {
      const row = btn.closest('.care-row');
      const it = findCare(btn.dataset.careId);
      if (row && it) { row.className = `care-row${it.done ? ' done' : ''}`; row.innerHTML = careRowInner(it); }
      return;
    }
    if (action === 'delete-care') {
      if (!confirm('Delete this care item?')) return;
      api(`/care/${btn.dataset.careId}`, { method: 'DELETE' })
        .then(() => loadDependents()).then(() => showToast('Care item deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'care-done') {
      const careId = btn.dataset.careId;
      if (!careId) return;
      btn.disabled = true;
      api(`/care/${careId}/done`, { method: 'POST' })
        .then(() => loadDependents()).then(() => showToast('Marked done ✓'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }

    if (action === 'scan-receipt') {
      document.getElementById('receipt-file-input')?.click();
      return;
    }
    if (action === 'scan-email') {
      scanEmailReceipts();
      return;
    }
    if (action === 'scan-inbox') {
      scanInbox();
      return;
    }
    if (action === 'enable-push') {
      enablePush();
      return;
    }
    if (action === 'disable-push') {
      disablePush();
      return;
    }
    if (action === 'push-test') {
      sendPushTest();
      return;
    }
    if (action === 'send-reminders') {
      api('/notifications/send-reminders', { method: 'POST' })
        .then((r) => {
          if (r.error) showToast(r.error, true);
          else if (r.sent) showToast(`Sent reminder for ${r.count} item(s)`);
          else showToast(r.reason || 'No reminders sent');
        })
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'sign-out') {
      api('/auth/logout', { method: 'POST' })
        .catch(() => {}) // clear locally even if the server call fails
        .then(() => {
          currentUser = null;
          store = {};
          closeModal();
          closeNotif();
          showToast('Signed out');
          showLogin();
        });
      return;
    }
    if (action === 'whatsapp-test') {
      showToast('Sending test digest…');
      api('/whatsapp/test-digest', { method: 'POST' })
        .then((r) => showToast(`Digest sent to ${r.sent_to}`))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'assistant-confirm') {
      const actionId = btn.dataset.actionId;
      if (actionId) {
        api(`/assistant/confirm/${actionId}`, { method: 'POST' })
          .then((r) => {
            showToast(r.summary || 'Confirmed');
            assistantPendingConfirm = null;
            load();
          })
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    if (action === 'save-idea') {
      const ideaId = btn.dataset.ideaId;
      if (ideaId) {
        api(`/holidays/ideas/${ideaId}/toggle`, { method: 'POST' })
          .then(() => load())
          .catch((err) => showToast(err.message, true));
      }
      return;
    }

    // --- Shopping list (home) ---
    if (action === 'add-shopping') { addShoppingItem(); return; }
    if (action === 'delete-shopping') { deleteShoppingItem(btn.dataset.shopId); return; }
    if (action === 'clear-done-shopping') { clearDoneShopping(); return; }

    // --- Proactive inbox suggestions (home) ---
    if (action === 'scan-suggestions') { scanInboxSuggestions(btn); return; }
    if (action === 'accept-suggestion') { acceptSuggestion(btn.dataset.sugId, btn.dataset.kind, btn); return; }
    if (action === 'dismiss-suggestion') { dismissSuggestion(btn.dataset.sugId, btn); return; }

    // --- Weekly meal planner (home) — inline edit, own refresh ---
    if (action === 'edit-meal') {
      const row = btn.closest('.meal-row');
      if (!row || row.querySelector('.row-edit')) return; // already editing
      const date = row.dataset.date;
      const meal = (mealsData?.meals || []).find((m) => m.date === date) || { date, title: '', ingredients: '' };
      row.classList.add('editing');
      row.innerHTML = mealEditInner(meal);
      row.querySelector('[data-f="title"]')?.focus();
      return;
    }
    if (action === 'save-meal-inline') {
      const row = btn.closest('.meal-row');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Give the meal a name', true); return; }
      btn.disabled = true;
      api('/meals', {
        method: 'PUT',
        body: JSON.stringify({ date: btn.dataset.date, title: f.title.trim(), ingredients: (f.ingredients || '').trim() }),
      }).then(() => loadMeals()).then(() => showToast('Meal saved'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'cancel-meal-inline') {
      if (mealsData) renderMeals(mealsData); else loadMeals();
      return;
    }
    if (action === 'delete-meal-inline') {
      api(`/meals/${btn.dataset.date}`, { method: 'DELETE' })
        .then(() => loadMeals()).then(() => showToast('Meal cleared'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'meal-to-shopping') {
      btn.disabled = true;
      api(`/meals/${btn.dataset.date}/to-shopping`, { method: 'POST' })
        .then((r) => {
          const n = (r && r.added ? r.added.length : 0);
          showToast(n ? `Added ${n} item${n === 1 ? '' : 's'} to the shopping list` : 'No ingredients to add');
          loadShopping(); // reflect the new items on the shopping card
        })
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }

    // --- Assets (finances net worth) — inline CRUD, refresh headline + list together ---
    if (action === 'add-asset') {
      const host = document.getElementById('assets-list');
      if (host && !document.getElementById('asset-add-form')) {
        host.insertAdjacentHTML('afterbegin', assetAddInner());
        document.querySelector('#asset-add-form [data-f="name"]')?.focus();
      }
      return;
    }
    if (action === 'save-asset-new') {
      const f = readInlineFields(document.getElementById('asset-add-form'));
      if (!f.name || !f.name.trim()) { showToast('Asset needs a name', true); return; }
      btn.disabled = true;
      api('/assets', {
        method: 'POST',
        body: JSON.stringify({
          name: f.name.trim(),
          type: f.type || 'other',
          value: parseFloat(f.value) || 0,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadNetWorth()).then(() => showToast('Asset added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-asset') {
      const row = btn.closest('.maintenance-row');
      const a = findAsset(btn.dataset.assetId);
      if (row && a) { row.classList.add('editing'); row.innerHTML = assetEditInner(a); row.querySelector('[data-f="name"]')?.focus(); }
      return;
    }
    if (action === 'save-asset-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.name || !f.name.trim()) { showToast('Asset needs a name', true); return; }
      api(`/assets/${btn.dataset.assetId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: f.name.trim(),
          type: f.type || 'other',
          value: parseFloat(f.value) || 0,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadNetWorth()).then(() => showToast('Asset updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-asset-inline') {
      const row = btn.closest('.maintenance-row');
      const a = findAsset(btn.dataset.assetId);
      if (row && a) { row.classList.remove('editing'); row.innerHTML = assetRowInner(a); }
      return;
    }
    if (action === 'delete-asset') {
      if (!confirm('Delete this asset?')) return;
      api(`/assets/${btn.dataset.assetId}`, { method: 'DELETE' })
        .then(() => loadNetWorth()).then(() => showToast('Asset deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }

    // --- Occasions (home card) -----------------------------------------------
    if (action === 'add-occasion') {
      const host = document.getElementById('occasions-list');
      if (host && !document.getElementById('occasion-add-form')) {
        host.insertAdjacentHTML('afterbegin', occasionAddInner());
        document.querySelector('#occasion-add-form [data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'save-occasion-new') {
      const f = readInlineFields(document.getElementById('occasion-add-form'));
      if (!f.title || !f.title.trim()) { showToast('Occasion needs a title', true); return; }
      if (!f.date) { showToast('Pick a date', true); return; }
      btn.disabled = true;
      api('/occasions', {
        method: 'POST',
        body: JSON.stringify({
          title: f.title.trim(),
          kind: f.kind || 'birthday',
          date: f.date,
          person: (f.person || '').trim() || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadOccasions()).then(() => showToast('Occasion added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-occasion') {
      const row = btn.closest('.maintenance-row');
      const o = findOccasion(btn.dataset.occasionId);
      if (row && o) { row.classList.add('editing'); row.innerHTML = occasionEditInner(o); row.querySelector('[data-f="title"]')?.focus(); }
      return;
    }
    if (action === 'save-occasion-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Occasion needs a title', true); return; }
      if (!f.date) { showToast('Pick a date', true); return; }
      api(`/occasions/${btn.dataset.occasionId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: f.title.trim(),
          kind: f.kind,
          date: f.date,
          person: (f.person || '').trim() || null,
          notes: (f.notes || '').trim() || null,
        }),
      }).then(() => loadOccasions()).then(() => showToast('Occasion updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-occasion-inline') {
      const row = btn.closest('.maintenance-row');
      const o = findOccasion(btn.dataset.occasionId);
      if (row && o) { row.classList.remove('editing'); row.innerHTML = occasionRowInner(o); }
      return;
    }
    if (action === 'delete-occasion') {
      if (!confirm('Delete this occasion?')) return;
      api(`/occasions/${btn.dataset.occasionId}`, { method: 'DELETE' })
        .then(() => loadOccasions()).then(() => showToast('Occasion deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }

    // --- Home inventory (home care card) -------------------------------------
    if (action === 'add-inventory') {
      const host = document.getElementById('inventory-list');
      if (host && !document.getElementById('inventory-add-form')) {
        host.insertAdjacentHTML('afterbegin', inventoryAddInner());
        document.querySelector('#inventory-add-form [data-f="name"]')?.focus();
      }
      return;
    }
    if (action === 'save-inventory-new') {
      const f = readInlineFields(document.getElementById('inventory-add-form'));
      if (!f.name || !f.name.trim()) { showToast('Item needs a name', true); return; }
      btn.disabled = true;
      api('/inventory', {
        method: 'POST',
        body: JSON.stringify(inventoryPayload(f)),
      }).then(() => loadInventory()).then(() => showToast('Item added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-inventory') {
      const row = btn.closest('.maintenance-row');
      const it = findInventory(btn.dataset.invId);
      if (row && it) { row.classList.add('editing'); row.innerHTML = inventoryEditInner(it); row.querySelector('[data-f="name"]')?.focus(); }
      return;
    }
    if (action === 'save-inventory-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.name || !f.name.trim()) { showToast('Item needs a name', true); return; }
      api(`/inventory/${btn.dataset.invId}`, {
        method: 'PATCH',
        body: JSON.stringify(inventoryPayload(f)),
      }).then(() => loadInventory()).then(() => showToast('Item updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-inventory-inline') {
      const row = btn.closest('.maintenance-row');
      const it = findInventory(btn.dataset.invId);
      if (row && it) { row.classList.remove('editing'); row.innerHTML = inventoryRowInner(it); }
      return;
    }
    if (action === 'delete-inventory') {
      if (!confirm('Delete this item?')) return;
      api(`/inventory/${btn.dataset.invId}`, { method: 'DELETE' })
        .then(() => loadInventory()).then(() => showToast('Item deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }

    // --- Vehicles (home care card) -------------------------------------------
    if (action === 'add-vehicle') {
      const host = document.getElementById('vehicles-list');
      if (host && !document.getElementById('vehicle-add-form')) {
        host.insertAdjacentHTML('afterbegin', vehicleAddInner());
        document.querySelector('#vehicle-add-form [data-f="name"]')?.focus();
      }
      return;
    }
    if (action === 'save-vehicle-new') {
      const f = readInlineFields(document.getElementById('vehicle-add-form'));
      if (!f.name || !f.name.trim()) { showToast('Vehicle needs a name', true); return; }
      btn.disabled = true;
      api('/vehicles', {
        method: 'POST',
        body: JSON.stringify(vehiclePayload(f)),
      }).then(() => loadVehicles()).then(() => showToast('Vehicle added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-vehicle') {
      const row = btn.closest('.maintenance-row');
      const v = findVehicle(btn.dataset.vehId);
      if (row && v) { row.classList.add('editing'); row.innerHTML = vehicleEditInner(v); row.querySelector('[data-f="name"]')?.focus(); }
      return;
    }
    if (action === 'save-vehicle-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.name || !f.name.trim()) { showToast('Vehicle needs a name', true); return; }
      api(`/vehicles/${btn.dataset.vehId}`, {
        method: 'PATCH',
        body: JSON.stringify(vehiclePayload(f)),
      }).then(() => loadVehicles()).then(() => showToast('Vehicle updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-vehicle-inline') {
      const row = btn.closest('.maintenance-row');
      const v = findVehicle(btn.dataset.vehId);
      if (row && v) { row.classList.remove('editing'); row.innerHTML = vehicleRowInner(v); }
      return;
    }
    if (action === 'delete-vehicle') {
      if (!confirm('Delete this vehicle?')) return;
      api(`/vehicles/${btn.dataset.vehId}`, { method: 'DELETE' })
        .then(() => loadVehicles()).then(() => showToast('Vehicle deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    // DVLA reg lookup — shared by both the add + edit forms (both use .row-edit).
    // Reads the form's reg, POSTs /vehicles/lookup, then fills make / mot_due /
    // tax_due. Never crashes on an unexpected response shape.
    if (action === 'lookup-vehicle') {
      const root = btn.closest('.row-edit');
      if (!root) return;
      const reg = (root.querySelector('[data-f="reg"]')?.value || '').trim();
      if (!reg) { showToast('Enter a registration first'); return; }
      btn.disabled = true;
      api('/vehicles/lookup', { method: 'POST', body: JSON.stringify({ reg }) })
        .then((res) => {
          res = res || {};
          if (res.configured === false) { showToast(res.message || 'Reg lookup needs a DVLA key'); return; }
          if (res.error) { showToast(res.error); return; }
          if (res.make == null && res.mot_due == null && res.tax_due == null) {
            showToast('Vehicle not found for that reg');
            return;
          }
          const setField = (name, val, isDate) => {
            const el = root.querySelector(`[data-f="${name}"]`);
            if (!el || val == null || val === '') return;
            el.value = isDate ? String(val).slice(0, 10) : String(val);
          };
          setField('make', res.make, false);
          setField('mot_due', res.mot_due, true);
          setField('tax_due', res.tax_due, true);
          showToast('Filled from DVLA');
        })
        .catch((err) => {
          const msg = (err && err.message) || '';
          if (/not found/i.test(msg) || /404/.test(msg)) showToast('Vehicle not found for that reg');
          else showToast(msg || 'Reg lookup failed', true);
        })
        .finally(() => { btn.disabled = false; });
      return;
    }

    // --- Gift ideas / wishlists (home card) ----------------------------------
    if (action === 'add-wishlist') {
      const host = document.getElementById('wishlist-list');
      if (host && !document.getElementById('wishlist-add-form')) {
        host.insertAdjacentHTML('afterbegin', wishlistAddInner());
        document.querySelector('#wishlist-add-form [data-f="title"]')?.focus();
      }
      return;
    }
    if (action === 'save-wishlist-new') {
      const f = readInlineFields(document.getElementById('wishlist-add-form'));
      if (!f.title || !f.title.trim()) { showToast('Gift idea needs a title', true); return; }
      btn.disabled = true;
      api('/wishlist', {
        method: 'POST',
        body: JSON.stringify(wishlistPayload(f)),
      }).then(() => loadWishlist()).then(() => showToast('Gift idea added'))
        .catch((err) => { showToast(err.message, true); btn.disabled = false; });
      return;
    }
    if (action === 'edit-wishlist') {
      const row = btn.closest('.maintenance-row');
      const w = findWishlist(btn.dataset.wishId);
      if (row && w) { row.classList.add('editing'); row.innerHTML = wishlistEditInner(w); row.querySelector('[data-f="title"]')?.focus(); }
      return;
    }
    if (action === 'save-wishlist-inline') {
      const row = btn.closest('.maintenance-row');
      const f = readInlineFields(row);
      if (!f.title || !f.title.trim()) { showToast('Gift idea needs a title', true); return; }
      api(`/wishlist/${btn.dataset.wishId}`, {
        method: 'PATCH',
        body: JSON.stringify(wishlistPayload(f)),
      }).then(() => loadWishlist()).then(() => showToast('Gift idea updated'))
        .catch((err) => showToast(err.message, true));
      return;
    }
    if (action === 'cancel-wishlist-inline') {
      const row = btn.closest('.maintenance-row');
      const w = findWishlist(btn.dataset.wishId);
      if (row && w) { row.classList.remove('editing'); row.innerHTML = wishlistRowInner(w); }
      return;
    }
    if (action === 'delete-wishlist') {
      if (!confirm('Delete this gift idea?')) return;
      api(`/wishlist/${btn.dataset.wishId}`, { method: 'DELETE' })
        .then(() => loadWishlist()).then(() => showToast('Gift idea deleted'))
        .catch((err) => showToast(err.message, true));
      return;
    }

    showToast(`“${action.replace(/-/g, ' ')}” isn’t available yet`);
  });

  document.querySelectorAll('input[name="appt-filter"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      const cat = document.querySelector('#appt-categories .cat-btn.active')?.dataset.apptCat || 'all';
      renderAppointments(store.appointments, radio.value, cat);
    });
  });

  // Recategorise a transaction (and learn the merchant) when its dropdown changes
  document.addEventListener('change', (e) => {
    // Notification preference toggles / lead-days — PATCH immediately.
    const prefEl = e.target.closest('[data-pref]');
    if (prefEl) {
      handleNotifPrefChange(prefEl);
      return;
    }

    // Shopping list — tick/untick an item.
    const shopCb = e.target.closest('.shopping-check');
    if (shopCb) {
      toggleShoppingItem(shopCb.dataset.shopId, shopCb.checked);
      return;
    }

    // Gift ideas — tick/untick the "Bought" toggle.
    const wishCb = e.target.closest('.wishlist-check');
    if (wishCb) {
      toggleWishlistPurchased(wishCb.dataset.wishId, wishCb.checked);
      return;
    }

    // Calendar member-filter chips
    const filterCb = e.target.closest('#cal-filters input[type="checkbox"][data-user-id]');
    if (filterCb) {
      if (filterCb.checked) calFilterHidden.delete(filterCb.dataset.userId);
      else calFilterHidden.add(filterCb.dataset.userId);
      if (store.calendar) renderCalendar(store.calendar);
      return;
    }

    // Transactions — tag "who spent" (Luke / Laura / Joint / — for untagged).
    const personSel = e.target.closest('[data-role="txn-person"]');
    if (personSel && personSel.dataset.txnId) {
      api(`/transactions/${personSel.dataset.txnId}/person`, {
        method: 'PATCH',
        body: JSON.stringify({ person: personSel.value || null }),
      })
        .then(() => {
          showToast('Updated who spent');
          loadByPerson();  // refresh the by-person breakdown to reflect the change
        })
        .catch((err) => showToast(err.message, true));
      return;
    }

    const sel = e.target.closest('.txn-cat');
    if (!sel || !sel.dataset.txnId) return;
    api(`/transactions/${sel.dataset.txnId}`, {
      method: 'PATCH',
      body: JSON.stringify({ category: sel.value, learn: true }),
    })
      .then((r) => {
        showToast(r.reclassified > 1 ? `Learned — ${r.reclassified} matching txns updated` : 'Category updated');
        load();
      })
      .catch((err) => showToast(err.message, true));
  });

  document.getElementById('notif-btn').onclick = () => {
    document.getElementById('notif-panel').hidden = false;
    document.getElementById('notif-backdrop').hidden = false;
    // Remember what was seen so the badge stays hidden until the reminders change.
    try {
      localStorage.setItem(NOTIF_SEEN_KEY, reminderFingerprint(store.dashboard?.reminders || []));
    } catch {
      /* storage unavailable — badge keeps its old behaviour */
    }
    document.getElementById('notif-badge').hidden = true;
    updateAppBadge(0);  // viewing the alerts clears the home-screen icon badge
  };
  document.getElementById('notif-close').onclick = closeNotif;
  document.getElementById('notif-backdrop').onclick = closeNotif;

  document.getElementById('weather-btn').onclick = openWeather;
  document.getElementById('weather-close').onclick = closeWeather;
  document.getElementById('weather-backdrop').onclick = closeWeather;

  document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
  updateThemeToggleIcon(); // reflect the current theme now the button is wired

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModal();
      closeNotif();
      closeWeather();
      closeLoginPreview();
    }
  });

  // Enter in the shopping-list input adds the item.
  document.getElementById('shopping-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); addShoppingItem(); }
  });

  document.getElementById('login-close')?.addEventListener('click', closeLoginPreview);
  document.getElementById('login-form')?.addEventListener('submit', (e) => {
    e.preventDefault();
    document.getElementById('login-demo')?.click();
  });
  document.getElementById('login-demo')?.addEventListener('click', async () => {
    const email = document.querySelector('#login-overlay input[type="email"]')?.value;
    const password = document.querySelector('#login-overlay input[type="password"]')?.value;
    try {
      const data = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      currentUser = data.user;
      hideLogin();
      showToast(`Welcome, ${currentUser.name}`);
      await load();
    } catch (err) {
      showToast(err.message || 'Login failed', true);
    }
  });

  document.getElementById('csv-file-input')?.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await uploadCsv(file);
      showToast(`Imported ${res.imported} transactions`);
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
    e.target.value = '';
  });

  document.getElementById('vault-upload-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const fileInput = form.querySelector('input[name="file"]');
    const file = fileInput?.files?.[0];
    if (!file) {
      showToast('Choose a file to upload', true);
      return;
    }
    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', form.name.value.trim());
    formData.append('category', form.category.value);
    formData.append('expiry', form.expiry.value);
    if (form.expiry.value) formData.append('expiry_date', form.expiry.value);
    formData.append('notes', form.notes.value.trim());
    try {
      showToast('Uploading…');
      const res = await fetch(`${API}/documents/upload`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Upload failed');
      }
      form.reset();
      showToast('Document uploaded');
      switchTab('documents');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Frictionless Photos upload: the button opens the hidden multi-file picker,
  // and selecting files uploads them immediately (no title/caption/trip prompts).
  const mediaUploadBtn = document.getElementById('media-upload-btn');
  const mediaFileInput = document.getElementById('media-file-input');
  if (mediaUploadBtn && mediaFileInput) {
    mediaUploadBtn.addEventListener('click', () => mediaFileInput.click());
    mediaFileInput.addEventListener('change', async () => {
      const files = mediaFileInput.files;
      if (files && files.length) await handleMediaFiles(files);
      mediaFileInput.value = ''; // allow re-picking the same file(s)
    });
  }

  document.getElementById('maintenance-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const body = {
      title: form.title.value.trim(),
      category: form.category.value,
      next_due_date: form.next_due_date.value,
      interval_months: parseInt(form.interval_months.value, 10) || 12,
      vendor: form.vendor.value.trim(),
      notes: form.notes.value.trim(),
    };
    try {
      await api('/maintenance', { method: 'POST', body: JSON.stringify(body) });
      form.reset();
      showToast('Maintenance item added');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById('receipt-file-input')?.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('account', 'joint');
    try {
      showToast('Scanning receipt…');
      const res = await fetch(`${API}/finances/scan-receipt`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Scan failed');
      }
      const data = await res.json();
      showToast(`Logged: ${data.transaction?.description || 'transaction'}`);
      switchTab('finances');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
    e.target.value = '';
  });
}

function closeNotif() {
  document.getElementById('notif-panel').hidden = true;
  document.getElementById('notif-backdrop').hidden = true;
}

let weatherData = null;

async function loadWeather() {
  try {
    weatherData = await api('/weather?days=7');
  } catch (err) {
    weatherData = null;
  }
  const iconEl = document.getElementById('weather-btn-icon');
  const tempEl = document.getElementById('weather-btn-temp');
  const cur = (weatherData && weatherData.configured && weatherData.current) || {};
  if (iconEl) iconEl.textContent = cur.emoji || '🌡️';
  if (tempEl) tempEl.textContent = cur.temp != null ? `${cur.temp}°` : '';
}

function renderWeatherPanel() {
  const title = document.getElementById('weather-panel-title');
  const body = document.getElementById('weather-panel-body');
  if (!body) return;
  if (!weatherData || !weatherData.configured) {
    if (title) title.textContent = 'Weather';
    body.innerHTML = '<div class="wx-empty">Weather isn’t set up yet — add WEATHER_LATITUDE and WEATHER_LONGITUDE to the server .env.</div>';
    return;
  }
  const d = weatherData;
  const badge = d.holiday
    ? '<span class="wx-loc-badge holiday">Holiday</span>'
    : '<span class="wx-loc-badge">Home</span>';
  if (title) title.innerHTML = `${esc(d.label || 'Weather')} ${badge}`;
  const cur = d.current || {};
  const curHtml = `
    <div class="wx-current">
      <span class="wx-current-emoji">${cur.emoji || '🌡️'}</span>
      <div>
        <div class="wx-current-temp">${cur.temp != null ? `${cur.temp}°C` : '—'}</div>
        <div class="wx-current-desc">${esc(cur.desc || '')}${d.holiday && d.trip ? ` · ${esc(d.trip)}` : ''}</div>
      </div>
    </div>`;
  const daysHtml = (d.days || [])
    .map((day) => `
    <div class="wx-day">
      <span class="wx-day-name">${esc(day.weekday)}</span>
      <span class="wx-day-emoji">${day.emoji || ''}</span>
      <span class="wx-day-desc">${esc(day.desc)}${day.precip != null && day.precip >= 30 ? ` <span class="wx-day-rain">${day.precip}%</span>` : ''}</span>
      <span class="wx-day-temp">${day.tmax}° <span class="lo">${day.tmin}°</span></span>
    </div>`)
    .join('');
  body.innerHTML = curHtml + (daysHtml || '<div class="wx-empty">No forecast available.</div>');
}

async function openWeather() {
  renderWeatherPanel();
  document.getElementById('weather-panel').hidden = false;
  document.getElementById('weather-backdrop').hidden = false;
  if (!weatherData) {
    document.getElementById('weather-panel-body').innerHTML = '<div class="wx-empty">Loading forecast…</div>';
    await loadWeather();
    renderWeatherPanel();
  }
}

function closeWeather() {
  document.getElementById('weather-panel').hidden = true;
  document.getElementById('weather-backdrop').hidden = true;
}

async function scanEmailReceipts() {
  showToast('Scanning email for receipts…');
  let res;
  try {
    res = await api('/finances/scan-email', { method: 'POST' });
  } catch (err) {
    return showToast(err.message, true);
  }
  const drafts = res.drafts || [];
  if (!drafts.length) {
    if ((res.needs_reconnect || []).length) {
      return showToast('Reconnect Google in Settings to grant Gmail access', true);
    }
    return showToast('No receipts found in recent emails');
  }
  const rows = drafts
    .map(
      (d, i) => `
      <label class="wx-day" style="cursor:pointer">
        <input type="checkbox" class="email-receipt-cb" data-idx="${i}" checked style="margin-right:6px">
        <span class="wx-day-desc">${esc(d.description || d.merchant || 'Receipt')}<br><span style="font-size:0.6875rem;color:var(--text-muted)">${esc(d.date || '')} · ${esc(d.email_subject || '')}</span></span>
        <span class="wx-day-temp neg">${fmt.gbp(d.amount)}</span>
      </label>`
    )
    .join('');
  window._emailDrafts = drafts;
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header"><h3>Email receipts found</h3><p>${drafts.length} receipt(s) from your inbox. Review and import.</p></div>
      <div class="wf-modal-body">${rows}</div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="email-import-btn">Import selected</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('email-import-btn').onclick = async () => {
    const picked = [...document.querySelectorAll('.email-receipt-cb')]
      .filter((cb) => cb.checked)
      .map((cb) => window._emailDrafts[parseInt(cb.dataset.idx, 10)]);
    if (!picked.length) return closeModal();
    try {
      const r = await api('/finances/import-email-receipts', {
        method: 'POST',
        body: JSON.stringify({ drafts: picked, account_id: 'joint' }),
      });
      closeModal();
      showToast(`Imported ${r.imported} receipt(s)`);
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  };
}

async function scanEmailMemory() {
  showToast('Reading your inbox for facts worth keeping… this can take a moment');
  let res;
  try {
    res = await api('/memory/scan-email', { method: 'POST' });
  } catch (err) {
    return showToast(err.message, true);
  }
  const cands = res.candidates || [];
  if (!cands.length) {
    if ((res.needs_reconnect || []).length) {
      return showToast('Reconnect Google in Settings to grant Gmail access', true);
    }
    return showToast(`No new facts found (scanned ${res.scanned || 0} emails)`);
  }
  window._memCands = cands;
  const rows = cands.map((c, i) => {
    const cat = MEMORY_CATS[c.category] || MEMORY_CATS.preferences;
    const src = c.source_from ? `${esc(c.source_from.replace(/<.*>/, '').trim() || c.source_from)}` : '';
    return `
      <label class="mem-cand">
        <input type="checkbox" class="mem-cand-cb" data-idx="${i}" checked>
        <span class="mem-cand-body">
          <span class="mem-cand-text">${esc(c.text)}</span>
          <span class="mem-cand-meta">${cat.icon} ${cat.label} · ${esc(memorySubjectName(c.subject))}${src ? ' · from ' + src : ''}</span>
        </span>
      </label>`;
  }).join('');
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal wf-modal-wide" role="dialog">
      <div class="wf-modal-header"><h3>Facts found in your email</h3><p>${cands.length} suggestion(s) from ${res.scanned || 0} emails. Untick anything you don't want, then save.</p></div>
      <div class="wf-modal-body">${rows}</div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="mem-import-btn">Save selected</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('mem-import-btn').onclick = async (e) => {
    const picked = [...document.querySelectorAll('.mem-cand-cb')]
      .filter((cb) => cb.checked)
      .map((cb) => window._memCands[parseInt(cb.dataset.idx, 10)])
      .map((c) => ({ text: c.text, category: c.category, subject: c.subject }));
    if (!picked.length) return closeModal();
    e.target.disabled = true;
    try {
      const r = await api('/memory/import-email', { method: 'POST', body: JSON.stringify({ facts: picked }) });
      closeModal();
      showToast(`Saved ${r.imported} fact(s) to memory`);
      await load();
    } catch (err) {
      showToast(err.message, true);
      e.target.disabled = false;
    }
  };
}

// Scan the inbox for bookings, appointments and documents, then let the user
// review and pick which to import. Mirrors the scanEmailMemory review pattern.
const INBOX_KIND_META = {
  trip: { icon: '🧳', label: 'Trip' },
  appointment: { icon: '📅', label: 'Appointment' },
  document: { icon: '📄', label: 'Document' },
};

function inboxCandidateDetail(c) {
  if (c.kind === 'trip') {
    const dates = c.start ? `${fmt.date(c.start)}${c.end ? ' → ' + fmt.date(c.end) : ''}` : '';
    return [c.destination, dates].filter(Boolean).join(' · ');
  }
  if (c.kind === 'appointment') {
    return [c.provider, c.datetime ? fmt.datetime(c.datetime) : ''].filter(Boolean).join(' · ');
  }
  if (c.kind === 'document') {
    const cat = DOC_CATEGORY_LABELS[c.category] || c.category;
    return [cat, c.expiry_date ? 'expires ' + fmt.date(c.expiry_date) : ''].filter(Boolean).join(' · ');
  }
  return '';
}

async function scanInbox() {
  showToast('Reading your inbox…');
  let res;
  try {
    res = await api('/inbox/scan', { method: 'POST' });
  } catch (err) {
    return showToast(err.message, true);
  }
  const cands = res.candidates || [];
  if (!cands.length) {
    if ((res.needs_reconnect || []).length) {
      return showToast('Reconnect Google in Settings to grant Gmail access', true);
    }
    return showToast(`Nothing to import found (scanned ${res.scanned || 0} emails)`);
  }
  window._inboxCands = cands;
  // Group visually by kind, but keep each checkbox pointed at its original index.
  const groups = ['trip', 'appointment', 'document']
    .map((kind) => {
      const items = cands.filter((c) => c.kind === kind);
      if (!items.length) return '';
      const meta = INBOX_KIND_META[kind];
      const rows = items
        .map((c) => {
          const i = cands.indexOf(c);
          const det = inboxCandidateDetail(c);
          const src = c.source_subject ? ` · ${esc(c.source_subject)}` : '';
          return `
        <label class="mem-cand">
          <input type="checkbox" class="inbox-cand-cb" data-idx="${i}" checked>
          <span class="mem-cand-body">
            <span class="mem-cand-text">${esc(c.title || 'Untitled')}</span>
            <span class="mem-cand-meta">${meta.icon} ${meta.label}${det ? ' · ' + esc(det) : ''}${src}</span>
          </span>
        </label>`;
        })
        .join('');
      return `<div class="inbox-group"><div class="inbox-group-label">${meta.icon} ${meta.label}s</div>${rows}</div>`;
    })
    .join('');
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal wf-modal-wide" role="dialog">
      <div class="wf-modal-header"><h3>Found in your email</h3><p>${cands.length} item(s) from ${res.scanned || 0} emails. Untick anything you don't want, then save.</p></div>
      <div class="wf-modal-body">${groups}</div>
      <div class="wf-modal-footer">
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="inbox-import-btn">Save selected</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
  document.getElementById('inbox-import-btn').onclick = async (e) => {
    const picked = [...document.querySelectorAll('.inbox-cand-cb')]
      .filter((cb) => cb.checked)
      .map((cb) => window._inboxCands[parseInt(cb.dataset.idx, 10)]);
    if (!picked.length) return closeModal();
    e.target.disabled = true;
    try {
      const r = await api('/inbox/import', { method: 'POST', body: JSON.stringify({ items: picked }) });
      closeModal();
      showToast(`Added ${r.created ?? picked.length}`);
      await load();
    } catch (err) {
      showToast(err.message, true);
      e.target.disabled = false;
    }
  };
}

const TOOL_LABELS = {
  get_household_summary: 'Checked household',
  list_upcoming_events: 'Listed events',
  create_calendar_event: 'Added calendar event',
  create_task: 'Added task',
  mark_task_done: 'Completed task',
  create_appointment: 'Booked appointment',
  create_holiday_trip: 'Created holiday trip',
  generate_holiday_ideas: 'Generated holiday ideas',
  add_bill: 'Added bill',
  log_transaction: 'Logged transaction',
  list_tasks: 'Listed tasks',
  get_morning_briefing: 'Morning briefing',
  search_household: 'Searched household',
  create_maintenance_item: 'Added maintenance',
  add_trip_packing_list: 'Added packing list',
};

let assistantOpen = false;
let assistantBusy = false;
let assistantConfigured = false;
let assistantMessages = [];
let assistantPendingConfirm = null;

function renderAssistantMessages(messages, pending = false) {
  const el = document.getElementById('assistant-messages');
  if (!messages.length && !pending && !assistantPendingConfirm) {
    el.innerHTML = '<div class="assistant-msg system">Try: “What’s on today?” or “Add boiler service next March”</div>';
    return;
  }
  el.innerHTML = messages.map((m) => {
    const actions = (m.actions || []).map((a) =>
      `<span class="assistant-action-pill">${esc(TOOL_LABELS[a.tool] || a.tool)}</span>`,
    ).join('');
    return `<div class="assistant-msg ${m.role}">${esc(m.content)}${actions ? `<div class="assistant-actions">${actions}</div>` : ''}</div>`;
  }).join('');
  if (assistantPendingConfirm) {
    el.innerHTML += `
      <div class="assistant-confirm-bar">
        <p>${esc(assistantPendingConfirm.summary)}</p>
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="assistant-confirm" data-action-id="${esc(assistantPendingConfirm.pending_id)}">Confirm</button>
      </div>`;
  }
  if (pending) {
    el.innerHTML += '<div class="assistant-typing"><span></span><span></span><span></span></div>';
  }
  el.scrollTop = el.scrollHeight;
}

function openAssistant() {
  assistantOpen = true;
  document.getElementById('assistant-panel').hidden = false;
  document.getElementById('assistant-backdrop').hidden = false;
  document.getElementById('assistant-input').focus();
}

function closeAssistant() {
  assistantOpen = false;
  document.getElementById('assistant-panel').hidden = true;
  document.getElementById('assistant-backdrop').hidden = true;
}

async function loadAssistantHistory() {
  if (!currentUser || !assistantConfigured) return;
  try {
    const data = await api('/assistant/history');
    assistantMessages = data.messages || [];
    renderAssistantMessages(assistantMessages);
  } catch {
    assistantMessages = [];
    renderAssistantMessages([]);
  }
}

async function sendAssistantMessage(text) {
  if (assistantBusy || !text.trim()) return;
  assistantBusy = true;
  const input = document.getElementById('assistant-input');
  const sendBtn = document.querySelector('.assistant-send');
  input.disabled = true;
  sendBtn.disabled = true;

  assistantMessages.push({ role: 'user', content: text.trim() });
  renderAssistantMessages(assistantMessages, true);

  try {
    const result = await api('/assistant/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text.trim() }),
    });
    assistantMessages.push({
      role: 'assistant',
      content: result.reply,
      actions: result.actions || [],
    });
    assistantPendingConfirm = result.pending_confirmation || null;
    renderAssistantMessages(assistantMessages);
    if (result.data_changed) await load();
  } catch (err) {
    assistantMessages.push({ role: 'assistant', content: `Sorry — ${err.message}` });
    renderAssistantMessages(assistantMessages);
  } finally {
    assistantBusy = false;
    input.disabled = false;
    sendBtn.disabled = false;
    input.value = '';
    input.focus();
  }
}

function initAssistant() {
  const fab = document.getElementById('assistant-fab');
  const panel = document.getElementById('assistant-panel');
  const backdrop = document.getElementById('assistant-backdrop');
  const form = document.getElementById('assistant-form');
  const input = document.getElementById('assistant-input');
  const clearBtn = document.getElementById('assistant-clear');
  const closeBtn = document.getElementById('assistant-close');

  fab.addEventListener('click', () => {
    if (assistantOpen) closeAssistant();
    else openAssistant();
  });
  closeBtn.addEventListener('click', closeAssistant);
  backdrop.addEventListener('click', closeAssistant);

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    sendAssistantMessage(input.value);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  clearBtn.addEventListener('click', async () => {
    try {
      await api('/assistant/clear', { method: 'POST' });
      assistantMessages = [];
      assistantPendingConfirm = null;
      renderAssistantMessages([]);
      showToast('New conversation started');
    } catch (err) {
      showToast(err.message, true);
    }
  });
}

async function refreshAssistantStatus() {
  const fab = document.getElementById('assistant-fab');
  if (!currentUser) {
    fab.hidden = true;
    return;
  }
  try {
    const status = await api('/assistant/status');
    assistantConfigured = status.configured;
    fab.hidden = !assistantConfigured;
    if (assistantConfigured) await loadAssistantHistory();
  } catch {
    fab.hidden = true;
  }
}

// Which page containers belong to each endpoint — used to show a per-section
// failure hint instead of blanking the whole app when one endpoint errors.
const SECTION_CONTAINERS = {
  dashboard: ['welcome-hero', 'reminder-strip', 'home-stats', 'home-events', 'home-tasks', 'home-bills', 'home-appointments', 'home-holiday', 'home-documents', 'home-finance'],
  calendar: ['calendar-grid', 'calendar-agenda'],
  finances: ['finance-stats', 'accounts-row', 'finance-bills', 'finance-budgets', 'finance-savings', 'finance-transactions', 'merged-recurring'],
  appointments: ['appointments-body'],
  holidays: ['holiday-trips', 'holiday-ideas'],
  documents: ['vault-stats', 'vault-grid'],
  media: ['media-storage', 'media-grid'],
  subscriptions: ['subscription-stats', 'subscription-list'],
  settings: ['settings-content'],
  briefing: ['briefing-card'],
  activity: ['activity-feed'],
  renewals: ['renewal-stats', 'renewal-timeline'],
  maintenance: ['maintenance-list'],
  memory: ['memory-content'],
};

function markSectionFailed(key) {
  (SECTION_CONTAINERS[key] || []).forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const msg = 'Couldn’t load this section — try refreshing.';
    const cols = el.closest('table')?.querySelectorAll('thead th').length || 6;
    el.innerHTML = el.tagName === 'TBODY'
      ? `<tr><td colspan="${cols}" class="hint-small">${msg}</td></tr>`
      : `<p class="hint-small">${msg}</p>`;
  });
}

// --- Home: Recipe book ------------------------------------------------------
// Own endpoint (/api/recipes). Reuses the .maintenance-row + .row-edit inline
// CRUD pattern. Each row also gets a "Plan…" control that drops the recipe onto
// a chosen day's meal plan (POST /recipes/{id}/plan) and refreshes the planner.

async function loadRecipes() {
  const list = document.getElementById('recipes-list');
  if (!list) return;
  try {
    const data = await api('/recipes');
    store.recipes = data.recipes || [];
    renderRecipes(store.recipes);
  } catch {
    list.innerHTML = '<p class="hint-small">Recipe book unavailable.</p>';
  }
}

function findRecipe(id) {
  return (store.recipes || []).find((r) => String(r.id) === String(id));
}

// Build a create/update payload from an inline recipe row (shared by add + edit).
function recipePayload(f) {
  const serves = parseInt(f.serves, 10);
  return {
    title: (f.title || '').trim(),
    ingredients: (f.ingredients || '').trim(),
    method: (f.method || '').trim(),
    tags: (f.tags || '').trim(),
    serves: Number.isFinite(serves) && serves > 0 ? serves : null,
  };
}

function recipeRowInner(r) {
  const chips = (r.tags || '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => `<span class="recipe-chip">${esc(t)}</span>`)
    .join('');
  const serves = r.serves ? `<span class="recipe-serves">serves ${esc(String(r.serves))}</span>` : '';
  const meta = chips || serves ? `<div class="recipe-meta">${chips}${serves}</div>` : '';
  return `
        <div class="recipe-main">
          <div class="recipe-title">${esc(r.title)}</div>
          ${meta}
          <div class="recipe-plan-bar" hidden>
            <input type="date" class="recipe-plan-date" data-f="plan_date" value="${todayIsoDate()}">
            <button type="button" class="btn btn-sm btn-primary wf-action" data-action="recipe-plan-confirm" data-recipe-id="${r.id}">Plan it</button>
            <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="recipe-plan-cancel" data-recipe-id="${r.id}">Cancel</button>
          </div>
        </div>
        <div class="recipe-side">
          <button class="btn btn-sm btn-soft wf-action" data-action="recipe-plan-toggle" data-recipe-id="${r.id}">Plan…</button>
          <button class="bill-edit-btn wf-action" data-action="edit-recipe" data-recipe-id="${r.id}" title="Edit recipe" aria-label="Edit recipe">✎</button>
        </div>`;
}

function recipeEditInner(r) {
  return `
    <div class="row-edit" data-recipe-id="${r.id}">
      <input type="text" class="te-input" data-f="title" value="${esc(r.title)}" placeholder="Recipe name (e.g. Spaghetti bolognese)">
      <div class="row-edit-fields">
        <label class="row-edit-full">Ingredients<textarea data-f="ingredients" rows="3" placeholder="One per line or comma-separated">${esc(r.ingredients || '')}</textarea></label>
        <label class="row-edit-full">Method<textarea data-f="method" rows="3" placeholder="Steps…">${esc(r.method || '')}</textarea></label>
        <label>Tags<input type="text" data-f="tags" value="${esc(r.tags || '')}" placeholder="e.g. quick, veggie"></label>
        <label>Serves<input type="number" min="1" data-f="serves" value="${r.serves ?? ''}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-recipe-inline" data-recipe-id="${r.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-recipe-inline" data-recipe-id="${r.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-recipe" data-recipe-id="${r.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function recipeAddInner() {
  return `
    <div class="row-edit" id="recipe-add-form">
      <input type="text" class="te-input" data-f="title" placeholder="Recipe name (e.g. Spaghetti bolognese)">
      <div class="row-edit-fields">
        <label class="row-edit-full">Ingredients<textarea data-f="ingredients" rows="3" placeholder="One per line or comma-separated"></textarea></label>
        <label class="row-edit-full">Method<textarea data-f="method" rows="3" placeholder="Steps…"></textarea></label>
        <label>Tags<input type="text" data-f="tags" placeholder="e.g. quick, veggie"></label>
        <label>Serves<input type="number" min="1" data-f="serves" placeholder="4"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-recipe-new">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="recipes-list">Cancel</button>
      </div>
    </div>`;
}

function renderRecipes(recipes) {
  const el = document.getElementById('recipes-list');
  if (!el) return;
  el.innerHTML = (recipes && recipes.length)
    ? recipes.map((r) => `<div class="maintenance-row" data-recipe-id="${r.id}">${recipeRowInner(r)}</div>`).join('')
    : '<div class="vault-empty"><p>No recipes yet</p><p class="hint-small">Save your go-to meals here, then drop them straight into the week\'s plan.</p></div>';
}

// --- Home care: Little ones (dependents + their care items) ------------------
// Own endpoints (/api/dependents, /api/care?dependent_id=). Renders each
// dependent as a panel, then their care items (jabs/checkups/etc.). Reuses the
// .row-edit inline-CRUD pattern; all status colours use semantic vars.

const CARE_CATEGORIES = [
  ['vaccination', '💉 Vaccination'],
  ['checkup', '🩺 Checkup'],
  ['grooming', '✂️ Grooming'],
  ['milestone', '🌟 Milestone'],
  ['measurement', '📏 Measurement'],
  ['other', '📋 Other'],
];
const CARE_EMOJI = { vaccination: '💉', checkup: '🩺', grooming: '✂️', milestone: '🌟', measurement: '📏', other: '📋' };
const DEPENDENT_KINDS = [['child', '👶 Child'], ['pet', '🐶 Pet']];

async function loadDependents() {
  const host = document.getElementById('dependents-list');
  if (!host) return;
  try {
    const data = await api('/dependents');
    store.dependents = data.dependents || [];
    // Care items live on a separate endpoint, one call per dependent (parallel).
    const cares = await Promise.all(
      store.dependents.map((d) =>
        api(`/care?dependent_id=${encodeURIComponent(d.id)}`).then((r) => r.items || []).catch(() => [])
      )
    );
    store.careItems = {};
    store.dependents.forEach((d, i) => { store.careItems[d.id] = cares[i]; });
    renderDependents(store.dependents);
  } catch {
    host.innerHTML = '<p class="hint-small">Little ones unavailable.</p>';
  }
}

function findDependent(id) {
  return (store.dependents || []).find((d) => String(d.id) === String(id));
}

function findCare(id) {
  const all = store.careItems || {};
  for (const depId in all) {
    const found = (all[depId] || []).find((c) => String(c.id) === String(id));
    if (found) return found;
  }
  return null;
}

// Age from dob: "N months" under 2 years, otherwise whole years.
function dependentAge(dob) {
  if (!dob) return '';
  const [y, m, day] = dob.slice(0, 10).split('-').map(Number);
  if (!y || !m || !day) return '';
  const birth = new Date(y, m - 1, day);
  const now = new Date();
  let months = (now.getFullYear() - birth.getFullYear()) * 12 + (now.getMonth() - birth.getMonth());
  if (now.getDate() < birth.getDate()) months -= 1;
  if (months < 0) return '';
  const years = Math.floor(months / 12);
  if (years < 2) return `${months} month${months === 1 ? '' : 's'}`;
  return `${years} year${years === 1 ? '' : 's'}`;
}

// Care due status: overdue (red) / due within 30d (amber) / future (muted).
function careDueMeta(dueDate, done) {
  if (done) return { cls: 'done', label: dueDate ? fmtShortDate(dueDate, true) : '' };
  if (!dueDate) return { cls: 'none', label: 'No date' };
  const iso = String(dueDate).slice(0, 10);
  const label = fmtShortDate(dueDate, true);
  if (iso < todayIsoDate()) return { cls: 'overdue', label: `Overdue · ${label}` };
  const [y, m, d] = iso.split('-').map(Number);
  const due = new Date(y, m - 1, d);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const days = Math.round((due - now) / 86400000);
  if (days <= 30) return { cls: 'soon', label: `Due ${label}` };
  return { cls: 'future', label: `Due ${label}` };
}

function careRowInner(it) {
  const emoji = CARE_EMOJI[it.category] || '📋';
  const due = careDueMeta(it.due_date, it.done);
  return `
        <div class="care-main">
          <span class="care-emoji" title="${esc(it.category)}">${emoji}</span>
          <div class="care-body">
            <div class="care-title">${esc(it.title)}</div>
            <div class="care-sub">
              ${due.label ? `<span class="care-due ${due.cls}">${due.label}</span>` : ''}
              ${it.notes ? `<span class="care-notes">${esc(it.notes)}</span>` : ''}
            </div>
          </div>
        </div>
        <div class="care-actions">
          ${it.done
            ? '<span class="care-done-badge">Done ✓</span>'
            : `<button class="btn btn-sm btn-primary wf-action" data-action="care-done" data-care-id="${it.id}">Done ✓</button>`}
          <button class="bill-edit-btn wf-action" data-action="edit-care" data-care-id="${it.id}" title="Edit care item" aria-label="Edit care item">✎</button>
        </div>`;
}

function careEditInner(it) {
  const catOpts = CARE_CATEGORIES.map(([v, l]) => `<option value="${v}"${v === it.category ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit" data-care-id="${it.id}">
      <input type="text" class="te-input" data-f="title" value="${esc(it.title)}" placeholder="e.g. Rabies booster">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${catOpts}</select></label>
        <label>Due date<input type="date" data-f="due_date" value="${esc((it.due_date || '').slice(0, 10))}"></label>
        <label>Notes<input type="text" data-f="notes" value="${esc(it.notes || '')}"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-care-inline" data-care-id="${it.id}">Save</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-care-inline" data-care-id="${it.id}">Cancel</button>
        <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-care" data-care-id="${it.id}" style="margin-left:auto">Delete</button>
      </div>
    </div>`;
}

function careAddInner(dependentId) {
  const catOpts = CARE_CATEGORIES.map(([v, l]) => `<option value="${v}"${v === 'checkup' ? ' selected' : ''}>${l}</option>`).join('');
  return `
    <div class="row-edit care-add-form" data-dependent-id="${dependentId}">
      <input type="text" class="te-input" data-f="title" placeholder="e.g. 12-week vaccination">
      <div class="row-edit-fields">
        <label>Category<select data-f="category">${catOpts}</select></label>
        <label>Due date<input type="date" data-f="due_date" value="${todayIsoDate()}"></label>
        <label>Notes<input type="text" data-f="notes" placeholder="Optional"></label>
      </div>
      <div class="row-edit-actions">
        <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-care-new" data-dependent-id="${dependentId}">Add</button>
        <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-care-add">Cancel</button>
      </div>
    </div>`;
}

// Build a create/update payload from an inline dependent row (shared by add + edit).
function dependentPayload(f) {
  const kind = f.kind === 'pet' ? 'pet' : 'child';
  return {
    name: (f.name || '').trim(),
    kind,
    dob: f.dob || null,
    breed: kind === 'pet' ? ((f.breed || '').trim() || null) : null,
    notes: (f.notes || '').trim() || null,
  };
}

function dependentKindSelect(selected) {
  return DEPENDENT_KINDS.map(([v, l]) => `<option value="${v}"${v === selected ? ' selected' : ''}>${l}</option>`).join('');
}

function dependentPanel(d) {
  const emoji = d.kind === 'pet' ? '🐶' : '👶';
  const parts = [];
  const age = dependentAge(d.dob);
  if (age) parts.push(esc(age));
  if (d.kind === 'pet' && d.breed) parts.push(esc(d.breed));
  const meta = parts.join(' · ');
  const items = store.careItems?.[d.id] || [];
  const careRows = items.length
    ? items.map((it) => `<div class="care-row${it.done ? ' done' : ''}" data-care-id="${it.id}">${careRowInner(it)}</div>`).join('')
    : '<p class="hint-small care-empty">No care items yet — add jabs, checkups or milestones below.</p>';
  return `
    <div class="dependent-panel" data-dependent-id="${d.id}">
      <div class="dependent-head">
        <div class="dependent-ident">
          <span class="dependent-emoji">${emoji}</span>
          <div>
            <div class="dependent-name">${esc(d.name)}</div>
            ${meta ? `<div class="dependent-meta">${meta}</div>` : ''}
          </div>
        </div>
        <div class="dependent-head-actions">
          <button class="btn btn-sm btn-soft wf-action" data-action="add-care" data-dependent-id="${d.id}">+ Care item</button>
          <button class="bill-edit-btn wf-action" data-action="edit-dependent" data-dependent-id="${d.id}" title="Edit" aria-label="Edit dependent">✎</button>
        </div>
      </div>
      ${d.notes ? `<p class="hint-small dependent-notes">${esc(d.notes)}</p>` : ''}
      <div class="care-list" id="care-list-${d.id}">${careRows}</div>
    </div>`;
}

function dependentEditInner(d) {
  const petHidden = d.kind === 'pet' ? '' : ' style="display:none"';
  return `
    <div class="dependent-panel editing" data-dependent-id="${d.id}">
      <div class="row-edit" data-dependent-id="${d.id}">
        <input type="text" class="te-input" data-f="name" value="${esc(d.name)}" placeholder="Name">
        <div class="row-edit-fields">
          <label>Type<select data-f="kind" class="dependent-kind-select">${dependentKindSelect(d.kind)}</select></label>
          <label>Date of birth<input type="date" data-f="dob" value="${esc((d.dob || '').slice(0, 10))}"></label>
          <label class="dependent-breed-field"${petHidden}>Breed<input type="text" data-f="breed" value="${esc(d.breed || '')}" placeholder="e.g. Cockapoo"></label>
          <label>Notes<input type="text" data-f="notes" value="${esc(d.notes || '')}"></label>
        </div>
        <div class="row-edit-actions">
          <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-dependent-inline" data-dependent-id="${d.id}">Save</button>
          <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-dependent-inline" data-dependent-id="${d.id}">Cancel</button>
          <button type="button" class="btn btn-sm btn-ghost wf-action" data-action="delete-dependent" data-dependent-id="${d.id}" style="margin-left:auto">Delete</button>
        </div>
      </div>
    </div>`;
}

function dependentAddInner() {
  return `
    <div class="dependent-panel" id="dependent-add-form">
      <div class="row-edit">
        <input type="text" class="te-input" data-f="name" placeholder="Name (e.g. Arthur)">
        <div class="row-edit-fields">
          <label>Type<select data-f="kind" class="dependent-kind-select">${dependentKindSelect('child')}</select></label>
          <label>Date of birth<input type="date" data-f="dob"></label>
          <label class="dependent-breed-field" style="display:none">Breed<input type="text" data-f="breed" placeholder="e.g. Cockapoo"></label>
          <label>Notes<input type="text" data-f="notes" placeholder="Optional"></label>
        </div>
        <div class="row-edit-actions">
          <button type="button" class="btn btn-sm btn-primary wf-action" data-action="save-dependent-new">Add</button>
          <button type="button" class="btn btn-sm btn-secondary wf-action" data-action="cancel-add-row" data-container="dependents-list">Cancel</button>
        </div>
      </div>
    </div>`;
}

function renderDependents(deps) {
  const host = document.getElementById('dependents-list');
  if (!host) return;
  host.innerHTML = (deps && deps.length)
    ? deps.map((d) => dependentPanel(d)).join('')
    : '<div class="vault-empty"><p>No little ones yet</p><p class="hint-small">Add Arthur and Bean here to track jabs, checkups, grooming and milestones.</p></div>';
}

async function load() {
  try {
    const me = await api('/auth/me');
    currentUser = me.user;
    hideLogin();
  } catch {
    showLogin();
    return;
  }

  loadWeather();  // refresh header forecast (also picks up holiday-location changes)

  const keys = ['dashboard', 'calendar', 'finances', 'appointments', 'holidays', 'documents', 'media', 'subscriptions', 'settings', 'briefing', 'activity', 'renewals', 'maintenance', 'memory', 'tradespeople'];
  const results = await Promise.allSettled(keys.map((k) => api(`/${k}`)));

  store = {};
  const failed = [];
  results.forEach((r, i) => {
    if (r.status === 'fulfilled') store[keys[i]] = r.value;
    else failed.push(keys[i]);
  });

  const { dashboard, calendar, finances, appointments, holidays, documents, media, subscriptions, settings, briefing, activity, renewals, maintenance, memory, tradespeople } = store;

  renderActionGrid();
  if (dashboard) {
    renderMembers(dashboard.users || []);
    renderWelcome(dashboard);
    renderReminders(dashboard.reminders || []);
    renderHome(dashboard);
    renderNotifications(dashboard.reminders || [], dashboard.notifications_unread);
  }
  loadShopping();  // shared shopping list on the home card (own endpoint)
  loadMeals();     // weekly meal planner on the home card (own endpoint)
  renderInboxSuggestions(); // Home → email suggestions card (own endpoint)
  loadRecipes();   // Home → Recipe book card: save meals & plan them (own endpoint)
  loadOccasions(); // Home → Occasions card: birthdays & anniversaries (own endpoint)
  loadWishlist();  // Home → Gift ideas / wishlists card (own endpoint)
  if (briefing) renderBriefing(briefing);
  if (activity) renderActivityFeed(activity);
  if (calendar) renderCalendar(calendar);
  if (finances) renderFinances(finances);
  loadInsights();   // Finances → Insights card (own endpoint)
  loadForecast();   // Finances → Money-left-this-month forecast card (own endpoint)
  loadByPerson();   // Finances → Spending-by-person breakdown (own endpoint)
  loadNetWorth();   // Finances → Net worth + assets (own endpoints)
  loadTrends();     // Finances → Trends card: spend + net-worth charts (own endpoints)
  if (renewals) renderRenewals(renewals);
  if (maintenance) renderMaintenance(maintenance);
  renderTradespeople(tradespeople || { tradespeople: [] });
  loadChores();     // Home care → Chores rotation card (own endpoint)
  loadInventory();  // Home care → Home inventory / warranty card (own endpoint)
  loadVehicles();   // Home care → Vehicles card: MOT/tax/insurance/service (own endpoint)
  loadDependents(); // Home care → Little ones card: dependents + care items (own endpoints)
  if (appointments) renderAppointments(appointments);
  if (holidays) renderHolidays(holidays);
  if (media) renderMedia(media);
  loadMediaStorage(); // Photos → storage meter (own endpoint)
  if (subscriptions) renderSubscriptions(subscriptions);
  if (documents) renderDocuments(documents);
  if (memory) renderMemory(memory);
  if (settings) { renderSettings(settings); loadNotificationPrefs(); refreshPushUI(); loadVoiceStatus(); loadSnapSortStatus(); }

  failed.forEach(markSectionFailed);
  if (failed.length) console.error('Failed to load:', failed.join(', '));

  await refreshAssistantStatus();
}

async function boot() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('google_connected')) {
    showToast('Google Calendar connected');
    window.history.replaceState({}, '', '/');
  }
  if (params.get('google_error')) {
    const raw = params.get('google_error');
    // Backend passes either "1" (generic) or a URL-encoded reason — show the specific one.
    const msg = raw === '1'
      ? 'Google connection failed — check .env credentials'
      : decodeURIComponent(raw.replace(/\+/g, ' '));
    showToast(msg, true);
    window.history.replaceState({}, '', '/');
  }
  if (params.get('bank_connected')) {
    showToast('Bank connected — transactions syncing');
    window.history.replaceState({}, '', '/');
  }
  if (params.get('bank_error')) {
    showToast(decodeURIComponent(params.get('bank_error').replace(/\+/g, ' ')), true);
    window.history.replaceState({}, '', '/');
  }
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
  }
  try {
    await load();
  } catch (err) {
    console.error(err);
    if (!currentUser) showLogin();
    else showToast('Failed to load data', true);
  }
}

initTabs();
initActions();
initAssistant();
boot();
