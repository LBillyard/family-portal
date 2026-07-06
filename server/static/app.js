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
let mediaFilter = 'all';
let tripFilter = 'all';
let calView = 'month';
let calCursor = null;
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

function userColour(users, id) {
  return users.find((u) => u.id === id)?.colour || '#718096';
}
function userName(users, id) {
  return esc(users.find((u) => u.id === id)?.name || id);
}

const MODALS = {
  'add-event': {
    title: 'Add event',
    desc: 'Creates a portal event and optionally syncs to Google Calendar.',
    fields: [
      { label: 'Title', type: 'text', placeholder: 'e.g. Date night' },
      { label: 'Date', type: 'date', value: '' },
      { label: 'Time', type: 'time', value: '19:00' },
      { label: 'Assigned to', type: 'select', options: ['Luke', 'Laura', 'Both'] },
      { label: 'Location', type: 'text', value: '' },
    ],
  },
  'log-expense': {
    title: 'Log transaction',
    desc: 'Manual income or expense entry.',
    fields: [
      { label: 'Description', type: 'text', placeholder: 'e.g. Weekly shop' },
      { label: 'Amount (£)', type: 'number', value: '' },
      { label: 'Category', type: 'select', options: ['Groceries', 'Transport', 'Eating out', 'Income'] },
      { label: 'Account', type: 'select', options: ['Joint current', 'Luke personal', 'Partner personal'] },
      { label: 'Date', type: 'date', value: '2026-07-05' },
    ],
  },
  'add-bill': {
    title: 'Add recurring bill',
    desc: 'Track monthly or annual payments.',
    fields: [
      { label: 'Bill name', type: 'text', placeholder: 'e.g. Spotify' },
      { label: 'Amount (£)', type: 'number', value: '' },
      { label: 'Due day of month', type: 'number', value: '1' },
      { label: 'Category', type: 'select', options: ['Utilities', 'Subscriptions', 'Housing', 'Transport'] },
    ],
  },
  'add-appointment': {
    title: 'New appointment',
    desc: 'Health, dental, car MOT, vet — with optional calendar sync.',
    fields: [
      { label: 'Title', type: 'text', placeholder: 'e.g. GP appointment' },
      { label: 'Provider', type: 'text', placeholder: 'e.g. Oakwood Medical' },
      { label: 'Date & time', type: 'datetime-local', value: '' },
      { label: 'Category', type: 'select', options: ['Health', 'Dental', 'Car', 'Vet'] },
      { label: 'Remind me (days before)', type: 'number', value: '2' },
    ],
  },
  'add-task': {
    title: 'Add shared task',
    desc: 'Household to-do assigned to one or both of you.',
    fields: [
      { label: 'Task', type: 'text', placeholder: 'e.g. Book airport parking' },
      { label: 'Assign to', type: 'select', options: ['Luke', 'Laura', 'Either'] },
      { label: 'Due date', type: 'date', value: '2026-07-10' },
      { label: 'Priority', type: 'select', options: ['High', 'Medium', 'Low'] },
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

// Actions still awaiting a real implementation — trimmed batch by batch.
const ACTION_MSG = {
  transfer: 'Transfer between accounts — coming next',
  'export-transactions': 'CSV export — coming next',
  'sync-appointments': 'Appointment → calendar sync — coming next',
  'compare-trips': 'Trip comparison — coming next',
  'edit-trip': 'Edit trip — coming next',
  'edit-member': 'Edit member — coming next',
};

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
      return `<label>${f.label}<input type="${f.type}" value="${f.value || ''}" placeholder="${f.placeholder || ''}"></label>`;
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

  // Drive the account picker from real accounts so IDs always resolve
  if (key === 'log-expense') {
    const accountLabel = [...document.querySelectorAll('.wf-modal label')].find((l) => l.textContent.trim().startsWith('Account'));
    const sel = accountLabel?.querySelector('select');
    const accounts = (store.finances?.accounts || []).filter((a) => a.type === 'current' || a.type === 'savings');
    if (sel && accounts.length) {
      sel.innerHTML = accounts.map((a) => `<option>${esc(a.name)}</option>`).join('');
    }
  }
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
          user_id: assignee.includes('laura') ? 'partner' : 'luke',
          location: f['Location'] || null,
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
          assignee_id: assignee.includes('laura') ? 'partner' : 'luke',
          due: f['Due date'] || null,
          priority: (f['Priority'] || 'medium').toLowerCase(),
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
        <button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="et-save">Save</button>
      </div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
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
        <label class="field field-full"><span>Colour</span><input type="color" id="em-colour" value="${user.colour || '#00a89e'}"></label>
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
          `<span class="member-chip"><span class="member-dot" style="background:${esc(u.colour)}"></span>${esc(u.name)}${u.google_connected ? ' · Google ✓' : ''}</span>`
      )
      .join('');
  }

  document.getElementById('cal-filters').innerHTML = users
    .map(
      (u) =>
        `<label class="filter-chip"><input type="checkbox" checked><span style="display:inline-flex;align-items:center;gap:6px"><span class="member-dot" style="background:${esc(u.colour)}"></span>${esc(u.name)}</span></label>`
    )
    .join('') + '<label class="filter-chip"><input type="checkbox" checked><span>Shared</span></label>';
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

function renderHome(data) {
  const { users, upcoming_events, upcoming_bills, upcoming_appointments, next_holiday, finance_summary, tasks, documents } = data;

  document.getElementById('home-stats').innerHTML = `
    <div class="stat"><span>${upcoming_events.length}</span><label>Events this week</label><div class="stat-trend up">${upcoming_events.filter((e) => e.source === 'google').length} from Google</div></div>
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
          <div class="list-item-title">${esc(e.title)}</div>
          <div class="list-item-meta">${fmt.date(e.start)} · ${userName(users, e.user_id)}${e.location ? ` · ${esc(e.location)}` : ''}
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
        <div class="task-title">${esc(t.title)}</div>
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
        <div class="list-item-title">${esc(b.name)}</div>
        <div class="list-item-meta">Due ${b.due_day} ${esc(b.recurrence)} · ${esc(b.category)}</div>
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
        <div class="list-item-title">${esc(a.title)}</div>
        <div class="list-item-meta">${esc(a.provider)} · ${fmt.time(a.datetime)}</div>
      </div>
    </div>`
    )
    .join('');

  if (next_holiday) {
    const done = next_holiday.checklist?.filter((c) => c.done).length || 0;
    const total = next_holiday.checklist?.length || 0;
    document.getElementById('home-holiday').innerHTML = `
      <div class="holiday-countdown">${next_holiday.days_until} days</div>
      <p style="font-size:1rem;font-weight:600;color:var(--navy-900);margin:8px 0 4px">${esc(next_holiday.title)}</p>
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
          <div class="list-item-title">${esc(d.name)}</div>
          <div class="list-item-meta">${esc(DOC_CATEGORY_LABELS[d.category] || d.category)}${d.expiry ? ' · ' + fmt.date(d.expiry) : ''}${d.has_file ? ' · 📎' : ''}</div>
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
  document.getElementById('modal-root').innerHTML = `
    <div class="modal-backdrop" id="modal-backdrop"></div>
    <div class="wf-modal" role="dialog">
      <div class="wf-modal-header" style="border-left:5px solid ${colour};padding-left:14px">
        <h3>${esc(e.title)}</h3><p>${e.source === 'google' ? 'From Google Calendar' : 'Portal event'}</p>
      </div>
      <div class="wf-modal-body ev-detail">${rows.join('')}</div>
      <div class="wf-modal-footer"><button type="button" class="btn btn-secondary wf-action" data-action="close-modal">Close</button></div>
    </div>`;
  document.getElementById('modal-backdrop').onclick = closeModal;
}

function renderCalendar(data) {
  const { users, events } = data;
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
          (c) => `
        <div class="connection-row">
          <div class="connection-info">
            <div class="connection-icon">🏦</div>
            <div>
              <div class="connection-name">${esc(c.provider_name)}</div>
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
    .map(
      (b) => `
    <div class="list-item${b.paid ? ' bill-paid' : ''}">
      <div class="list-item-body">
        <div class="list-item-title">${esc(b.name)}</div>
        <div class="list-item-meta">Day ${b.due_day} · ${esc(b.category)}${b.paid ? ' · ✓ Paid' : ''}</div>
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
          <span>${esc(b.category)}</span>
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
        <h4>${esc(g.name)}</h4>
        <div class="savings-amounts"><strong>${fmt.gbp(g.current)}</strong><span>of ${fmt.gbp(g.target)}</span></div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${g.colour}"></div></div>
      </div>`;
    })
    .join('');

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
      <td>${esc(t.account)}</td>
      <td class="amount-cell ${t.amount >= 0 ? 'positive' : 'negative'}">${fmt.gbp(t.amount)}</td>
    </tr>`;
    })
    .join('');

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
    .join('');
}

function renderHolidays(data, filter = tripFilter) {
  const { trips, ideas } = data;
  const shownTrips = filter === 'all' ? trips : trips.filter((t) => t.status === filter);

  document.getElementById('holiday-trips').innerHTML = shownTrips.length
    ? shownTrips
    .map((t) => {
      const checklist = (t.checklist || [])
        .map((c) => `<li class="${c.done ? 'done' : ''}"><span class="checklist-box">${c.done ? '✓' : ''}</span>${esc(c.label)}</li>`)
        .join('');
      const bookings = (t.bookings || [])
        .map((b) => `<a href="#" class="booking-link wf-action" data-action="view-booking"><span>${b.type}: ${b.ref}</span><span>→</span></a>`)
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
          ${bookings ? `<div class="booking-links">${bookings}</div>` : ''}
          <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
            <button class="btn btn-sm btn-primary wf-action" data-action="view-trip" data-trip-id="${t.id}">Details</button>
            <button class="btn btn-sm btn-soft wf-action" data-action="add-packing" data-trip-id="${t.id}" data-template="beach">Packing</button>
            <button class="btn btn-sm btn-soft wf-action" data-tab-link="media" data-media-trip="${t.id}">Photos</button>
            <button class="btn btn-sm btn-outline wf-action" data-action="edit-trip" data-trip-id="${t.id}">Edit</button>
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
          <span class="vault-cat-pill">${esc(DOC_CATEGORY_LABELS[d.category] || d.category)}</span>
          <span class="status-tag ${docStatusClass(d.status)}">${docStatusLabel(d.status)}</span>
        </div>
        <h3 class="vault-card-title">${esc(d.name)}</h3>
        ${d.notes ? `<p class="vault-card-notes">${esc(d.notes)}</p>` : ''}
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

function renderMedia(data, filter = mediaFilter) {
  const { items = [], trips = [] } = data;
  const filtered =
    filter === 'all' ? items : filter === 'none' ? items.filter((m) => !m.trip_id) : items.filter((m) => m.trip_id === filter);
  const photos = items.filter((m) => m.media_type === 'photo').length;
  const videos = items.filter((m) => m.media_type === 'video').length;
  const linked = items.filter((m) => m.trip_id).length;

  const tripSelect = document.getElementById('media-trip-select');
  if (tripSelect) {
    tripSelect.innerHTML =
      '<option value="">No trip</option>' +
      trips.map((t) => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
  }

  document.getElementById('media-stats').innerHTML = `
    <div class="stat"><span>${items.length}</span><label>Total items</label></div>
    <div class="stat"><span>${photos}</span><label>Photos</label></div>
    <div class="stat"><span>${videos}</span><label>Videos</label></div>
    <div class="stat"><span>${linked}</span><label>Linked to trips</label></div>`;

  document.getElementById('media-filters').innerHTML =
    `<button class="filter-chip-btn wf-action ${filter === 'all' ? 'active' : ''}" data-media-trip="all">All</button>` +
    `<button class="filter-chip-btn wf-action ${filter === 'none' ? 'active' : ''}" data-media-trip="none">Unlinked</button>` +
    trips
      .map(
        (t) =>
          `<button class="filter-chip-btn wf-action ${filter === t.id ? 'active' : ''}" data-media-trip="${t.id}">${esc(t.title)}</button>`
      )
      .join('');

  document.getElementById('media-grid').innerHTML = filtered.length
    ? filtered
        .map((m) => {
          const fileUrl = m.has_file ? `/api/media/${m.id}/file` : '';
          const preview =
            m.media_type === 'photo' && fileUrl
              ? `<img class="media-thumb" src="${fileUrl}" alt="${esc(m.title)}" loading="lazy">`
              : `<div class="media-thumb media-thumb-video"><span>▶</span><small>Video</small></div>`;
          return `
      <article class="media-card">
        <a href="${fileUrl || '#'}" class="media-preview" target="_blank" rel="noopener"${fileUrl ? '' : ' aria-disabled="true"'}>
          ${preview}
        </a>
        <div class="media-card-body">
          <h3 class="media-card-title">${esc(m.title)}</h3>
          ${m.trip_title ? `<span class="media-trip-pill">${esc(m.trip_title)}</span>` : ''}
          ${m.caption ? `<p class="media-card-caption">${esc(m.caption)}</p>` : ''}
          <div class="media-card-meta">
            ${m.taken_at ? `<span>${fmt.date(m.taken_at)}</span>` : ''}
            ${m.has_file ? `<span>${fmt.fileSize(m.file_size)}</span>` : ''}
          </div>
          <div class="media-card-actions">
            ${fileUrl ? `<a class="btn btn-sm btn-soft" href="${fileUrl}" target="_blank" rel="noopener">View</a>` : ''}
            <button class="btn btn-sm btn-ghost wf-action" data-action="delete-media" data-media-id="${m.id}">Delete</button>
          </div>
        </div>
      </article>`;
        })
        .join('')
    : `<div class="vault-empty"><p>No photos or videos yet.</p><p class="hint-small">Upload family memories and link them to your holidays.</p></div>`;
}

function subscriptionStatusLabel(status) {
  if (status === 'confirmed') return 'Confirmed';
  if (status === 'ignored') return 'Hidden';
  return 'Detected';
}

function frequencyLabel(freq) {
  return { monthly: 'Monthly', weekly: 'Weekly', yearly: 'Yearly', quarterly: 'Quarterly' }[freq] || freq;
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
            <span>${frequencyLabel(s.frequency)}</span>
            <span>${s.occurrence_count} charges found</span>
            ${s.account ? `<span>${esc(s.account)}</span>` : ''}
          </div>
          ${s.next_expected_date ? `<div class="subscription-next">Next expected: ${fmt.date(s.next_expected_date)}</div>` : ''}
        </div>
        <div class="subscription-amount">${fmt.gbp(s.amount)}</div>
        <div class="subscription-actions">
          ${s.status !== 'confirmed' ? `<button class="btn btn-sm btn-primary wf-action" data-action="confirm-subscription" data-sub-id="${s.id}">Confirm</button>` : ''}
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

function renderMaintenance(data) {
  const items = data?.items || [];
  document.getElementById('maintenance-list').innerHTML = items.length
    ? items.map((m) => `
      <div class="maintenance-row">
        <div>
          <strong>${esc(m.title)}</strong>
          <div class="subscription-meta"><span>${esc(m.category)}</span>${m.vendor ? `<span>${esc(m.vendor)}</span>` : ''}${m.next_due_date ? `<span>Due ${fmt.date(m.next_due_date)}</span>` : ''}</div>
          ${m.notes ? `<p class="hint-small">${esc(m.notes)}</p>` : ''}
        </div>
        <div class="subscription-actions">
          <button class="btn btn-sm btn-primary wf-action" data-action="maintenance-done" data-maint-id="${m.id}">Mark done</button>
        </div>
      </div>`).join('')
    : '<div class="vault-empty"><p>No maintenance items yet.</p></div>';
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
          <div class="subscription-meta"><span>${x.source}</span><span>${x.frequency || 'monthly'}</span>${x.amount_note ? `<span>${esc(x.amount_note)}</span>` : ''}</div>
        </div>
        <div class="subscription-amount">${fmt.gbp(x.amount)}</div>
      </div>`).join('')
    : '<p class="hint-small">No recurring items yet.</p>';
}

