const form = document.querySelector('#notificationForm');
const feedback = document.querySelector('#notificationFeedback');
const syncStatus = document.querySelector('#notificationSyncStatus');
const saveButton = document.querySelector('#saveNotifications');
const queueButton = document.querySelector('#queueBriefing');
const deliveryStatus = document.querySelector('#deliveryStatus');
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
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  if (themeMeta) themeMeta.setAttribute('content', theme === 'dark' ? '#171e1a' : '#f0f1eb');
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

function renderDelivery(delivery) {
  if (!delivery) {
    deliveryStatus.textContent = 'No briefing queued today.';
    return;
  }
  const labels = { queued: 'Queued for delivery.', sending: 'Delivery is in progress.', sent: 'Delivered.', failed: 'Delivery will retry.', no_provider: 'Queued, but no email provider is configured.', cancelled: 'Cancelled because notifications are off.' };
  deliveryStatus.textContent = labels[delivery.status] || `Delivery status: ${delivery.status}.`;
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

async function loadDelivery() {
  try {
    const payload = await api('/api/notifications/delivery?briefing_type=morning');
    renderDelivery(payload.delivery);
  } catch (error) {
    deliveryStatus.textContent = 'Delivery status unavailable.';
  }
}

async function queueBriefing() {
  queueButton.disabled = true;
  try {
    const payload = await api('/api/notifications/queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ briefing_type: 'morning' }),
    });
    if (!payload.queued) throw new Error(payload.reason || 'Briefing is disabled.');
    renderDelivery(payload.delivery);
    showFeedback('Today’s briefing is queued once.');
  } catch (error) {
    showFeedback(error.message, 'error');
  } finally {
    queueButton.disabled = false;
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
setTheme(document.documentElement.dataset.theme);
queueButton.addEventListener('click', queueBriefing);
loadPreferences();
loadDelivery();
