const els = {
  search: document.querySelector('#recipeSearch'),
  tag: document.querySelector('#recipeTag'),
  date: document.querySelector('#planDate'),
  type: document.querySelector('#planType'),
  grid: document.querySelector('#recipeGrid'),
  empty: document.querySelector('#recipeEmpty'),
  heading: document.querySelector('#recipeHeading'),
  updated: document.querySelector('#recipeUpdated'),
  error: document.querySelector('#errorBanner'),
  status: document.querySelector('#syncStatus'),
  theme: document.querySelector('#themeToggle'),
  refresh: document.querySelector('#refreshButton'),
  importForm: document.querySelector('#recipeImportForm'),
  planDialog: document.querySelector('#planDialog'),
  planForm: document.querySelector('#planForm'),
  planTitle: document.querySelector('#planDialogTitle'),
  planDate: document.querySelector('#planDialogDate'),
  planCook: document.querySelector('#planDialogCook'),
  planChecklist: document.querySelector('#planIngredientChecklist'),
  planHint: document.querySelector('#planIngredientHint'),
  closePlan: document.querySelector('#closePlanDialog'),
  planConfirm: document.querySelector('#confirmPlan'),
  planFeedback: document.querySelector('#planFeedback'),
  ingredients: document.querySelector('#recipeIngredients'),
  ownership: document.querySelector('#ingredientOwnership'),
  checklist: document.querySelector('#ingredientChecklist'),
  importFeedback: document.querySelector('#importFeedback'),
};

const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));

function syncTheme() {
  const dark = document.documentElement.dataset.theme === 'dark';
  els.theme.setAttribute('aria-pressed', String(dark));
  els.theme.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  if (!els.theme.querySelector('.theme-icon')) els.theme.textContent = dark ? '☀' : '☾';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? '#1d1917' : '#f3ede3';
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('hearthstate-theme', theme); } catch (error) {}
  syncTheme();
}

function sourceLabel(recipe) {
  if (recipe.source_policy === 'local_original') return 'HEARTHSTATE ORIGINAL';
  if (recipe.source === 'user_supplied') return 'YOUR RECIPE';
  return recipe.source.toUpperCase();
}

function recipeTime(recipe) {
  const minutes = (Number(recipe.prep_minutes) || 0) + (Number(recipe.cook_minutes) || 0);
  return minutes ? `${minutes} min` : 'Time on source';
}

function photoMarkup(recipe) {
  if (!recipe.image_url) {
    return '<div class="recipe-image recipe-image-placeholder" role="img" aria-label="No recipe photo yet"><span>✦</span></div>';
  }
  const label = recipe.image_url.startsWith('/recipe-images/') ? 'Illustrative photo' : 'Provided photo';
  return `<figure class="recipe-photo"><img class="recipe-image" src="${escapeHTML(recipe.image_url)}" alt="Illustrative food photo for ${escapeHTML(recipe.title)}" loading="lazy"><figcaption>${label}</figcaption></figure>`;
}

function filterLabel() {
  const option = els.tag.options[els.tag.selectedIndex];
  return option?.textContent || 'Everything';
}

function renderRecipes(recipes) {
  els.grid.innerHTML = recipes.map((recipe) => `
    <article class="recipe-card">
      ${photoMarkup(recipe)}
      <div class="recipe-card-top"><span class="recipe-source">${escapeHTML(sourceLabel(recipe))}</span><span class="recipe-time">◷ ${escapeHTML(recipeTime(recipe))}</span></div>
      <div class="recipe-card-body"><h3>${escapeHTML(recipe.title)}</h3><p>${escapeHTML(recipe.summary || 'A recipe saved for the household shortlist.')}</p><div class="recipe-tags">${recipe.tags.map((tag) => `<span>${escapeHTML(tag)}</span>`).join('')}</div></div>
      <div class="recipe-card-actions">
        <button class="text-action save-recipe ${recipe.saved ? 'is-saved' : ''}" type="button" data-recipe-id="${recipe.id}" data-saved="${recipe.saved}">${recipe.saved ? '★ Saved' : '☆ Save'}</button>
        <button class="small-action plan-recipe" type="button" data-recipe-id="${recipe.id}">Plan dinner</button>
        <button class="small-action grocery-recipe" type="button" data-recipe-id="${recipe.id}" ${recipe.ingredients.length ? '' : 'disabled'}>${recipe.ingredients.length ? '+ groceries' : 'link only'}</button>
        <a class="source-action" href="${escapeHTML(recipe.source_url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>
      </div>
    </article>
  `).join('');
  els.grid.classList.toggle('is-hidden', recipes.length === 0);
  els.empty.classList.toggle('is-hidden', recipes.length !== 0);
  els.grid.querySelectorAll('.recipe-image').forEach((image) => image.addEventListener('error', () => {
    const placeholder = document.createElement('div');
    placeholder.className = 'recipe-image recipe-image-placeholder';
    placeholder.setAttribute('role', 'img');
    placeholder.setAttribute('aria-label', 'Recipe photo unavailable');
    placeholder.innerHTML = '<span>✦</span>';
    image.closest('.recipe-photo')?.replaceWith(placeholder);
  }));
  els.grid.querySelectorAll('.save-recipe').forEach((button) => button.addEventListener('click', () => saveRecipe(button)));
  els.grid.querySelectorAll('.plan-recipe').forEach((button) => button.addEventListener('click', () => openPlanDialog(recipes.find((recipe) => String(recipe.id) === String(button.dataset.recipeId)))));
  els.grid.querySelectorAll('.grocery-recipe').forEach((button) => button.addEventListener('click', () => addRecipeGroceries(button)));
}

