const section = document.body.dataset.section;
const isCalendar = section === 'calendar';
const els = {
  assignee: document.querySelector('#assigneeSelect'),
  themeToggle: document.querySelector('#themeToggle'),
  refresh: document.querySelector('#refreshButton'),
  syncStatus: document.querySelector('#syncStatus'),
  recordCount: document.querySelector('#recordCount'),
  updatedAt: document.querySelector('#updatedAt'),
  list: document.querySelector('#recordsList'),
  empty: document.querySelector('#emptyState'),
  assignmentSummary: document.querySelector('#assignmentSummary'),
  error: document.querySelector('#errorBanner'),
  addRecord: document.querySelector('#addRecordButton'),
  editor: document.querySelector('#editorForm'),
  cancelEdit: document.querySelector('#cancelEdit'),
  editorTitle: document.querySelector('#editorTitle'),
  editorFeedback: document.querySelector('#editorFeedback'),
  recordId: document.querySelector('#recordId'),
  recordTitle: document.querySelector('#recordTitle'),
  recordStartsAt: document.querySelector('#recordStartsAt'),
  recordPerson: document.querySelector('#recordPerson'),
  recordAssignee: document.querySelector('#recordAssignee'),
  recordRecurrence: document.querySelector('#recordRecurrence'),
};

const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));

function syncThemeButton() {
  const dark = document.documentElement.dataset.theme === 'dark';
  els.themeToggle.setAttribute('aria-pressed', String(dark));
  els.themeToggle.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  els.themeToggle.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
  if (!els.themeToggle.querySelector('.theme-icon')) els.themeToggle.textContent = dark ? '☀' : '☾';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#171e1a' : '#f0f1eb';
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('hearthstate-theme', theme); } catch (error) {}
  syncThemeButton();
}

function formatDate(value, options) {
  return new Intl.DateTimeFormat(undefined, options).format(new Date(value));
}

function formatRelativeDate(value) {
  const date = new Date(value);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === tomorrow.toDateString()) return 'Tomorrow';
  return formatDate(value, { weekday: 'short', month: 'short', day: 'numeric' });
}

function renderAssigneeOptions(members) {
  const current = els.assignee.value;
  const options = [{ id: '', display_name: 'Everyone' }, ...(Array.isArray(members) ? members : [])];
  const optionMarkup = options.map((member) => `<option value="${escapeHTML(member.id)}">${escapeHTML(member.display_name || member.id)}</option>`).join('');
  els.assignee.innerHTML = optionMarkup;
  els.recordAssignee.innerHTML = `<option value="">Unassigned</option>${options.slice(1).map((member) => `<option value="${escapeHTML(member.id)}">${escapeHTML(member.display_name || member.id)}</option>`).join('')}`;
  if (options.some((member) => String(member.id) === String(current))) els.assignee.value = current;
}

function renderCalendar(items) {
  els.list.innerHTML = items.map((item) => `
    <article class="record-row calendar-record">
      <div class="record-date"><strong>${escapeHTML(formatDate(item.starts_at, { day: 'numeric' }))}</strong><span>${escapeHTML(formatDate(item.starts_at, { month: 'short' }).toUpperCase())}</span></div>
      <div class="record-main"><strong>${escapeHTML(item.title)}</strong><span>${escapeHTML(formatRelativeDate(item.starts_at))} · ${escapeHTML(item.time_label)}${item.person ? ` · ${escapeHTML(item.person)}` : ''}${item.source_type === 'task' ? ' · task' : item.source_type === 'meal' ? ' · meal' : ''}${item.recurrence !== 'none' ? ` · ${escapeHTML(item.recurrence_label)}` : ''}</span></div>
      <span class="assignee-chip assignee-${escapeHTML(item.assignee || 'none')}">${escapeHTML(item.assignee_label)}</span>
      <button class="quiet-action edit-record" type="button" data-record-id="${escapeHTML(item.source_id ?? item.id)}" data-record-type="${escapeHTML(item.source_type || 'event')}">Edit</button>
    </article>
  `).join('');
  els.list.querySelectorAll('.edit-record').forEach((button) => {
    button.addEventListener('click', () => {
      const record = items.find((item) => String(item.source_id ?? item.id) === button.dataset.recordId && (item.source_type || 'event') === button.dataset.recordType);
      openEditor(record);
    });
  });
}

function renderTasks(items) {
  els.list.innerHTML = items.map((item) => `
    <article class="record-row task-record">
      <div class="task-mark" aria-hidden="true"></div>
      <div class="record-main"><strong>${escapeHTML(item.title)}</strong><span>${escapeHTML(item.due_label)}${item.recurrence !== 'none' ? ` · ${escapeHTML(item.recurrence_label)}` : ''}${item.private ? ' · private' : ''}</span></div>
      <span class="assignee-chip assignee-${escapeHTML(item.assignee || 'none')}">${escapeHTML(item.assignee_label)}</span>
      <button class="quiet-action edit-record" type="button" data-record-id="${item.id}">Edit</button>
      <div class="task-actions"><button class="quiet-action complete-record" type="button" data-record-id="${item.id}">Done</button><button class="quiet-action delete-record" type="button" data-record-id="${item.id}">Delete</button></div>
    </article>
  `).join('');
  els.list.querySelectorAll('.edit-record').forEach((button) => {
    button.addEventListener('click', () => openEditor(items.find((item) => String(item.id) === String(button.dataset.recordId))));
  });
  els.list.querySelectorAll('.complete-record').forEach((button) => {
    button.addEventListener('click', () => mutateTask(button.dataset.recordId, 'complete'));
  });
  els.list.querySelectorAll('.delete-record').forEach((button) => {
    button.addEventListener('click', () => {
      const task = items.find((item) => String(item.id) === String(button.dataset.recordId));
      if (task && window.confirm(`Delete “${task.title}”? This cannot be undone.`)) mutateTask(task.id, 'delete');
    });
  });
}

