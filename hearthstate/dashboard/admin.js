const feedback = document.querySelector('#adminFeedback');
const memberList = document.querySelector('#memberList');
const invitationList = document.querySelector('#invitationList');
const invitationEmpty = document.querySelector('#invitationEmpty');
const memberCount = document.querySelector('#memberCount');
const invitationCount = document.querySelector('#invitationCount');
const householdName = document.querySelector('#householdName');
const themeToggle = document.querySelector('#themeToggle');

const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));

const roleLabels = { owner: 'Owner', member: 'Member', child: 'Child', guest: 'Guest' };

function showFeedback(message, kind = 'success') {
  feedback.textContent = message;
  feedback.className = `admin-feedback ${kind === 'error' ? 'is-error' : 'is-success'}`;
}

function hideFeedback() {
  feedback.classList.add('is-hidden');
}

async function api(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function roleOptions(current) {
  return Object.entries(roleLabels).map(([value, label]) => `<option value="${value}" ${value === current ? 'selected' : ''}>${label}</option>`).join('');
}

function renderMembers(members) {
  memberCount.textContent = `${members.length} ${members.length === 1 ? 'person' : 'people'}`;
  memberList.innerHTML = members.map((member) => `
    <article class="admin-record">
      <div class="admin-record-avatar">${escapeHTML((member.display_name || member.id).charAt(0).toUpperCase())}</div>
      <div class="admin-record-copy"><strong>${escapeHTML(member.display_name)}</strong><span>${escapeHTML(member.email || 'No email on file')}</span></div>
      <label class="admin-role-control"><span class="sr-only">Role for ${escapeHTML(member.display_name)}</span><select data-member-role="${escapeHTML(member.id)}">${roleOptions(member.role)}</select></label>
      <button class="text-action admin-remove" type="button" data-remove-member="${escapeHTML(member.id)}" ${member.role === 'owner' ? 'aria-label="Remove owner"' : ''}>Remove</button>
    </article>
  `).join('');
  memberList.querySelectorAll('[data-member-role]').forEach((select) => {
    select.addEventListener('change', () => updateMemberRole(select.dataset.memberRole, select.value));
  });
  memberList.querySelectorAll('[data-remove-member]').forEach((button) => {
    button.addEventListener('click', () => removeMember(button.dataset.removeMember));
  });
}

function statusLabel(status) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function renderInvitations(invitations) {
  const pending = invitations.filter((invitation) => invitation.status === 'pending').length;
  invitationCount.textContent = `${pending} pending`;
  invitationList.innerHTML = invitations.map((invitation) => `
    <article class="admin-record invitation-record">
      <div class="admin-record-avatar invitation-avatar">↗</div>
      <div class="admin-record-copy"><strong>${escapeHTML(invitation.email)}</strong><span>${escapeHTML(roleLabels[invitation.role] || invitation.role)} · expires ${escapeHTML(new Date(invitation.expires_at).toLocaleDateString())}</span></div>
      <span class="admin-status status-${escapeHTML(invitation.status)}">${escapeHTML(statusLabel(invitation.status))}</span>
      ${invitation.status === 'pending' ? `<button class="text-action admin-revoke" type="button" data-revoke-invitation="${escapeHTML(invitation.id)}">Revoke</button>` : ''}
    </article>
  `).join('');
  invitationList.classList.toggle('is-hidden', invitations.length === 0);
  invitationEmpty.classList.toggle('is-hidden', invitations.length !== 0);
  invitationList.querySelectorAll('[data-revoke-invitation]').forEach((button) => {
    button.addEventListener('click', () => revokeInvitation(button.dataset.revokeInvitation));
  });
}

async function loadAdmin() {
  document.querySelector('#adminSyncStatus').textContent = 'Refreshing';
  try {
    const payload = await api('/api/admin');
    householdName.value = payload.household.name;
    renderMembers(payload.members);
    renderInvitations(payload.invitations);
    document.querySelector('#adminSyncStatus').textContent = 'Live snapshot';
    hideFeedback();
  } catch (error) {
    showFeedback(error.message, 'error');
    document.querySelector('#adminSyncStatus').textContent = 'Offline';
  }
}

async function updateMemberRole(accountId, role) {
  try {
    await api(`/api/admin/members/${encodeURIComponent(accountId)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }),
    });
    showFeedback('Member role updated.');
    await loadAdmin();
  } catch (error) {
    showFeedback(error.message, 'error');
    await loadAdmin();
  }
}

async function removeMember(accountId) {
  if (!window.confirm('Remove this person from the household?')) return;
  try {
    await api(`/api/admin/members/${encodeURIComponent(accountId)}/remove`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    showFeedback('Member removed from this household.');
    await loadAdmin();
  } catch (error) {
    showFeedback(error.message, 'error');
  }
}

async function revokeInvitation(invitationId) {
  if (!window.confirm('Revoke this invitation? The link will stop working.')) return;
  try {
    await api(`/api/admin/invitations/${encodeURIComponent(invitationId)}/revoke`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    showFeedback('Invitation revoked.');
    await loadAdmin();
  } catch (error) {
    showFeedback(error.message, 'error');
  }
}

document.querySelector('#settingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const payload = await api('/api/admin/household', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: householdName.value.trim() }),
    });
    householdName.value = payload.household.name;
    showFeedback('Household name saved.');
  } catch (error) {
    showFeedback(error.message, 'error');
  }
});

document.querySelector('#inviteForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const payload = await api('/api/auth/invitations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: document.querySelector('#inviteEmail').value.trim(), role: document.querySelector('#inviteRole').value }),
    });
    const invitation = payload.invitation;
    const link = new URL(invitation.url, window.location.origin).href;
    showFeedback(`Invite created for ${invitation.email}. Copy the one-time link: ${link}`);
    document.querySelector('#inviteForm').reset();
    await loadAdmin();
  } catch (error) {
    showFeedback(error.message, 'error');
  } finally {
    submit.disabled = false;
  }
});

themeToggle.addEventListener('click', () => {
  const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = nextTheme;
  themeToggle.setAttribute('aria-pressed', String(nextTheme === 'dark'));
  themeToggle.setAttribute('aria-label', nextTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  try { localStorage.setItem('hearthstate-theme', nextTheme); } catch (error) { /* no-op */ }
});

themeToggle.setAttribute('aria-pressed', String(document.documentElement.dataset.theme === 'dark'));
loadAdmin();
