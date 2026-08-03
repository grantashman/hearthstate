const params = new URLSearchParams(window.location.search);
const token = params.get('token') || '';
const form = document.querySelector('#inviteForm');
const summary = document.querySelector('#inviteSummary');
const feedback = document.querySelector('#inviteFeedback');
const emailField = document.querySelector('#inviteEmail');
const codeWrap = document.querySelector('#inviteCodeWrap');
const codeField = document.querySelector('#inviteCode');
const sendCodeButton = document.querySelector('#sendInviteCode');
let config = null;
let invitation = null;
let codeSent = false;

function showError(message) {
  feedback.textContent = message;
  feedback.classList.remove('is-hidden');
  form.classList.add('is-hidden');
}

function showMessage(message) {
  feedback.textContent = message;
  feedback.classList.remove('is-hidden');
}

async function inspect() {
  if (!token) throw new Error('This invitation link is incomplete. Ask the household owner for a new link.');
  const response = await fetch(`/api/auth/invitations/inspect?token=${encodeURIComponent(token)}`, { cache: 'no-store' });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'This invitation is no longer available.');
  invitation = payload.invitation;
  emailField.value = invitation.email;
  summary.textContent = `You have been invited to ${invitation.household_name} as a ${invitation.role}.`;
  config = await (await fetch('/api/auth/config', { cache: 'no-store' })).json();
}

async function supabaseAuth(path, payload) {
  const response = await fetch(`${config.supabase_url}${path}`, {
    method: 'POST',
    headers: { apikey: config.supabase_publishable_key, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.msg || body.message || body.error_description || 'Authentication request failed.');
  return body;
}

sendCodeButton.addEventListener('click', async () => {
  sendCodeButton.disabled = true;
  try {
    await supabaseAuth('/auth/v1/otp', { email: invitation.email, create_user: true });
    codeSent = true;
    codeWrap.classList.remove('is-hidden');
    showMessage('Code sent. Check your inbox, then accept the invitation.');
    codeField.focus();
  } catch (error) {
    showMessage(error.message);
    sendCodeButton.disabled = false;
  }
});

inspect().catch((error) => showError(error.message));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  feedback.classList.add('is-hidden');
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    if (!codeSent) throw new Error('Send the sign-in code first.');
    const session = await supabaseAuth('/auth/v1/verify', { email: invitation.email, token: codeField.value.trim(), type: 'email' });
    const response = await fetch('/api/auth/session', { method: 'POST', headers: { Authorization: `Bearer ${session.access_token}`, 'Content-Type': 'application/json' }, body: '{}' });
    const sessionPayload = await response.json();
    if (!response.ok) throw new Error(sessionPayload.error || 'Could not start your Hearthstate session.');
    const accept = await fetch('/api/auth/invitations/accept', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, display_name: document.querySelector('#displayName').value }) });
    const accepted = await accept.json();
    if (!accept.ok) throw new Error(accepted.error || 'Could not accept invitation.');
    window.location.assign('/');
  } catch (error) {
    feedback.textContent = error.message;
    feedback.classList.remove('is-hidden');
    submit.disabled = false;
  }
});
