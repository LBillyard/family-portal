/* Family Portal — live app */

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
let activeModalKey = null;

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (res.status === 401 && !path.includes('/auth/')) {
    showLogin();
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
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
  return d.innerHTML;
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

function userColour(users, id) {
  return users.find((u) => u.id === id)?.colour || '#718096';
}
function userName(users, id) {
  return users.find((u) => u.id === id)?.name || id;
}

const MODALS = {
  'add-event': {
    title: 'Add event',
    desc: 'Creates a portal event and optionally syncs to Google Calendar.',
    fields: [
      { label: 'Title', type: 'text', value: 'Date night' },
      { label: 'Date', type: 'date', value: '2026-07-11' },
      { label: 'Time', type: 'time', value: '19:00' },
      { label: 'Assigned to', type: 'select', options: ['Luke', 'Partner', 'Both'] },
      { label: 'Location', type: 'text', value: '' },
    ],
  },
  'log-expense': {
    title: 'Log transaction',
    desc: 'Manual income or expense entry.',
    fields: [
      { label: 'Description', type: 'text', value: 'Weekly shop' },
      { label: 'Amount (£)', type: 'number', value: '45.00' },
      { label: 'Category', type: 'select', options: ['Groceries', 'Transport', 'Eating out', 'Income'] },
      { label: 'Account', type: 'select', options: ['Joint current', 'Luke personal', 'Partner personal'] },
      { label: 'Date', type: 'date', value: '2026-07-05' },
    ],
  },
  'add-bill': {
    title: 'Add recurring bill',
    desc: 'Track monthly or annual payments.',
    fields: [
      { label: 'Bill name', type: 'text', value: 'Spotify' },
      { label: 'Amount (£)', type: 'number', value: '11.99' },
      { label: 'Due day of month', type: 'number', value: '15' },
      { label: 'Category', type: 'select', options: ['Utilities', 'Subscriptions', 'Housing', 'Transport'] },
    ],
  },
  'add-appointment': {
    title: 'New appointment',
    desc: 'Health, dental, car MOT, vet — with optional calendar sync.',
    fields: [
      { label: 'Title', type: 'text', value: 'GP appointment' },
      { label: 'Provider', type: 'text', value: 'Oakwood Medical' },
      { label: 'Date & time', type: 'datetime-local', value: '2026-07-14T10:30' },
      { label: 'Category', type: 'select', options: ['Health', 'Dental', 'Car', 'Vet'] },
      { label: 'Remind me (days before)', type: 'number', value: '2' },
    ],
  },
  'add-task': {
    title: 'Add shared task',
    desc: 'Household to-do assigned to one or both of you.',
    fields: [
      { label: 'Task', type: 'text', value: 'Book airport parking' },
      { label: 'Assign to', type: 'select', options: ['Luke', 'Partner', 'Either'] },
      { label: 'Due date', type: 'date', value: '2026-07-10' },
      { label: 'Priority', type: 'select', options: ['High', 'Medium', 'Low'] },
    ],
  },
  'new-trip': {
    title: 'New holiday trip',
    desc: 'Start from scratch or promote a saved AI idea.',
    fields: [
      { label: 'Trip name', type: 'text', value: 'Summer city break' },
      { label: 'Status', type: 'select', options: ['Idea', 'Planning', 'Booked'] },
      { label: 'Start date', type: 'date', value: '' },
      { label: 'Budget (£)', type: 'number', value: '800' },
    ],
  },
  'connect-google': {
    title: 'Connect Google Calendar',
    desc: 'OAuth sign-in — read and write events per person.',
    fields: [
      { label: 'Account', type: 'select', options: ['Luke@gmail.com', 'Partner@gmail.com'] },
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

const ACTION_MSG = {
  search: 'Global search — events, bills, appointments, trips',
  'open-settings': 'Opening settings…',
  'sync-calendar': 'Pulling latest events from Google Calendar',
  'sync-appointments': 'Adding appointments to shared calendar',
  transfer: 'Transfer between accounts',
  'export-transactions': 'Export CSV for July 2026',
  'add-document': 'Document vault — passports, insurance, MOT',
  'compare-trips': 'Side-by-side trip comparison view',
  'filter-all-trips': 'Showing all trips',
  'filter-booked': 'Filter: booked trips only',
  'filter-planning': 'Filter: planning stage',
  'filter-ideas': 'Filter: ideas only',
  'cal-prev': 'Previous month',
  'cal-next': 'Next month',
  'cal-today': 'Jump to today',
  'cal-view-month': 'Month view',
  'cal-view-week': 'Week view',
  'cal-view-agenda': 'Agenda view',
  'save-idea': 'Saved to holiday wishlist ✓',
  'view-trip': 'Trip detail — checklist, bookings, budget',
  'edit-trip': 'Edit trip — dates, budget, checklist',
  'edit-member': 'Edit member — name, colour, Google account',
  'view-booking': 'Open booking confirmation link',
  'edit-appointment': 'Edit appointment details',
  'preview-login': 'Login screen — household PIN or per-user password',
  'toggle-task': 'Task marked complete',
};

const SEARCH_RESULTS = [
  { type: 'Appointment', label: 'Dentist — check-up', meta: '8 Jul · Smile Dental', tab: 'appointments' },
  { type: 'Event', label: 'Date night', meta: '11 Jul · The Ivy', tab: 'calendar' },
  { type: 'Bill', label: 'Council tax', meta: '£186 · due 15th', tab: 'finances' },
  { type: 'Trip', label: 'Algarve, Portugal', meta: '15–22 Aug · booked', tab: 'holidays' },
  { type: 'Task', label: 'Book Portugal airport parking', meta: 'Due 10 Jul · Luke', tab: 'home' },
];

function showToast(msg, isError = false) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = isError
    ? `<strong style="color:#f87171">Error:</strong> ${esc(msg)}`
    : `<strong>Saved:</strong> ${esc(msg)}`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function showLogin() {
  document.getElementById('login-overlay').hidden = false;
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
      if (f.type === 'select') {
        return `<label>${f.label}<select>${f.options.map((o) => `<option>${o}</option>`).join('')}</select></label>`;
      }
      if (f.type === 'textarea') {
        return `<label>${f.label}<textarea rows="3">${f.value || ''}</textarea></label>`;
      }
      return `<label>${f.label}<input type="${f.type}" value="${f.value || ''}"></label>`;
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
}

function readModalFields() {
  const modal = document.querySelector('.wf-modal');
  if (!modal) return {};
  const data = {};
  modal.querySelectorAll('label').forEach((label) => {
    const input = label.querySelector('input, select, textarea');
    if (!input) return;
    const key = label.textContent.trim();
    data[key] = input.value;
  });
  return data;
}

async function submitModal(key) {
  const f = readModalFields();
  try {
    if (key === 'add-event') {
      const dateVal = f['Date'];
      const timeVal = f['Time'] || '09:00';
      const start = dateVal.includes('T') ? dateVal : `${dateVal}T${timeVal}:00`;
      const assignee = (f['Assigned to'] || 'Luke').toLowerCase();
      await api('/events', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Title'],
          start,
          end: start,
          user_id: assignee.includes('partner') ? 'partner' : assignee.includes('both') ? 'luke' : 'luke',
          location: f['Location'] || null,
        }),
      });
    } else if (key === 'log-expense') {
      const acctMap = { 'Joint current': 'joint', 'Luke personal': 'luke_acct', 'Partner personal': 'partner' };
      await api('/transactions', {
        method: 'POST',
        body: JSON.stringify({
          description: f['Description'],
          amount: parseFloat(f['Amount (£)'] || f['Amount'] || 0),
          category: f['Category'],
          account_id: acctMap[f['Account']] || 'joint',
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
        }),
      });
    } else if (key === 'add-appointment') {
      await api('/appointments', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Title'],
          provider: f['Provider'],
          datetime: f['Date & time'],
          category: (f['Category'] || 'health').toLowerCase(),
          reminder_days: parseInt(f['Remind me (days before)'] || 2, 10),
        }),
      });
    } else if (key === 'add-task') {
      const assignee = (f['Assign to'] || 'Luke').toLowerCase();
      await api('/tasks', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Task'],
          assignee_id: assignee.includes('partner') ? 'partner' : 'luke',
          due: f['Due date'] || null,
          priority: (f['Priority'] || 'medium').toLowerCase(),
        }),
      });
    } else if (key === 'new-trip') {
      await api('/holidays/trips', {
        method: 'POST',
        body: JSON.stringify({
          title: f['Trip name'],
          status: (f['Status'] || 'idea').toLowerCase(),
          start: f['Start date'] || null,
          end: null,
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
          notes: f['Notes'] || '',
        }),
      });
    } else if (key === 'holiday-ai') {
      await submitHolidayAI(f['Prompt'], f['Model']);
      return;
    } else {
      closeModal();
      showToast(ACTION_MSG[key] || 'Coming soon');
      return;
    }
    closeModal();
    showToast(MODALS[key].title);
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
      <button type="button" class="bank-provider-tile wf-action" data-action="connect-bank-provider" data-provider-id="${p.id}">
        <strong>${p.name}</strong>
        <span>${p.kind === 'card' ? 'Credit card' : 'Current account'}</span>
        ${p.note ? `<small>${p.note}</small>` : ''}
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

