const feedback = document.querySelector('#loginFeedback');
const legacyChooser = document.querySelector('#legacyChooser');
const magicLinkPanel = document.querySelector('#magicLinkPanel');
const verificationPanel = document.querySelector('#verificationPanel');
const passwordPanel = document.querySelector('#passwordPanel');
const passwordToggle = document.querySelector('#passwordToggle');
const loginTitle = document.querySelector('#loginTitle');
const loginDescription = document.querySelector('.login-copy p:last-child');
const emailInput = document.querySelector('#magicLinkEmail');
const codeInput = document.querySelector('#magicLinkCode');
const passwordEmailInput = document.querySelector('#passwordEmail');
const passwordInput = document.querySelector('#passwordInput');
let hostedConfig = null;
let passwordMode = false;

function showFeedback(message) {
  feedback.textContent = message;
  feedback.classList.remove('is-hidden');
}

function setButtonLabel(form, label) {
  const span = form.querySelector('button[type="submit"] span');
  if (span) span.textContent = label;
}

async function supabaseAuth(path, payload) {
  const response = await fetch(`${hostedConfig.supabase_url}${path}`, {
    method: 'POST',
    headers: { apikey: hostedConfig.supabase_publishable_key, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.msg || body.message || body.error_description || 'Authentication request failed.');
  return body;
}

async function establishHostedSession(accessToken) {
  const response = await fetch('/api/auth/session', {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: '{}',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || 'Could not start Hearthstate session.');
  window.location.assign(payload.households?.length ? '/' : '/setup');
}

async function consumeMagicLink(token) {
  const response = await fetch('/api/auth/sign-in', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'This sign-in link is no longer valid');
  window.location.assign('/');
}

document.querySelectorAll('[data-user]').forEach((button) => {
  button.addEventListener('click', async () => {
    document.querySelectorAll('[data-user]').forEach((choice) => { choice.disabled = true; });
    feedback.classList.add('is-hidden');
    try {
      const response = await fetch('/api/session', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user: button.dataset.user }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not start Hearthstate session');
      window.location.assign('/');
    } catch (error) {
      showFeedback(error.message);
      document.querySelectorAll('[data-user]').forEach((choice) => { choice.disabled = false; });
    }
  });
});

magicLinkPanel.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submitButton = magicLinkPanel.querySelector('button[type="submit"]');
  const email = emailInput.value.trim();
  feedback.classList.add('is-hidden');
  submitButton.disabled = true;
  setButtonLabel(magicLinkPanel, 'Sending…');
  let requestSucceeded = false;
  try {
    if (hostedConfig?.hosted) {
      await supabaseAuth('/auth/v1/otp', { email, create_user: true });
      requestSucceeded = true;
      magicLinkPanel.classList.add('is-hidden');
      verificationPanel.classList.remove('is-hidden');
      codeInput.focus();
      showFeedback('Code sent. Check your inbox.');
    } else {
      const response = await fetch('/api/auth/sign-in/request', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not request a sign-in link');
      setButtonLabel(magicLinkPanel, 'Link sent');
      showFeedback('If that email belongs to this household, a sign-in link is on its way.');
    }
  } catch (error) {
    showFeedback(error.message);
  } finally {
    if (!requestSucceeded || !hostedConfig?.hosted) submitButton.disabled = false;
    setButtonLabel(magicLinkPanel, hostedConfig?.hosted ? 'Send code' : 'Send sign-in link');
  }
});

verificationPanel.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submitButton = verificationPanel.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  setButtonLabel(verificationPanel, 'Checking…');
  try {
    const session = await supabaseAuth('/auth/v1/verify', { email: emailInput.value.trim(), token: codeInput.value.trim(), type: 'email' });
    await establishHostedSession(session.access_token);
  } catch (error) {
    showFeedback(error.message);
    submitButton.disabled = false;
    setButtonLabel(verificationPanel, 'Continue');
  }
});

passwordPanel.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submitButton = passwordPanel.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  setButtonLabel(passwordPanel, 'Signing in…');
  try {
    const session = await supabaseAuth('/auth/v1/token?grant_type=password', {
      email: passwordEmailInput.value.trim(),
      password: passwordInput.value,
    });
    if (!session.access_token) throw new Error('Supabase did not return a session.');
    await establishHostedSession(session.access_token);
  } catch (error) {
    showFeedback(error.message);
    submitButton.disabled = false;
    setButtonLabel(passwordPanel, 'Sign in');
  }
});

passwordToggle.addEventListener('click', () => {
  passwordMode = !passwordMode;
  magicLinkPanel.classList.toggle('is-hidden', passwordMode);
  verificationPanel.classList.add('is-hidden');
  passwordPanel.classList.toggle('is-hidden', !passwordMode);
  passwordToggle.textContent = passwordMode ? 'Use email code instead' : 'Use temporary password sign-in';
  feedback.classList.add('is-hidden');
  if (passwordMode) {
    passwordEmailInput.value = emailInput.value.trim();
    passwordEmailInput.focus();
  } else {
    emailInput.focus();
  }
});

(async () => {
  const token = new URLSearchParams(window.location.search).get('token');
  try {
    const response = await fetch('/api/auth/config', { cache: 'no-store' });
    hostedConfig = await response.json();
    if (hostedConfig.hosted) {
      legacyChooser.classList.add('is-hidden');
      magicLinkPanel.classList.remove('is-hidden');
      passwordToggle.classList.remove('is-hidden');
      loginTitle.textContent = 'Sign in to your household';
      loginDescription.textContent = 'Use your email and we will send a secure, one-time code to your inbox.';
      if (token) {
        magicLinkPanel.classList.add('is-hidden');
        await consumeMagicLink(token);
      }
    } else if (hostedConfig.account_backed) {
      legacyChooser.classList.add('is-hidden');
      magicLinkPanel.classList.remove('is-hidden');
      loginTitle.textContent = 'Sign in to your household';
      loginDescription.textContent = 'Use your email and we will send a secure, one-time link to your inbox.';
    }
  } catch (error) {
    if (token) showFeedback(error.message);
  }
})();
