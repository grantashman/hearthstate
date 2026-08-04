const form = document.querySelector('#notificationForm');
const feedback = document.querySelector('#notificationFeedback');
const syncStatus = document.querySelector('#notificationSyncStatus');
const saveButton = document.querySelector('#saveNotifications');
const themeToggle = document.querySelector('#themeToggle');
const fields = {
  enabled: document.querySelector('#enabled'),
  preferred_time: document.querySelector('#preferredTime'),
  quiet_start: document.querySelector('#quietStart'),
  quiet_end: document.querySelector('#quietEnd'),
};

function showFeedback(message, kind = 'success') {
  feedback.textContent = message;
  feedback.className = `notification-feedback ${kind === 'error' ? 'is-error' : 'is-success'}`;
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeToggle.setAttribute('aria-pressed', String(theme === 'dark'));
  themeToggle.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  try { localStorage.setItem('hearthstate-theme', theme); } catch (error) { /* no-op */ }
}

async function api(path, options = {}) {
  const response = await hearthstateFetch(path, { cache: 'no-store', ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function renderPreferences(preferences) {
  fields.enabled.checked = Boolean(preferences.enabled);
  fields.preferred_time.value = preferences.preferred_time;
  fields.quiet_start.value = preferences.quiet_start;
  fields.quiet_end.value = preferences.quiet_end;
  document.querySelector('#channelBadge').textContent = preferences.channel === 'email' ? 'Email' : preferences.channel;
}

async function loadPreferences() {
  syncStatus.textContent = 'Refreshing';
  try {
    const payload = await api('/api/notifications/preferences?briefing_type=morning');
    renderPreferences(payload.preferences);
    syncStatus.textContent = 'Live preferences';
    feedback.classList.add('is-hidden');
  } catch (error) {
    syncStatus.textContent = 'Unavailable';
    showFeedback(error.message, 'error');
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  saveButton.disabled = true;
  syncStatus.textContent = 'Saving';
  try {
    const payload = await api('/api/notifications/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        briefing_type: 'morning',
        enabled: fields.enabled.checked,
        preferred_time: fields.preferred_time.value,
        quiet_start: fields.quiet_start.value,
        quiet_end: fields.quiet_end.value,
      }),
    });
    renderPreferences(payload.preferences);
    syncStatus.textContent = 'Saved just now';
    showFeedback('Notification preferences saved.');
  } catch (error) {
    syncStatus.textContent = 'Could not save';
    showFeedback(error.message, 'error');
  } finally {
    saveButton.disabled = false;
  }
});

themeToggle.addEventListener('click', () => {
  setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
});
themeToggle.setAttribute('aria-pressed', String(document.documentElement.dataset.theme === 'dark'));
loadPreferences();
