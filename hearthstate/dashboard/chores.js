const elements = {
  themeToggle: document.querySelector('#themeToggle'),
  refresh: document.querySelector('#refreshButton'),
  syncStatus: document.querySelector('#syncStatus'),
  memberSummary: document.querySelector('#memberSummary'),
  memberPicker: document.querySelector('#memberPickerOptions'),
  form: document.querySelector('#choreForm'),
  title: document.querySelector('#choreTitle'),
  cadence: document.querySelector('#choreCadence'),
  nextDue: document.querySelector('#choreNextDue'),
  feedback: document.querySelector('#choreFeedback'),
  list: document.querySelector('#choreList'),
  empty: document.querySelector('#choreEmpty'),
  updatedAt: document.querySelector('#updatedAt'),
  error: document.querySelector('#errorBanner'),
  cancelEdit: document.querySelector('#cancelEdit'),
};

let choreState = [];
let choreMembers = [];
let editingChoreId = null;

const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));

const cadenceLabels = {
  daily: 'Every day',
  weekly: 'Every week',
  fortnightly: 'Every two weeks',
  monthly: 'Every month',
  yearly: 'Every year',
  on_demand: 'Whenever needed',
};

function syncThemeButton() {
  const dark = document.documentElement.dataset.theme === 'dark';
  elements.themeToggle.setAttribute('aria-pressed', String(dark));
  elements.themeToggle.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  elements.themeToggle.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
  elements.themeToggle.textContent = dark ? '☀' : '☾';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#1d1917' : '#f3ede3';
}

function formatDue(value) {
  if (!value) return 'No date set';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'No date set';
  return new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date);
}

