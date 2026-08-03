const feedback = document.querySelector('#loginFeedback');
const legacyChooser = document.querySelector('#legacyChooser');
const magicLinkPanel = document.querySelector('#magicLinkPanel');
const loginTitle = document.querySelector('#loginTitle');
const loginDescription = document.querySelector('.login-copy p:last-child');

function showFeedback(message) {
  feedback.textContent = message;
  feedback.classList.remove('is-hidden');
}

async function consumeMagicLink(token) {
  const response = await fetch('/api/auth/sign-in', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: button.dataset.user }),
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
  const email = document.querySelector('#magicLinkEmail').value.trim();
  feedback.classList.add('is-hidden');
  try {
    const response = await fetch('/api/auth/sign-in/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not request a sign-in link');
    showFeedback('If that email belongs to this household, a sign-in link is on its way.');
  } catch (error) {
    showFeedback(error.message);
  }
});

(async () => {
  const token = new URLSearchParams(window.location.search).get('token');
  try {
    const response = await fetch('/api/auth/config');
    const config = await response.json();
    if (config.account_backed) {
      legacyChooser.classList.add('is-hidden');
      magicLinkPanel.classList.remove('is-hidden');
      loginTitle.textContent = 'Sign in to your household';
      loginDescription.textContent = 'Use your email and we will send a secure, one-time link to your inbox.';
      if (token) {
        magicLinkPanel.classList.add('is-hidden');
        await consumeMagicLink(token);
      }
    }
  } catch (error) {
    if (token) showFeedback(error.message);
  }
})();
