const params = new URLSearchParams(window.location.search);
const token = params.get('token') || '';
const form = document.querySelector('#inviteForm');
const summary = document.querySelector('#inviteSummary');
const feedback = document.querySelector('#inviteFeedback');

function showError(message) {
  feedback.textContent = message;
  feedback.classList.remove('is-hidden');
  form.classList.add('is-hidden');
}

async function inspect() {
  if (!token) {
    showError('This invitation link is incomplete. Ask the household owner for a new link.');
    return;
  }
  const response = await fetch(`/api/auth/invitations/inspect?token=${encodeURIComponent(token)}`, { cache: 'no-store' });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'This invitation is no longer available.');
  const invitation = payload.invitation;
  summary.textContent = `You have been invited to ${invitation.household_name} as a ${invitation.role}.`;
}

inspect().catch((error) => showError(error.message));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  feedback.classList.add('is-hidden');
  form.querySelector('button').disabled = true;
  try {
    const response = await fetch('/api/auth/invitations/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, display_name: document.querySelector('#displayName').value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not accept invitation.');
    window.location.assign('/');
  } catch (error) {
    feedback.textContent = error.message;
    feedback.classList.remove('is-hidden');
    form.querySelector('button').disabled = false;
  }
});