function localInputToIso(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function isoToLocalInput(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function renderMembers(members, selected = new Set()) {
  elements.memberSummary.textContent = members.length ? `${members.length} household member${members.length === 1 ? '' : 's'}` : 'Add household members to rotate';
  elements.memberPicker.innerHTML = members.length
    ? members.map((member) => `
      <label class="member-option">
        <input type="checkbox" name="participants" value="${escapeHTML(member.id)}" ${selected.has(String(member.id)) ? 'checked' : ''} />
        <span class="member-option-mark" aria-hidden="true">✓</span>
        <span><strong>${escapeHTML(member.display_name || 'Household member')}</strong><small>${escapeHTML(member.role || 'member')}</small></span>
      </label>
    `).join('')
    : '<p class="form-help">No household members are available yet.</p>';
}

function renderChores(chores) {
  choreState = chores;
  elements.list.innerHTML = chores.map((chore) => {
    const nextAssignee = chore.next_assignee_label || 'Unassigned';
    const participantLabels = (chore.participant_labels || []).join(' · ') || 'No members selected';
    const assignDisabled = !chore.next_assignee;
    return `
      <article class="chore-card">
        <div class="chore-card-top"><div><span class="section-kicker">${escapeHTML(cadenceLabels[chore.cadence] || chore.cadence || 'Routine')}</span><h3>${escapeHTML(chore.title)}</h3></div><span class="rotation-mark" aria-hidden="true">↻</span></div>
        <div class="chore-card-meta"><span><strong>Next</strong>${escapeHTML(nextAssignee)}</span><span><strong>Due</strong>${escapeHTML(formatDue(chore.next_due_at))}</span></div>
        <div class="chore-card-footer"><span class="participant-line">${escapeHTML(participantLabels)}</span><div class="chore-card-actions"><button class="secondary-action edit-chore" type="button" data-chore-id="${escapeHTML(chore.id)}">Edit</button><button class="secondary-action assign-next" type="button" data-chore-id="${escapeHTML(chore.id)}" ${assignDisabled ? 'disabled' : ''}>Assign next <span aria-hidden="true">↗</span></button></div></div>
      </article>
    `;
  }).join('');
  elements.list.classList.toggle('is-hidden', chores.length === 0);
  elements.empty.classList.toggle('is-hidden', chores.length !== 0);
  elements.list.querySelectorAll('.edit-chore').forEach((button) => button.addEventListener('click', () => startEdit(button)));
  elements.list.querySelectorAll('.assign-next').forEach((button) => button.addEventListener('click', () => assignNext(button)));
}

async function loadChores() {
  elements.syncStatus.textContent = 'Refreshing';
  elements.refresh.disabled = true;
  try {
    const response = await hearthstateFetch('/api/chores', { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not load chores');
    const selected = new Set([...document.querySelectorAll('input[name="participants"]:checked')].map((input) => input.value));
    choreMembers = payload.members || [];
    renderMembers(choreMembers, selected);
    renderChores(payload.chores || []);
    elements.updatedAt.textContent = payload.generated_at ? `UPDATED ${formatDue(payload.generated_at).toUpperCase()}` : 'UPDATED JUST NOW';
    elements.syncStatus.textContent = 'Live snapshot';
    elements.error.classList.add('is-hidden');
  } catch (error) {
    elements.syncStatus.textContent = 'Needs attention';
    elements.error.textContent = error.message;
    elements.error.classList.remove('is-hidden');
  } finally {
    elements.refresh.disabled = false;
  }
}

async function saveChore(event) {
  event.preventDefault();
  const participants = [...document.querySelectorAll('input[name="participants"]:checked')].map((input) => input.value);
  if (!participants.length) {
    elements.feedback.textContent = 'Choose at least one household member for this rotation.';
    elements.feedback.classList.remove('is-hidden');
    return;
  }
  const payload = {
    title: elements.title.value.trim(),
    cadence: elements.cadence.value,
    participants,
    next_due_at: localInputToIso(elements.nextDue.value),
  };
  const button = elements.form.querySelector('button[type="submit"]');
  const isEditing = Boolean(editingChoreId);
  button.disabled = true;
  try {
    const endpoint = isEditing ? `/api/chores/${encodeURIComponent(editingChoreId)}/edit` : '/api/chores';
    const response = await hearthstateFetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save chore');
    elements.form.reset();
    editingChoreId = null;
    elements.cancelEdit.classList.add('is-hidden');
    button.textContent = 'Save chore ↗';
    renderMembers(choreMembers, new Set());
    elements.feedback.textContent = isEditing ? 'Chore updated. Existing assignments and history were left unchanged.' : 'Chore saved. The rotation is ready for its first assignment.';
    elements.feedback.classList.remove('is-hidden');
    await loadChores();
  } catch (error) {
    elements.feedback.textContent = error.message;
    elements.feedback.classList.remove('is-hidden');
  } finally {
    button.disabled = false;
  }
}

function startEdit(button) {
  const chore = choreState.find((item) => String(item.id) === String(button.dataset.choreId));
  if (!chore) return;
  editingChoreId = chore.id;
  elements.title.value = chore.title || '';
  elements.cadence.value = chore.cadence || 'weekly';
  elements.nextDue.value = chore.next_due_at ? isoToLocalInput(chore.next_due_at) : '';
  renderMembers(choreMembers, new Set((chore.participants || []).map(String)));
  elements.cancelEdit.classList.remove('is-hidden');
  elements.form.querySelector('button[type="submit"]').textContent = 'Update chore ↗';
  elements.feedback.textContent = 'Editing future rotation settings. Existing assignments stay as they are.';
  elements.feedback.classList.remove('is-hidden');
  elements.title.focus();
}

function cancelEdit() {
  editingChoreId = null;
  elements.form.reset();
  elements.cancelEdit.classList.add('is-hidden');
  elements.form.querySelector('button[type="submit"]').textContent = 'Save chore ↗';
  renderMembers(choreMembers, new Set());
  elements.feedback.classList.add('is-hidden');
}

async function assignNext(button) {
  const choreId = button.dataset.choreId;
  button.disabled = true;
  button.textContent = 'Assigning…';
  try {
    const response = await hearthstateFetch(`/api/chores/${encodeURIComponent(choreId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not assign chore');
    elements.feedback.textContent = `Assigned “${payload.task?.title || 'chore'}” to the next person in the rotation.`;
    elements.feedback.classList.remove('is-hidden');
    await loadChores();
  } catch (error) {
    elements.error.textContent = error.message;
    elements.error.classList.remove('is-hidden');
    button.disabled = false;
    button.textContent = 'Assign next ↗';
  }
}

elements.themeToggle.addEventListener('click', () => {
  document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('hearthstate-theme', document.documentElement.dataset.theme); } catch (error) {}
  syncThemeButton();
});
elements.refresh.addEventListener('click', loadChores);
elements.form.addEventListener('submit', saveChore);
elements.cancelEdit.addEventListener('click', cancelEdit);
syncThemeButton();
loadChores();