function switchTab(tabId) {
  document.querySelectorAll('.tab').forEach((t) => {
    t.classList.toggle('active', t.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-panel').forEach((p) => {
    p.classList.toggle('active', p.id === `tab-${tabId}`);
  });
}

function renderMembers(users) {
  document.getElementById('member-chips').innerHTML = users
    .map(
      (u) =>
        `<span class="member-chip"><span class="member-dot" style="background:${u.colour}"></span>${u.name}${u.google_connected ? ' · Google ✓' : ''}</span>`
    )
    .join('');

  document.getElementById('cal-filters').innerHTML = users
    .map(
      (u) =>
        `<label class="filter-chip"><input type="checkbox" checked><span style="display:inline-flex;align-items:center;gap:6px"><span class="member-dot" style="background:${u.colour}"></span>${u.name}</span></label>`
    )
    .join('') + '<label class="filter-chip"><input type="checkbox" checked><span>Shared</span></label>';
}

function renderWelcome(data) {
  const h = data.next_holiday;
  document.getElementById('welcome-hero').innerHTML = `
    <div>
      <h2>${fmt.greeting()}, Luke & Partner</h2>
      <p>${fmt.todayLabel()} · ${data.upcoming_events.length} events this week · ${data.notifications_unread} notifications</p>
    </div>
    <div class="welcome-meta">
      <div class="welcome-meta-item"><strong>${h?.days_until ?? '—'}</strong><span>Days to Portugal</span></div>
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
      <div><strong>${r.text}</strong><span>${r.when}</span></div>
    </div>`
    )
    .join('');
}