async function mutateTask(taskId, action) {
  try {
    const response = await hearthstateFetch(`/api/tasks/${taskId}/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Could not ${action} task`);
    await loadSection();
  } catch (error) {
    els.error.textContent = error.message;
    els.error.classList.remove('is-hidden');
  }
}

function render(payload) {
  const members = Array.isArray(payload.members) ? payload.members : [];
  renderAssigneeOptions(members);
  els.assignmentSummary.textContent = members.length ? members.map((member) => member.display_name || member.id).join(' · ') : 'No household members configured';
  const items = isCalendar ? payload.calendar : payload.tasks;
  els.recordCount.textContent = items.length;
  els.updatedAt.textContent = `UPDATED ${formatDate(payload.generated_at, { hour: 'numeric', minute: '2-digit' }).toUpperCase()}`;
  els.list.classList.toggle('is-hidden', items.length === 0);
  els.empty.classList.toggle('is-hidden', items.length !== 0);
  if (isCalendar) renderCalendar(items); else renderTasks(items);
  els.error.classList.add('is-hidden');
  els.syncStatus.textContent = 'Live snapshot';
}

function openEditor(record = null) {
  if (isCalendar && record?.source_type === 'task') {
    window.location.href = `/tasks?edit=${encodeURIComponent(record.source_id)}`;
    return;
  }
  if (isCalendar && record?.source_type === 'meal') {
    window.location.href = `/meals?date=${encodeURIComponent(record.starts_at.slice(0, 10))}`;
    return;
  }
  els.editor.classList.remove('is-hidden');
  els.editorTitle.textContent = record ? (isCalendar ? 'Edit event' : 'Edit task') : (isCalendar ? 'Add event' : 'Add a task');
  els.editorFeedback.classList.add('is-hidden');
  els.recordId.value = record?.id || '';
  if (isCalendar) {
    els.recordTitle.value = record?.title || '';
    els.recordStartsAt.value = record ? record.starts_at.slice(0, 16) : '';
    els.recordPerson.value = record?.person || '';
    els.recordAssignee.value = record?.assignee || '';
  } else {
    els.recordTitle.value = record?.title || '';
    els.recordStartsAt.value = record?.due_at ? record.due_at.slice(0, 16) : '';
    els.recordAssignee.value = record?.assignee || '';
    els.recordRecurrence.value = record?.recurrence || 'none';
  }
  els.recordTitle.focus();
}

function closeEditor() {
  els.editor.classList.add('is-hidden');
  els.editor.reset();
  if (els.recordId) els.recordId.value = '';
  if (els.recordRecurrence) els.recordRecurrence.value = 'none';
}

async function saveRecord(event) {
  event.preventDefault();
  const body = isCalendar ? {
    id: els.recordId.value ? els.recordId.value : undefined,
    title: els.recordTitle.value.trim(),
    starts_at: els.recordStartsAt.value,
    person: els.recordPerson.value.trim(),
    assignee: els.recordAssignee.value || null,
  } : {
    id: els.recordId.value ? els.recordId.value : undefined,
    title: els.recordTitle.value.trim(),
    due_at: els.recordStartsAt.value || null,
    assignee: els.recordAssignee.value || null,
    recurrence: els.recordRecurrence.value || 'none',
  };
  try {
    const response = await hearthstateFetch(isCalendar ? '/api/calendar' : '/api/tasks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not save');
    closeEditor();
    await loadSection();
  } catch (error) {
    els.editorFeedback.textContent = error.message;
    els.editorFeedback.classList.remove('is-hidden');
  }
}

async function loadSection() {
  els.refresh.classList.add('is-loading');
  els.refresh.disabled = true;
  els.syncStatus.textContent = 'Refreshing';
  try {
    const endpoint = isCalendar ? '/api/calendar' : '/api/tasks';
    const query = new URLSearchParams();
    if (els.assignee.value) query.set('assignee', els.assignee.value);
    const response = await hearthstateFetch(`${endpoint}?${query.toString()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const payload = await response.json();
    render(payload);
    const editId = new URLSearchParams(window.location.search).get('edit');
    const record = editId
      ? (isCalendar
        ? payload.calendar.find((item) => item.source_type === 'event' && String(item.source_id) === editId)
        : payload.tasks.find((item) => String(item.id) === String(editId)))
      : null;
    if (record) {
      history.replaceState({}, '', isCalendar ? '/calendar' : '/tasks');
      openEditor(record);
    }
  } catch (error) {
    els.error.textContent = `Could not load ${isCalendar ? 'the calendar' : 'tasks'}. Is the dashboard server running?`;
    els.error.classList.remove('is-hidden');
    els.syncStatus.textContent = 'Offline';
    console.error(error);
  } finally {
    els.refresh.classList.remove('is-loading');
    els.refresh.disabled = false;
  }
}

els.assignee.addEventListener('change', loadSection);
els.themeToggle.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
els.refresh.addEventListener('click', loadSection);
els.addRecord.addEventListener('click', () => openEditor());
els.cancelEdit.addEventListener('click', closeEditor);
els.editor.addEventListener('submit', saveRecord);
syncThemeButton();
loadSection();