function renderPlanCookOptions(members) {
  const options = (Array.isArray(members) ? members : []).map((member) => `<option value="${escapeHTML(member.id)}">${escapeHTML(member.display_name || member.id)}</option>`).join('');
  els.planCook.innerHTML = `<option value="">Decide later</option>${options}`;
}

async function loadRecipes() {
  els.status.textContent = 'Refreshing';
  const params = new URLSearchParams();
  if (els.search.value.trim()) params.set('search', els.search.value.trim());
  if (els.tag.value && els.tag.value !== 'saved') params.set('tag', els.tag.value);
  if (els.tag.value === 'saved') params.set('saved_by', 'grant');
  try {
    const response = await hearthstateFetch(`/api/recipes?${params.toString()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const payload = await response.json();
    renderPlanCookOptions(payload.members);
    renderRecipes(payload.recipes);
    const heading = els.tag.value === 'saved' ? 'Saved for later' : els.tag.value === '' ? 'Simple and healthy' : `${filterLabel()} recipes`;
    els.heading.textContent = heading;
    els.updated.textContent = `${payload.recipes.length} RECIPES · UPDATED ${new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(payload.generated_at)).toUpperCase()}`;
    els.error.classList.add('is-hidden');
    els.status.textContent = `Showing ${payload.recipes.length} recipes`;
  } catch (error) {
    els.error.textContent = 'Could not load recipes.';
    els.error.classList.remove('is-hidden');
    els.status.textContent = 'Offline';
    console.error(error);
  }
}

async function saveRecipe(button) {
  const saved = button.dataset.saved !== 'true';
  button.disabled = true;
  try {
    const response = await hearthstateFetch(`/api/recipes/${button.dataset.recipeId}/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ saved_by: 'grant', saved }),
    });
    if (!response.ok) throw new Error('save failed');
    await loadRecipes();
  } catch (error) { button.disabled = false; console.error(error); }
}

let currentPlanRecipe = null;

function openPlanDialog(recipe) {
  if (!recipe) return;
  currentPlanRecipe = recipe;
  els.planTitle.textContent = `Plan ${recipe.title}`;
  els.planDate.value = els.date.value || new Date().toISOString().slice(0, 10);
  els.planCook.value = '';
  els.planFeedback.classList.add('is-hidden');
  const ingredients = recipe.ingredients || [];
  els.planChecklist.innerHTML = ingredients.map((ingredient, index) => {
    const description = [ingredient.quantity, ingredient.unit, ingredient.name].filter(Boolean).join(' ');
    return `<label class="ingredient-check"><input type="checkbox" data-ingredient-index="${index}"><span>${escapeHTML(description)}</span><em>already have</em></label>`;
  }).join('');
  els.planHint.textContent = ingredients.length
    ? 'Check anything you already have. Unchecked ingredients will be added to Groceries.'
    : 'This recipe links to its source and has no local ingredient list to add. You can still choose the night and cook.';
  els.planDialog.classList.remove('is-hidden');
  els.planDialog.setAttribute('aria-hidden', 'false');
  els.planCook.focus();
}

function closePlanDialog() {
  els.planDialog.classList.add('is-hidden');
  els.planDialog.setAttribute('aria-hidden', 'true');
  currentPlanRecipe = null;
}