function renderHome(data) {
  const { users, upcoming_events, upcoming_bills, upcoming_appointments, next_holiday, finance_summary, tasks, documents } = data;

  document.getElementById('home-stats').innerHTML = `
    <div class="stat"><span>${upcoming_events.length}</span><label>Events this week</label><div class="stat-trend up">+2 from Google</div></div>
    <div class="stat"><span>${upcoming_bills.length}</span><label>Bills due</label><div class="stat-trend neutral">${fmt.gbp(finance_summary.bills_due_this_month)} total</div></div>
    <div class="stat"><span>${upcoming_appointments.length}</span><label>Appointments</label><div class="stat-trend neutral">Next: ${fmt.date(upcoming_appointments[0]?.datetime)}</div></div>
    <div class="stat"><span>${next_holiday?.days_until ?? '—'}</span><label>Days to holiday</label><div class="stat-trend up">${next_holiday?.title || ''}</div></div>`;

  document.getElementById('home-events').innerHTML = upcoming_events
    .map((e) => {
      const col = userColour(users, e.user_id);
      return `
      <div class="list-item">
        <div class="list-item-time">${e.all_day ? 'All day' : fmt.time(e.start)}</div>
        <div class="list-item-body">
          <div class="list-item-title">${e.title}</div>
          <div class="list-item-meta">${fmt.date(e.start)} · ${userName(users, e.user_id)}${e.location ? ` · ${e.location}` : ''}
            <span class="source-tag ${e.source}">${e.source}</span></div>
        </div>
        <span class="member-dot" style="background:${col};margin-top:6px"></span>
      </div>`;
    })
    .join('');

  document.getElementById('home-tasks').innerHTML = tasks
    .slice(0, 4)
    .map(
      (t) => `
    <div class="task-item${t.done ? ' done' : ''}">
      <div class="task-check${t.done ? ' done' : ''} wf-action" data-action="toggle-task" data-task-id="${t.id}"></div>
      <div class="task-body">
        <div class="task-title">${t.title}</div>
        <div class="task-meta">
          ${userName(users, t.assignee)}
          ${t.due ? `· Due ${fmt.date(t.due)}` : ''}
          <span class="priority-tag ${t.priority}">${t.priority}</span>
        </div>
      </div>
    </div>`
    )
    .join('');

  document.getElementById('home-bills').innerHTML = upcoming_bills
    .map(
      (b) => `
    <div class="list-item">
      <div class="list-item-body">
        <div class="list-item-title">${b.name}</div>
        <div class="list-item-meta">Due ${b.due_day} ${b.recurrence} · ${b.category}</div>
      </div>
      <div class="list-item-amount negative">${fmt.gbp(b.amount)}</div>
    </div>`
    )
    .join('');

  document.getElementById('home-appointments').innerHTML = upcoming_appointments
    .map(
      (a) => `
    <div class="list-item">
      <div class="list-item-time">${fmt.date(a.datetime)}</div>
      <div class="list-item-body">
        <div class="list-item-title">${a.title}</div>
        <div class="list-item-meta">${a.provider} · ${fmt.time(a.datetime)}</div>
      </div>
    </div>`
    )
    .join('');

  if (next_holiday) {
    const done = next_holiday.checklist?.filter((c) => c.done).length || 0;
    const total = next_holiday.checklist?.length || 0;
    document.getElementById('home-holiday').innerHTML = `
      <div class="holiday-countdown">${next_holiday.days_until} days</div>
      <p style="font-size:1rem;font-weight:600;color:var(--navy-900);margin:8px 0 4px">${next_holiday.title}</p>
      <p style="font-size:0.875rem;color:var(--text-muted)">${fmt.date(next_holiday.start)} → ${fmt.date(next_holiday.end)}</p>
      ${total ? `<p style="font-size:0.8125rem;color:var(--text-muted);margin-top:10px">Checklist: ${done}/${total} done</p>
        <div class="progress-bar"><div class="progress-fill" style="width:${Math.round((done / total) * 100)}%"></div></div>` : ''}
      <span class="status-tag booked" style="margin-top:12px;display:inline-block">${next_holiday.status}</span>`;
  }

  document.getElementById('home-documents').innerHTML = documents.length
    ? documents
        .slice(0, 4)
        .map(
          (d) => `
      <div class="list-item">
        <div class="list-item-body">
          <div class="list-item-title">${d.name}</div>
          <div class="list-item-meta">${DOC_CATEGORY_LABELS[d.category] || d.category}${d.expiry ? ' · ' + fmt.date(d.expiry) : ''}${d.has_file ? ' · 📎' : ''}</div>
        </div>
        <span class="status-tag ${docStatusClass(d.status)}">${docStatusLabel(d.status)}</span>
      </div>`
        )
        .join('')
    : '<p class="hint-small">All documents up to date</p>';

  const spentPct = Math.round((finance_summary.monthly_spent / finance_summary.monthly_income) * 100);
  document.getElementById('home-finance').innerHTML = `
    <div class="two-col" style="gap:32px">
      <div>
        <div style="display:flex;justify-content:space-between;margin-bottom:8px">
          <span style="font-size:0.875rem;color:var(--text-muted)">Spent this month</span>
          <span style="font-weight:700">${fmt.gbp(finance_summary.monthly_spent)} / ${fmt.gbp(finance_summary.monthly_income)}</span>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${spentPct}%"></div></div>
        <div class="finance-split"><span>${spentPct}% of income</span><span>Savings: ${fmt.gbp(finance_summary.savings_total)}</span></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div class="stat" style="margin:0;padding:16px"><span style="font-size:1.5rem">${fmt.gbp(finance_summary.joint_balance)}</span><label>Joint</label></div>
        <div class="stat" style="margin:0;padding:16px"><span style="font-size:1.5rem">${fmt.gbp(finance_summary.bills_due_this_month)}</span><label>Bills due</label></div>
      </div>
    </div>`;
}

