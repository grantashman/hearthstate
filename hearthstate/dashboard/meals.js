const els = {
  form: document.querySelector('#mealForm'),
  id: document.querySelector('#mealId'),
  date: document.querySelector('#mealDate'),
  list: document.querySelector('#mealList'),
  empty: document.querySelector('#mealEmpty'),
  feedback: document.querySelector('#formFeedback'),
  error: document.querySelector('#errorBanner'),
  updated: document.querySelector('#mealUpdated'),
  theme: document.querySelector('#themeToggle'),
  refresh: document.querySelector('#refreshButton'),
  status: document.querySelector('#syncStatus'),
  formKicker: document.querySelector('#mealFormKicker'),
  formTitle: document.querySelector('#mealFormTitle'),
  submit: document.querySelector('#mealSubmit'),
  cancel: document.querySelector('#cancelMealEdit'),
};

let currentMeals = [];

const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));

function syncTheme() {
  const dark = document.documentElement.dataset.theme === 'dark';
  els.theme.setAttribute('aria-pressed', String(dark));
  els.theme.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  els.theme.textContent = dark ? '☀' : '☾';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#1d1917' : '#f3ede3';
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('hearthstate-theme', theme); } catch (error) {}
  syncTheme();
}

function formatDay(value) {
  return new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'short', day: 'numeric' }).format(new Date(`${value}T12:00:00`));
}

function setFormMode(editing) {
  els.formKicker.textContent = editing ? 'EDIT THE TABLE' : 'ADD TO THE TABLE';
  els.formTitle.textContent = editing ? 'Edit meal' : 'Plan a meal';
  els.submit.innerHTML = editing ? 'Save meal <span>↗</span>' : 'Add to meal plan <span>↗</span>';
  els.cancel.classList.toggle('is-hidden', !editing);
}

function renderCookOptions(members) {
  const select = els.form.elements.cook;
  const selected = select.value;
  const options = (Array.isArray(members) ? members : []).map((member) => `<option value="${escapeHTML(member.id)}">${escapeHTML(member.display_name || member.id)}</option>`).join('');
  select.innerHTML = `<option value="">Decide later</option>${options}`;
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

function resetMealForm() {
  els.form.reset();
  els.id.value = '';
  els.date.value = defaultMealDate;
  setFormMode(false);
  els.feedback.classList.add('is-hidden');
}

function startEditMeal(mealId) {
  const meal = currentMeals.find((item) => String(item.id) === String(mealId));
  if (!meal) return;
  els.id.value = meal.id;
  els.date.value = meal.meal_date;
  els.form.elements.meal_type.value = meal.meal_type;
  els.form.elements.cook.value = meal.cook || '';
  els.form.elements.title.value = meal.title;
  els.form.elements.ingredients.value = meal.ingredients.join(', ');
  setFormMode(true);
  els.feedback.classList.add('is-hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  els.form.elements.title.focus();
}

async function deleteMeal(mealId) {
  const meal = currentMeals.find((item) => String(item.id) === String(mealId));
  if (!meal || !window.confirm(`Delete “${meal.title}”? This cannot be undone.`)) return;
  try {
    const response = await hearthstateFetch(`/api/meals/${meal.id}/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not delete that meal.');
    if (String(els.id.value) === String(meal.id)) resetMealForm();
    els.feedback.textContent = 'Meal deleted.';
    els.feedback.classList.remove('is-hidden');
    await loadMeals();
  } catch (error) {
    els.feedback.textContent = error.message;
    els.feedback.classList.remove('is-hidden');
  }
}

function renderMeals(meals) {
  els.list.innerHTML = meals.map((meal) => `
    <article class="meal-card">
      <div class="meal-card-date"><span>${escapeHTML(formatDay(meal.meal_date))}</span><strong>${escapeHTML(meal.meal_type)}</strong></div>
      <div class="meal-card-main"><strong>${escapeHTML(meal.title)}</strong><span>Cooking: ${escapeHTML(meal.cook_label)}</span><div class="ingredient-list">${meal.ingredients.map((item) => `<span>${escapeHTML(item)}</span>`).join('')}</div></div>
      <div class="meal-actions">
        <button class="quiet-action edit-meal" type="button" data-meal-id="${escapeHTML(meal.id)}">Edit</button>
        <button class="quiet-action delete-meal" type="button" data-meal-id="${escapeHTML(meal.id)}">Delete</button>
        <button class="ingredient-action" type="button" data-meal-id="${escapeHTML(meal.id)}" ${meal.ingredients.length ? '' : 'disabled'}>+ groceries</button>
      </div>
    </article>
  `).join('');
  els.list.classList.toggle('is-hidden', meals.length === 0);
  els.empty.classList.toggle('is-hidden', meals.length !== 0);
  els.list.querySelectorAll('.edit-meal').forEach((button) => {
    button.addEventListener('click', () => startEditMeal(button.dataset.mealId));
  });
  els.list.querySelectorAll('.delete-meal').forEach((button) => {
    button.addEventListener('click', () => deleteMeal(button.dataset.mealId));
  });
  els.list.querySelectorAll('.ingredient-action').forEach((button) => {
    button.addEventListener('click', () => syncGroceries(button));
  });
}

async function loadMeals() {
  els.status.textContent = 'Refreshing';
  try {
    const response = await hearthstateFetch('/api/meals', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const payload = await response.json();
    renderCookOptions(payload.members);
    currentMeals = payload.meals;
    renderMeals(currentMeals);
    els.updated.textContent = `UPDATED ${new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(payload.generated_at)).toUpperCase()}`;
    els.error.classList.add('is-hidden');
    els.status.textContent = 'Live snapshot';
  } catch (error) {
    els.error.textContent = 'Could not load the meal plan.';
    els.error.classList.remove('is-hidden');
    els.status.textContent = 'Offline';
    console.error(error);
  }
}

async function syncGroceries(button) {
  button.disabled = true;
  button.textContent = 'adding…';
  try {
    const response = await hearthstateFetch('/api/meals/sync-groceries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ meal_id: button.dataset.mealId, created_by: 'grant' }),
    });
    const payload = await response.json();
    button.textContent = payload.added.length ? 'added ✓' : 'already there';
  } catch (error) {
    button.disabled = false;
    button.textContent = '+ groceries';
    console.error(error);
  }
}

els.form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(els.form);
  const ingredients = String(data.get('ingredients') || '').split(',').map((item) => item.trim()).filter(Boolean);
  const id = String(data.get('id') || '').trim();
  els.submit.disabled = true;
  try {
    const response = await hearthstateFetch('/api/meals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...(id ? { id } : {}),
        meal_date: data.get('meal_date'), meal_type: data.get('meal_type'), title: data.get('title'),
        cook: data.get('cook'), ingredients, created_by: 'grant',
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not save that meal.');
    const wasEditing = Boolean(id);
    resetMealForm();
    els.feedback.textContent = wasEditing ? 'Meal updated.' : 'Meal added. You can send its ingredients to Groceries below.';
    els.feedback.classList.remove('is-hidden');
    await loadMeals();
  } catch (error) {
    els.feedback.textContent = error.message;
    els.feedback.classList.remove('is-hidden');
  } finally {
    els.submit.disabled = false;
  }
});

els.cancel.addEventListener('click', resetMealForm);
els.theme.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
els.refresh.addEventListener('click', loadMeals);
const requestedDate = new URLSearchParams(window.location.search).get('date');
const defaultMealDate = /^\d{4}-\d{2}-\d{2}$/.test(requestedDate || '') ? requestedDate : new Date().toISOString().slice(0, 10);
els.date.value = defaultMealDate;
syncTheme();
loadMeals();
