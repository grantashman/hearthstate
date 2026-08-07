const list = document.querySelector('#householdList');
const summary = document.querySelector('#householdSummary');
const feedback = document.querySelector('#householdFeedback');

const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));

function showError(message) {
  feedback.textContent = message;
  feedback.classList.remove('is-hidden');
}

async function selectHousehold(id, button) {
  button.disabled = true;
  button.textContent = 'Opening…';
  try {
    const response = await fetch('/api/households/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ household_id: id }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Could not select that household.');
    window.location.assign('/');
  } catch (error) {
    showError(error.message);
    button.disabled = false;
    button.textContent = 'Open household';
  }
}

async function loadHouseholds() {
  try {
    const response = await fetch('/api/me', { cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Your session has expired.');
    const households = Array.isArray(payload.households) ? payload.households : [];
    if (!households.length) {
      window.location.assign('/setup');
      return;
    }
    summary.textContent = households.length === 1 ? 'Opening your household space.' : 'Choose one space to continue.';
    list.innerHTML = households.map((household) => `<article class="login-form-heading"><span><strong>${escapeHTML(household.name || 'Household')}</strong><small>${escapeHTML(household.role || 'Household member')}</small></span><button class="primary-button household-choice" type="button" data-household-id="${escapeHTML(household.id)}"><span>Open household</span><span aria-hidden="true">↗</span></button></article>`).join('');
    list.querySelectorAll('.household-choice').forEach((button) => button.addEventListener('click', () => selectHousehold(button.dataset.householdId, button)));
    if (households.length === 1) await selectHousehold(households[0].id, list.querySelector('.household-choice'));
  } catch (error) {
    showError(error.message);
    summary.textContent = 'We could not load your household spaces.';
  }
}

loadHouseholds();