function renderCalendar(data) {
  const { users, events } = data;
  document.getElementById('calendar-agenda').innerHTML = events
    .map((e) => {
      const col = userColour(users, e.user_id);
      return `
      <div class="list-item">
        <div class="list-item-time">${e.all_day ? 'All day' : fmt.time(e.start)}</div>
        <div class="list-item-body">
          <div class="list-item-title">${e.title}</div>
          <div class="list-item-meta">${fmt.date(e.start)} · ${userName(users, e.user_id)}${e.location ? ` · 📍 ${e.location}` : ''}</div>
        </div>
        <span class="cal-event" style="background:${col}">${userName(users, e.user_id)}</span>
      </div>`;
    })
    .join('');

  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const start = new Date('2026-07-06');
  let html = days.map((d) => `<div class="cal-day-header">${d}</div>`).join('');
  for (let i = -1; i < 34; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const iso = d.toISOString().slice(0, 10);
    const dayEvents = events.filter((e) => e.start.startsWith(iso));
    html += `
      <div class="cal-day${iso === '2026-07-05' ? ' today' : ''}">
        <div class="cal-day-num">${d.getDate()}</div>
        ${dayEvents.map((e) => `<div class="cal-event" style="background:${userColour(users, e.user_id)}" title="${e.title}">${e.title}</div>`).join('')}
      </div>`;
  }
  document.getElementById('calendar-grid').innerHTML = html;
}