async function submitPlan(event) {
  event.preventDefault();
  if (!currentPlanRecipe) return;
  const missingIndexes = [...els.planChecklist.querySelectorAll('input:not(:checked)')]
    .map((input) => Number(input.dataset.ingredientIndex));
  els.planConfirm.disabled = true;
  els.planConfirm.textContent = 'planning…';
  try {
    const response = await hearthstateFetch(`/api/recipes/${currentPlanRecipe.id}/plan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        meal_date: els.planDate.value,
        meal_type: 'dinner',
        cook: els.planCook.value,
        created_by: 'grant',
        grocery_ingredient_indexes: missingIndexes,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'plan failed');
    const added = payload.added || [];
    els.status.textContent = added.length ? `Planned · added ${added.length} to Groceries` : 'Dinner planned';
    closePlanDialog();
  } catch (error) {
    els.planConfirm.disabled = false;
    els.planConfirm.innerHTML = 'Plan dinner <span>↗</span>';
    els.planFeedback.textContent = error.message;
    els.planFeedback.classList.remove('is-hidden');
  }
}

async function addRecipeGroceries(button) {
  button.disabled = true;
  button.textContent = 'adding…';
  try {
    const response = await hearthstateFetch(`/api/recipes/${button.dataset.recipeId}/shopping-list`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ meal_id: button.dataset.recipeId, created_by: 'grant' }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'groceries failed');
    button.textContent = payload.added.length ? 'added ✓' : 'already there';
  } catch (error) { button.disabled = false; button.textContent = '+ groceries'; console.error(error); }
}

function parseIngredients(value) {
  return String(value || '').split('\n').map((line) => {
    const [quantity = '', unit = '', ...nameParts] = line.split('|').map((part) => part.trim());
    return { quantity, unit, name: nameParts.join(' | ') || quantity };
  }).filter((item) => item.name);
}

function renderIngredientChecklist() {
  const ingredients = parseIngredients(els.ingredients.value);
  els.ownership.classList.toggle('is-hidden', ingredients.length === 0);
  els.checklist.innerHTML = ingredients.map((ingredient, index) => {
    const description = [ingredient.quantity, ingredient.unit, ingredient.name].filter(Boolean).join(' ');
    return `<label class="ingredient-check"><input type="checkbox" data-ingredient-index="${index}"><span>${escapeHTML(description)}</span><em>already have</em></label>`;
  }).join('');
}

els.importForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(els.importForm);
  const ingredients = parseIngredients(data.get('ingredients'));
  const groceryIngredientIndexes = [...els.checklist.querySelectorAll('input:not(:checked)')]
    .map((input) => Number(input.dataset.ingredientIndex));
  const response = await hearthstateFetch('/api/recipes/import', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: data.get('title'),
      source_url: data.get('source_url') || `user://recipe/${Date.now()}`,
      image_url: data.get('image_url') || '',
      tags: String(data.get('tags') || '').split(',').map((tag) => tag.trim()).filter(Boolean),
      ingredients,
      grocery_ingredient_indexes: groceryIngredientIndexes,
      created_by: 'grant',
    }),
  });
  const payload = await response.json();
  if (!response.ok) { els.importFeedback.textContent = payload.error || 'Could not save recipe.'; els.importFeedback.classList.remove('is-hidden'); return; }
  els.importForm.reset();
  renderIngredientChecklist();
  els.importFeedback.textContent = payload.added?.length
    ? `Saved. Added ${payload.added.length} missing ingredient${payload.added.length === 1 ? '' : 's'} to Groceries.`
    : 'Saved. Ingredients marked as already owned were not added to Groceries.';
  els.importFeedback.classList.remove('is-hidden');
  await loadRecipes();
});

els.search.addEventListener('input', (() => { let timer; return () => { clearTimeout(timer); timer = setTimeout(loadRecipes, 180); }; })());
els.ingredients.addEventListener('input', renderIngredientChecklist);
els.tag.addEventListener('change', loadRecipes);
els.tag.addEventListener('input', loadRecipes);
els.refresh.addEventListener('click', loadRecipes);
els.theme.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
els.planForm.addEventListener('submit', submitPlan);
els.closePlan.addEventListener('click', closePlanDialog);
els.planDialog.addEventListener('click', (event) => { if (event.target === els.planDialog) closePlanDialog(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !els.planDialog.classList.contains('is-hidden')) closePlanDialog(); });
els.date.value = new Date().toISOString().slice(0, 10);
syncTheme();
loadRecipes();