async function openTripDetailModal(tripId) {
  try {
    const trip = await api(`/holidays/trips/${tripId}`);
    const timeline = (trip.timeline || []).map((day) => `
      <div class="timeline-day">
        <strong>${esc(day.label)}</strong>
        ${day.media?.length ? day.media.map((m) => `<span class="media-trip-pill">${esc(m.title)}</span>`).join(' ') : '<span class="hint-small">No media</span>'}
      </div>`).join('');
    const packing = (trip.packing || []).map((p) => `<li class="${p.done ? 'done' : ''}">${esc(p.label)}</li>`).join('');
    const docs = (trip.linked_documents || []).map((d) => `<li>${esc(d.name)} (${esc(d.category)})</li>`).join('');
    const docOptions = (store.documents?.documents || [])
      .map((d) => `<option value="${d.id}">${esc(d.name)}</option>`)
      .join('');
    document.getElementById('modal-root').innerHTML = `
      <div class="modal-backdrop" id="modal-backdrop"></div>
      <div class="wf-modal wf-modal-wide" role="dialog">
        <div class="wf-modal-header"><h3>${esc(trip.title)}</h3><p>Trip timeline, packing &amp; travel documents</p></div>
        <div class="wf-modal-body">
          <h4>Timeline</h4>${timeline || '<p class="hint-small">Add dates and photos to build a timeline.</p>'}
          <h4 style="margin-top:16px">Packing</h4><ul class="checklist">${packing || '<li>Add packing list from trip card</li>'}</ul>
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

  document.getElementById('settings-content').innerHTML = `
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
      <h3>Login &amp; access</h3>
      <p>Change your password or preview the login screen.</p>
      <button class="btn btn-primary wf-action" data-action="change-password">Change password</button>
      <button class="btn btn-outline wf-action" data-action="preview-login" style="margin-left:8px">Preview login screen</button>
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
        ? results.map((r) => `
          <button type="button" class="search-result wf-action" data-tab-link="${r.tab}">
            <span class="search-result-type">${esc(r.type)}</span>
            <strong>${esc(r.label)}</strong>
            <span class="search-result-meta">${esc(r.meta || '')}</span>
          </button>`).join('')
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
  document.getElementById('login-overlay').hidden = false;
}

function closeLoginPreview() {
  document.getElementById('login-overlay').hidden = true;
}

function renderNotifications(reminders, unread) {
  const badge = document.getElementById('notif-badge');
  if (unread > 0) {
    badge.hidden = false;
    badge.textContent = unread;
  } else {
    badge.hidden = true;
  }
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
            load();
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
    if (action === 'view-trip') {
      const tripId = btn.dataset.tripId;
      if (tripId) openTripDetailModal(tripId);
      return;
    }
    if (action === 'add-packing') {
      const tripId = btn.dataset.tripId;
      const template = btn.dataset.template || 'beach';
      if (tripId) {
        api(`/holidays/trips/${tripId}/packing`, { method: 'POST', body: JSON.stringify({ template }) })
          .then(() => {
            showToast('Packing list added');
            load();
          })
          .catch((err) => showToast(err.message, true));
      }
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
    if (action === 'scan-receipt') {
      document.getElementById('receipt-file-input')?.click();
      return;
    }
    if (action === 'send-reminders') {
      api('/notifications/send-reminders', { method: 'POST' })
        .then((r) => {
          if (r.sent) showToast(`Sent reminder for ${r.count} item(s)`);
          else showToast(r.reason || 'No reminders sent');
        })
        .catch((err) => showToast(err.message, true));
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
    showToast(ACTION_MSG[action] || `Coming in Phase 1: ${action.replace(/-/g, ' ')}`);
  });

  document.querySelectorAll('input[name="appt-filter"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      const cat = document.querySelector('#appt-categories .cat-btn.active')?.dataset.apptCat || 'all';
      renderAppointments(store.appointments, radio.value, cat);
    });
  });

  // Recategorise a transaction (and learn the merchant) when its dropdown changes
  document.addEventListener('change', (e) => {
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
  };
  document.getElementById('notif-close').onclick = closeNotif;
  document.getElementById('notif-backdrop').onclick = closeNotif;

  document.getElementById('weather-btn').onclick = openWeather;
  document.getElementById('weather-close').onclick = closeWeather;
  document.getElementById('weather-backdrop').onclick = closeWeather;

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModal();
      closeNotif();
      closeWeather();
      closeLoginPreview();
    }
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

  document.getElementById('media-upload-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const fileInput = form.querySelector('input[name="file"]');
    const file = fileInput?.files?.[0];
    if (!file) {
      showToast('Choose a photo or video', true);
      return;
    }
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', form.title.value.trim());
    formData.append('caption', form.caption.value.trim());
    formData.append('trip_id', form.trip_id.value);
    formData.append('taken_at', form.taken_at.value);
    try {
      showToast('Uploading…');
      const res = await fetch(`${API}/media/upload`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Upload failed');
      }
      form.reset();
      showToast('Media uploaded');
      switchTab('media');
      await load();
    } catch (err) {
      showToast(err.message, true);
    }
  });

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

  const [dashboard, calendar, finances, appointments, holidays, documents, media, subscriptions, settings, briefing, activity, renewals, maintenance] = await Promise.all([
    api('/dashboard'),
    api('/calendar'),
    api('/finances'),
    api('/appointments'),
    api('/holidays'),
    api('/documents'),
    api('/media'),
    api('/subscriptions'),
    api('/settings'),
    api('/briefing'),
    api('/activity'),
    api('/renewals'),
    api('/maintenance'),
  ]);

  store = { dashboard, calendar, finances, appointments, holidays, documents, media, subscriptions, settings, briefing, activity, renewals, maintenance };

  renderMembers(dashboard.users);
  renderWelcome(dashboard);
  renderBriefing(briefing);
  renderActionGrid();
  renderReminders(dashboard.reminders);
  renderHome(dashboard);
  renderActivityFeed(activity);
  renderCalendar(calendar);
  renderFinances(finances);
  renderRenewals(renewals);
  renderMaintenance(maintenance);
  renderAppointments(appointments);
  renderHolidays(holidays);
  renderMedia(media);
  renderSubscriptions(subscriptions);
  renderDocuments(documents);
  renderSettings(settings);
  renderNotifications(dashboard.reminders || [], dashboard.notifications_unread);
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