function renderFinances(data) {
  const { bills, transactions, accounts, budgets, savings_goals, summary, connections = [], banking_configured } = data;

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
          (c) => `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">🏦</div>
            <div>
              <div class="connection-name">${c.provider_name}</div>
              <div class="connection-status connected">${c.last_synced_at ? 'Synced ' + fmt.datetime(c.last_synced_at) : 'Connected — tap Sync all banks'}</div>
            </div>
          </div>
          <button class="btn btn-sm btn-ghost wf-action" data-action="disconnect-bank" data-connection-id="${c.id}">Disconnect</button>
        </div>`
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
      <div class="account-tile-name">${a.name}${a.linked ? ' <span class="linked-badge">Live</span>' : ''}</div>
      <div class="account-tile-balance">${fmt.gbp(a.balance)}</div>
      <div class="account-tile-inst">${a.institution}</div>
    </div>`
    )
    .join('');

  document.getElementById('finance-bills').innerHTML = bills
    .map(
      (b) => `
    <div class="list-item${b.paid ? ' bill-paid' : ''}">
      <div class="list-item-body">
        <div class="list-item-title">${b.name}</div>
        <div class="list-item-meta">Day ${b.due_day} · ${b.category}${b.paid ? ' · ✓ Paid' : ''}</div>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <div class="list-item-amount negative">${fmt.gbp(b.amount)}</div>
        ${!b.paid ? `<button class="btn btn-sm btn-soft wf-action" data-action="mark-paid" data-bill-id="${b.id}">Pay</button>` : ''}
      </div>
    </div>`
    )
    .join('');

  document.getElementById('finance-budgets').innerHTML = budgets
    .map((b) => {
      const pct = Math.round((b.spent / b.limit) * 100);
      const cls = pct >= 100 ? 'over' : pct >= 85 ? 'warn' : '';
      return `
      <div>
        <div class="budget-row-head">
          <span>${b.category}</span>
          <span class="${pct >= 100 ? 'over' : ''}">${fmt.gbp(b.spent)} / ${fmt.gbp(b.limit)}</span>
        </div>
        <div class="progress-bar budget"><div class="progress-fill ${cls}" style="width:${Math.min(pct, 100)}%"></div></div>
      </div>`;
    })
    .join('');

  document.getElementById('finance-savings').innerHTML = savings_goals
    .map((g) => {
      const pct = Math.round((g.current / g.target) * 100);
      return `
      <div class="savings-card">
        <h4>${g.name}</h4>
        <div class="savings-amounts"><strong>${fmt.gbp(g.current)}</strong><span>of ${fmt.gbp(g.target)}</span></div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${g.colour}"></div></div>
      </div>`;
    })
    .join('');

  document.getElementById('finance-transactions').innerHTML = transactions
    .map(
      (t) => `
    <tr>
      <td>${fmt.date(t.date)}</td>
      <td>${t.description}</td>
      <td>${t.category}</td>
      <td>${t.account}</td>
      <td class="amount-cell ${t.amount >= 0 ? 'positive' : 'negative'}">${fmt.gbp(t.amount)}</td>
    </tr>`
    )
    .join('');
}

function renderAppointments(data, filter = 'all', category = 'all') {
  const { users, appointments } = data;
  let filtered = appointments.filter((a) => filter === 'all' || a.status === filter);
  if (category !== 'all') filtered = filtered.filter((a) => a.category === category);

  const cats = [...new Set(appointments.map((a) => a.category))];
  document.getElementById('appt-categories').innerHTML =
    `<button class="cat-btn active wf-action" data-appt-cat="all">All</button>` +
    cats.map((c) => `<button class="cat-btn wf-action" data-appt-cat="${c}">${c}</button>`).join('');

  document.getElementById('appointments-body').innerHTML = filtered
    .map(
      (a) => `
    <tr>
      <td>${fmt.datetime(a.datetime)}</td>
      <td><strong>${a.title}</strong><br><span style="font-size:0.75rem;color:var(--text-muted)">Reminder ${a.reminder_days}d before</span></td>
      <td>${a.provider}</td>
      <td>${a.location || '—'}</td>
      <td><span class="member-dot" style="background:${userColour(users, a.user_id)};display:inline-block;vertical-align:middle;margin-right:6px"></span>${userName(users, a.user_id)}</td>
      <td><span class="cat-pill ${a.category}">${a.category}</span></td>
      <td><span class="status-tag ${a.status}">${a.status}</span></td>
      <td>
        <button class="btn btn-sm btn-ghost wf-action" data-action="edit-appointment" data-modal="add-appointment">Edit</button>
      </td>
    </tr>`
    )
    .join('');
}

function renderHolidays(data) {
  const { trips, ideas } = data;

  document.getElementById('holiday-trips').innerHTML = trips
    .map((t) => {
      const checklist = (t.checklist || [])
        .map((c) => `<li class="${c.done ? 'done' : ''}"><span class="checklist-box">${c.done ? '✓' : ''}</span>${c.label}</li>`)
        .join('');
      const bookings = (t.bookings || [])
        .map((b) => `<a href="#" class="booking-link wf-action" data-action="view-booking"><span>${b.type}: ${b.ref}</span><span>→</span></a>`)
        .join('');
      const budgetPct = t.budget ? Math.round((t.spent / t.budget) * 100) : 0;
      return `
      <article class="holiday-card">
        <div class="holiday-card-header">
          <span class="status-tag ${t.status}">${t.status}</span>
          <h3>${t.title}</h3>
          ${t.start ? `<p style="font-size:0.8125rem;opacity:0.85;margin-top:4px">${fmt.date(t.start)} → ${fmt.date(t.end)}</p>` : '<p style="font-size:0.8125rem;opacity:0.85;margin-top:4px">Dates TBC</p>'}
        </div>
        <div class="holiday-card-body">
          ${t.days_until != null ? `<div class="holiday-countdown">${t.days_until} days</div>` : ''}
          <p style="font-size:0.875rem;color:var(--text-muted);margin-top:8px">Budget: ${fmt.gbp(t.spent)} / ${fmt.gbp(t.budget)}</p>
          <div class="progress-bar"><div class="progress-fill" style="width:${Math.min(budgetPct, 100)}%"></div></div>
          ${checklist ? `<ul class="checklist">${checklist}</ul>` : ''}
          ${bookings ? `<div class="booking-links">${bookings}</div>` : ''}
          <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
            <button class="btn btn-sm btn-primary wf-action" data-action="view-trip">Details</button>
            <button class="btn btn-sm btn-outline wf-action" data-action="edit-trip">Edit</button>
          </div>
        </div>
      </article>`;
    })
    .join('');

  document.getElementById('holiday-ideas').innerHTML = ideas
    .map(
      (i) => `
    <article class="idea-card">
      <div class="idea-tags">${(i.tags || []).map((t) => `<span class="idea-tag">${t}</span>`).join('')}</div>
      <h4>${i.destination}</h4>
      <p>${i.summary}</p>
      <p style="font-size:0.8125rem;color:var(--text-muted);margin-bottom:12px">Est. ${fmt.gbp(i.budget_estimate)}</p>
      <div style="display:flex;gap:8px">
        <button class="btn btn-sm ${i.saved ? 'btn-secondary' : 'btn-primary'} wf-action" data-action="save-idea" data-idea-id="${i.id}">${i.saved ? 'Saved ✓' : 'Save'}</button>
        <button class="btn btn-sm btn-soft wf-action" data-action="new-trip" data-modal="new-trip">Plan trip</button>
      </div>
    </article>`
    )
    .join('');
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
          <span class="vault-cat-pill">${DOC_CATEGORY_LABELS[d.category] || d.category}</span>
          <span class="status-tag ${docStatusClass(d.status)}">${docStatusLabel(d.status)}</span>
        </div>
        <h3 class="vault-card-title">${d.name}</h3>
        ${d.notes ? `<p class="vault-card-notes">${d.notes}</p>` : ''}
        <div class="vault-card-meta">
          ${d.expiry ? `<span>Expires ${fmt.date(d.expiry)}</span>` : '<span>No expiry set</span>'}
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

function renderSettings(data) {
  const { users, sync, notifications, integrations = {} } = data;
  const googleOk = integrations.google_calendar;
  const aiOk = integrations.openrouter;
  const bankOk = integrations.open_banking;
  const bankConns = store.finances?.connections || [];
  const docCount = store.documents?.documents?.length || 0;

  document.getElementById('settings-content').innerHTML = `
    <div class="settings-section phase-checklist">
      <h3>Build progress</h3>
      <p>Family Portal — ready to deploy when you are.</p>
      <ul class="phase-list">
        <li class="done">✓ SQLite database + CRUD</li>
        <li class="done">✓ Household login (2 users)</li>
        <li class="done">✓ Google Calendar OAuth + sync</li>
        <li class="done">✓ OpenRouter AI holiday ideas</li>
        <li class="done">✓ Open Banking (TrueLayer)</li>
        <li class="done">✓ CSV bank import</li>
        <li class="done">✓ PWA (add to home screen)</li>
        <li>○ Deploy to AWS (see docs/DEPLOY.md)</li>
      </ul>
    </div>
    <div class="settings-section">
      <h3>Login &amp; access</h3>
      <p>Simple auth for two users — preview the login screen.</p>
      <button class="btn btn-outline wf-action" data-action="preview-login">Preview login screen</button>
    </div>
    <div class="settings-section">
      <h3>Calendar connections</h3>
      <p>Google Calendar OAuth — ${googleOk ? 'configured' : 'add GOOGLE_CLIENT_ID to .env'}.</p>
      ${users
        .map(
          (u) => `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">📅</div>
            <div>
              <div class="connection-name">${u.name} — Google Calendar</div>
              <div class="connection-status ${u.google_connected ? 'connected' : ''}">${u.google_connected ? 'Connected · Last sync ' + sync.google_last : 'Not connected'}</div>
            </div>
          </div>
          <button class="btn btn-sm ${u.google_connected ? 'btn-secondary' : 'btn-primary'} wf-action" data-action="connect-google" ${googleOk ? '' : 'disabled title="Configure Google OAuth in .env"'}>${u.google_connected ? 'Reconnect' : 'Connect'}</button>
        </div>`
        )
        .join('')}
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
              <div class="connection-name">${c.provider_name}</div>
              <div class="connection-status connected">${c.last_synced_at ? 'Last sync ' + fmt.datetime(c.last_synced_at) : 'Connected'}</div>
            </div>
          </div>
          <button class="btn btn-sm btn-secondary wf-action" data-action="connect-bank-provider" data-provider-id="${c.provider_id}">Reconnect</button>
        </div>`
            )
            .join('')
        : `<p style="font-size:0.875rem;color:var(--text-muted)">No banks connected yet — use Finances → Connect bank.</p>`}
      <button class="btn btn-sm btn-primary wf-action" data-action="connect-bank" style="margin-top:10px" ${bankOk ? '' : 'disabled'}>Connect Starling / Revolut / Amex / Virgin</button>
    </div>
    <div class="settings-section">
      <h3>AI — OpenRouter</h3>
      <p>Holiday ideas — ${aiOk ? 'API key configured' : 'add OPENROUTER_API_KEY to .env'}.</p>
      <div class="connection-row">
        <div class="connection-info">
          <div class="connection-icon">✨</div>
          <div>
            <div class="connection-name">OpenRouter API</div>
            <div class="connection-status">Not configured — add OPENROUTER_API_KEY in Phase 2</div>
          </div>
        </div>
        <button class="btn btn-sm btn-ai wf-action" data-action="holiday-idea" data-modal="holiday-ai" ${aiOk ? '' : 'disabled title="Configure OpenRouter in .env"'}>Configure</button>
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
            <span class="member-dot" style="background:${u.colour};width:12px;height:12px"></span>
            <div class="connection-name">${u.name}</div>
          </div>
          <button class="btn btn-sm btn-ghost wf-action" data-action="edit-member">Edit</button>
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
      <h3>Recent notifications</h3>
      ${notifications.map((n) => `<div class="list-item" style="padding:10px 0"><div class="list-item-body"><div class="list-item-title">${n.text}</div><div class="list-item-meta">${n.time}</div></div></div>`).join('')}
    </div>`;

  document.getElementById('sync-pill').innerHTML = `<span class="sync-dot"></span> Synced ${sync.google_last}`;
}

function openSearchModal() {
  closeModal();
  closeNotif();
  const results = SEARCH_RESULTS.map(
    (r) =>
      `<button type="button" class="search-result wf-action" data-tab-link="${r.tab}">
        <span class="search-result-type">${r.type}</span>
        <strong>${r.label}</strong>
        <span class="search-result-meta">${r.meta}</span>
      </button>`
  ).join('');

  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal wf-modal-wide" role="dialog">
      <div class="wf-modal-header">
        <h3>Search</h3>
        <p>Events, bills, appointments, tasks and trips</p>
      </div>
      <div class="wf-modal-body">
        <label>Search<input type="text" value="dentist" autofocus></label>
        <div class="search-results">${results}</div>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
}

function openLoginPreview() {
  closeModal();
  closeNotif();
  document.getElementById('login-overlay').hidden = false;
}

function closeLoginPreview() {
  document.getElementById('login-overlay').hidden = true;
}

function renderNotifications(notifications, unread) {
  const badge = document.getElementById('notif-badge');
  if (unread > 0) {
    badge.hidden = false;
    badge.textContent = unread;
  } else {
    badge.hidden = true;
  }
  document.getElementById('notif-list').innerHTML = notifications
    .map((n) => `<div class="notif-item${n.read ? '' : ' unread'}">${n.text}<time>${n.time}</time></div>`)
    .join('');
}

function initTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });
}

function initActions() {
  document.addEventListener('click', (e) => {
    const tabLink = e.target.closest('[data-tab-link]');
    if (tabLink) {
      switchTab(tabLink.dataset.tabLink);
      closeModal();
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
    if (action === 'sync-calendar') {
      api('/calendar/sync', { method: 'POST' })
        .then((r) => {
          showToast(`Synced — ${JSON.stringify(r.synced)}`);
          load();
        })
        .catch((err) => showToast(err.message, true));
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
    if (action === 'toggle-task') {
      const taskId = btn.dataset.taskId;
      if (taskId) {
        api(`/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify({ done: true }) })
          .then(() => load())
          .catch((err) => showToast(err.message, true));
      }
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
    if (action === 'save-idea') {
      const ideaId = btn.dataset.ideaId;
      if (ideaId) {
        api(`/holidays/ideas/${ideaId}/toggle`, { method: 'POST' })
          .then(() => load())
          .catch((err) => showToast(err.message, true));
      }
      return;
    }
    showToast(ACTION_MSG[action] || `Coming in Phase 1: ${action.replace(/-/g, ' ')}`);
  });

  document.querySelectorAll('input[name="appt-filter"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      const cat = document.querySelector('#appt-categories .cat-btn.active')?.dataset.apptCat || 'all';
      renderAppointments(store.appointments, radio.value, cat);
    });
  });

  document.getElementById('notif-btn').onclick = () => {
    document.getElementById('notif-panel').hidden = false;
    document.getElementById('notif-backdrop').hidden = false;
  };
  document.getElementById('notif-close').onclick = closeNotif;
  document.getElementById('notif-backdrop').onclick = closeNotif;

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModal();
      closeNotif();
      closeLoginPreview();
    }
  });

  document.getElementById('login-close')?.addEventListener('click', closeLoginPreview);
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
}

function closeNotif() {
  document.getElementById('notif-panel').hidden = true;
  document.getElementById('notif-backdrop').hidden = true;
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
};

let assistantOpen = false;
let assistantBusy = false;
let assistantConfigured = false;
let assistantMessages = [];

function renderAssistantMessages(messages, pending = false) {
  const el = document.getElementById('assistant-messages');
  if (!messages.length && !pending) {
    el.innerHTML = '<div class="assistant-msg system">Try: “Add dinner with Mum next Saturday” or “Help me plan a holiday to Portugal”</div>';
    return;
  }
  el.innerHTML = messages.map((m) => {
    const actions = (m.actions || []).map((a) =>
      `<span class="assistant-action-pill">${esc(TOOL_LABELS[a.tool] || a.tool)}</span>`,
    ).join('');
    return `<div class="assistant-msg ${m.role}">${esc(m.content)}${actions ? `<div class="assistant-actions">${actions}</div>` : ''}</div>`;
  }).join('');
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

async function load() {
  try {
    const me = await api('/auth/me');
    currentUser = me.user;
    hideLogin();
  } catch {
    showLogin();
    return;
  }

  const [dashboard, calendar, finances, appointments, holidays, documents, settings] = await Promise.all([
    api('/dashboard'),
    api('/calendar'),
    api('/finances'),
    api('/appointments'),
    api('/holidays'),
    api('/documents'),
    api('/settings'),
  ]);

  store = { dashboard, calendar, finances, appointments, holidays, documents, settings };

  renderMembers(dashboard.users);
  renderWelcome(dashboard);
  renderActionGrid();
  renderReminders(dashboard.reminders);
  renderHome(dashboard);
  renderCalendar(calendar);
  renderFinances(finances);
  renderAppointments(appointments);
  renderHolidays(holidays);
  renderDocuments(documents);
  renderSettings(settings);
  renderNotifications(settings.notifications || [], dashboard.notifications_unread);
  await refreshAssistantStatus();
}

async function boot() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('google_connected')) {
    showToast('Google Calendar connected');
    window.history.replaceState({}, '', '/');
  }
  if (params.get('google_error')) {
    showToast('Google connection failed — check .env credentials', true);
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
