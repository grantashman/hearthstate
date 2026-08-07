const els = {
  themeToggle: document.querySelector('#themeToggle'),
  greetingEyebrow: document.querySelector('#greetingEyebrow'),
  greetingTitle: document.querySelector('#greetingTitle'),
  refresh: document.querySelector('#refreshButton'),
  syncStatus: document.querySelector('#syncStatus'),
  headerDate: document.querySelector('#headerDate'),
  todayHeading: document.querySelector('#todayHeading'),
  todayStamp: document.querySelector('#todayStamp'),
  attentionMetric: document.querySelector('#attentionMetric'),
  todayMetric: document.querySelector('#todayMetric'),
  groceryMetric: document.querySelector('#groceryMetric'),
  stateCount: document.querySelector('#stateCount'),
  stateTitle: document.querySelector('#stateTitle'),
  stateRuleFill: document.querySelector('#stateRuleFill'),
  attentionBadge: document.querySelector('#attentionBadge'),
  attentionList: document.querySelector('#attentionList'),
  attentionEmpty: document.querySelector('#attentionEmpty'),
  todayTimeline: document.querySelector('#todayTimeline'),
  todayEmpty: document.querySelector('#todayEmpty'),
  upcomingWrap: document.querySelector('#upcomingWrap'),
  upcomingList: document.querySelector('#upcomingList'),
  groceryCount: document.querySelector('#groceryCount'),
  groceryBudgetNote: document.querySelector('#groceryBudgetNote'),
  groceryList: document.querySelector('#groceryList'),
  groceryEmpty: document.querySelector('#groceryEmpty'),
  planningStrip: document.querySelector('#planningStrip'),
  footerTime: document.querySelector('#footerTime'),
  viewerAvatar: document.querySelector('#viewerAvatar'),
  viewerName: document.querySelector('#viewerName'),
  viewerRole: document.querySelector('#viewerRole'),
  error: document.querySelector('#errorBanner'),
  inboxBadge: document.querySelector('#inboxBadge'),
  inboxList: document.querySelector('#inboxList'),
  inboxEmpty: document.querySelector('#inboxEmpty'),
  inboxCaptureForm: document.querySelector('#inboxCaptureForm'),
  inboxCaptureText: document.querySelector('#inboxCaptureText'),
  inboxConvertForm: document.querySelector('#inboxConvertForm'),
  inboxConvertId: document.querySelector('#inboxConvertId'),
  inboxSuggestionId: document.querySelector('#inboxSuggestionId'),
  inboxConvertType: document.querySelector('#inboxConvertType'),
  inboxConvertTitle: document.querySelector('#inboxConvertTitle'),
  inboxConvertName: document.querySelector('#inboxConvertName'),
  inboxConvertDateTime: document.querySelector('#inboxConvertDateTime'),
  inboxConvertMealDate: document.querySelector('#inboxConvertMealDate'),
  inboxConvertIngredients: document.querySelector('#inboxConvertIngredients'),
  inboxConvertCancel: document.querySelector('#inboxConvertCancel'),
  inboxRejectSuggestion: document.querySelector('#inboxRejectSuggestion'),
  inboxConvertFeedback: document.querySelector('#inboxConvertFeedback'),
  inboxTitleField: document.querySelector('#inboxTitleField'),
  inboxNameField: document.querySelector('#inboxNameField'),
  inboxDateTimeField: document.querySelector('#inboxDateTimeField'),
  inboxMealDateField: document.querySelector('#inboxMealDateField'),
  inboxIngredientsField: document.querySelector('#inboxIngredientsField'),
  intelligenceBadge: document.querySelector('#intelligenceBadge'),
  conflictList: document.querySelector('#conflictList'),
  conflictEmpty: document.querySelector('#conflictEmpty'),
  activityList: document.querySelector('#activityList'),
  activityEmpty: document.querySelector('#activityEmpty'),
  choreList: document.querySelector('#choreList'),
  choreEmpty: document.querySelector('#choreEmpty'),
};

const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));

const formatDate = (value, options) => new Intl.DateTimeFormat(undefined, options).format(new Date(value));
const viewerBootstrap = window.__HEARTHSTATE_VIEWER__ || {};
let currentViewerName = viewerBootstrap.name || 'family';

function getTimeOfDayGreeting(hour = new Date().getHours(), name = 'family') {
  const subject = name || 'family';
  if (hour >= 5 && hour < 12) {
    return { title: `Good morning, ${subject}.`, eyebrow: 'A CALM START TO THE DAY' };
  }
  if (hour >= 12 && hour < 17) {
    return { title: `Good afternoon, ${subject}.`, eyebrow: 'A CALM PAUSE IN THE DAY' };
  }
  if (hour >= 17 && hour < 21) {
    return { title: `Good evening, ${subject}.`, eyebrow: 'A CALM EVENING AT HOME' };
  }
  return { title: `Good evening, ${subject}.`, eyebrow: 'A QUIET END TO THE DAY' };
}

function updateGreeting(now = new Date(), name = currentViewerName) {
  const greeting = getTimeOfDayGreeting(now.getHours(), name);
  els.greetingTitle.textContent = greeting.title;
  els.greetingEyebrow.textContent = greeting.eyebrow;
}

function applyViewerBootstrap() {
  if (!viewerBootstrap.name) return;
  currentViewerName = viewerBootstrap.name;
  if (els.viewerName) els.viewerName.textContent = viewerBootstrap.name;
  if (els.viewerRole) els.viewerRole.textContent = viewerBootstrap.role || 'Household member';
  if (els.viewerAvatar) els.viewerAvatar.textContent = viewerBootstrap.name.charAt(0).toUpperCase();
}

function syncThemeButton() {
  const isDark = document.documentElement.dataset.theme === 'dark';
  els.themeToggle.setAttribute('aria-pressed', String(isDark));
  els.themeToggle.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
  els.themeToggle.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  if (themeMeta) themeMeta.setAttribute('content', isDark ? '#1d1917' : '#f3ede3');
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem('hearthstate-theme', theme);
  } catch (error) {
    // The visual toggle still works when browser storage is unavailable.
  }
  syncThemeButton();
}

function setLoading(isLoading) {
  els.refresh.classList.toggle('is-loading', isLoading);
  els.refresh.disabled = isLoading;
  els.syncStatus.textContent = isLoading ? 'Refreshing' : 'Live snapshot';
}

function renderAttention(items) {
  els.attentionList.innerHTML = items.map((item) => {
    const editLink = item.href && item.action_type === 'complete'
      ? `<a class="attention-link" href="${escapeHTML(item.href)}">Edit</a>`
      : '';
    const action = item.action_type === 'complete'
      ? `<button class="attention-action attention-complete" type="button" data-task-id="${escapeHTML(item.source_id)}">${escapeHTML(item.action_label)}</button>`
      : item.href
        ? `<a class="attention-action" href="${escapeHTML(item.href)}">${escapeHTML(item.action_label)}</a>`
        : '';
    return `
      <li class="attention-item urgency-${escapeHTML(item.urgency)}">
        <div class="attention-content">
          <div class="attention-title" title="${escapeHTML(item.title)}">${escapeHTML(item.title)}</div>
          <div class="attention-meta">
            <span class="owner-chip ${item.owner ? '' : 'is-unassigned'}">${escapeHTML(item.meta_label || item.owner_label || '')}</span>
            ${item.private ? '<span>private</span>' : ''}
          </div>
        </div>
        <span class="attention-due">${escapeHTML(item.due_label || '')}</span>
        <div class="attention-actions">${editLink}${action}</div>
      </li>
    `;
  }).join('');
  els.attentionList.classList.toggle('is-hidden', items.length === 0);
  els.attentionEmpty.classList.toggle('is-hidden', items.length !== 0);
  els.attentionList.querySelectorAll('.attention-complete').forEach((button) => {
    button.addEventListener('click', () => completeTask(button.dataset.taskId));
  });
}

async function completeTask(taskId) {
  try {
    const response = await hearthstateFetch(`/api/tasks/${encodeURIComponent(taskId)}/complete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not complete task');
    await loadDashboard();
  } catch (error) {
    els.error.textContent = error.message;
    els.error.classList.remove('is-hidden');
  }
}

function itemHref(item) {
  if (item.source_type === 'task') return `/tasks?edit=${encodeURIComponent(item.source_id)}`;
  if (item.source_type === 'meal') return `/meals?date=${encodeURIComponent(item.starts_at.slice(0, 10))}`;
  if (item.source_type === 'event') return `/calendar?edit=${encodeURIComponent(item.source_id)}`;
  return '#';
}

function renderTimeline(items) {
  els.todayTimeline.innerHTML = items.map((item) => `
    <div class="timeline-item timeline-${escapeHTML(item.source_type)}">
      <time class="timeline-time">${escapeHTML(item.time_label)}</time>
      <div class="timeline-card">
        <a class="timeline-title" href="${escapeHTML(itemHref(item))}">${escapeHTML(item.title)}</a>
        <div class="timeline-meta"><span>${escapeHTML(item.source_type === 'task' ? 'Task' : item.source_type === 'meal' ? (item.meal_type ? item.meal_type.charAt(0).toUpperCase() + item.meal_type.slice(1) : 'Meal') : 'Event')}</span>${item.person ? `<span>${escapeHTML(item.person)}</span>` : ''}</div>
      </div>
    </div>
  `).join('');
  els.todayTimeline.classList.toggle('is-hidden', items.length === 0);
  els.todayEmpty.classList.toggle('is-hidden', items.length !== 0);
}

function renderPlanningWeek(days) {
  els.planningStrip.innerHTML = days.map((day) => {
    const dinner = day.dinner
      ? `<a class="planning-dinner" href="/meals?date=${encodeURIComponent(day.date)}"><span class="planning-label">DINNER</span><strong>${escapeHTML(day.dinner.title)}</strong>${day.dinner.person ? `<small>${escapeHTML(day.dinner.person)}</small>` : '<small class="planning-warning">Assign a cook</small>'}</a>`
      : `<a class="planning-dinner planning-empty" href="/meals?date=${encodeURIComponent(day.date)}"><span class="planning-label">DINNER</span><strong>Plan dinner</strong><small>Nothing planned yet</small></a>`;
    const entries = day.items.filter((item) => item.source_type !== 'meal').slice(0, 3).map((item) => `
      <a class="planning-item planning-${escapeHTML(item.source_type)}" href="${escapeHTML(itemHref(item))}">
        <span>${escapeHTML(item.source_type === 'task' ? 'Task' : 'Event')}</span><strong>${escapeHTML(item.title)}</strong>${item.recurrence !== 'none' ? `<small>${escapeHTML(item.recurrence_label)}</small>` : ''}
      </a>
    `).join('');
    return `<article class="planning-day ${day.date === days[0].date ? 'is-today' : ''}"><div class="planning-day-head"><span>${escapeHTML(day.short_label)}</span><strong>${escapeHTML(day.day_number)}</strong></div>${dinner}<div class="planning-items">${entries || '<span class="planning-no-items">No other plans</span>'}</div></article>`;
  }).join('');
}

function renderUpcoming(items) {
  els.upcomingList.innerHTML = items.slice(0, 4).map((item) => `
    <div class="upcoming-item">
      <strong>${escapeHTML(item.title)}</strong>
      <span>${escapeHTML(item.day_label)} · ${escapeHTML(item.time_label)}</span>
    </div>
  `).join('');
  els.upcomingWrap.classList.toggle('is-hidden', items.length === 0);
}

function renderGroceries(items, summary) {
  els.groceryList.innerHTML = items.map((item) => `
    <div class="grocery-item"><span class="grocery-check" aria-hidden="true">✓</span><span>${escapeHTML(item.name)}</span></div>
  `).join('');
  els.groceryList.classList.toggle('is-hidden', items.length === 0);
  els.groceryEmpty.classList.toggle('is-hidden', items.length !== 0);
  if (summary?.over_budget) {
    els.groceryBudgetNote.textContent = `Over budget by $${Math.abs(summary.remaining).toFixed(2)}`;
    els.groceryBudgetNote.className = 'grocery-budget-note is-warning';
  } else if (summary?.remaining != null) {
    els.groceryBudgetNote.textContent = `$${summary.remaining.toFixed(2)} left in weekly budget`;
    els.groceryBudgetNote.className = 'grocery-budget-note';
  } else if (summary?.unknown_price_count) {
    els.groceryBudgetNote.textContent = `${summary.unknown_price_count} item${summary.unknown_price_count === 1 ? '' : 's'} need a price`;
    els.groceryBudgetNote.className = 'grocery-budget-note is-warning';
  } else {
    els.groceryBudgetNote.textContent = 'Set a weekly budget in Groceries';
    els.groceryBudgetNote.className = 'grocery-budget-note';
  }
}

function renderIntelligence(intelligence) {
  const conflicts = intelligence.conflicts || [];
  const activity = intelligence.activity || [];
  const chores = intelligence.chores || [];
  els.intelligenceBadge.textContent = conflicts.length ? `${conflicts.length} conflict${conflicts.length === 1 ? '' : 's'}` : 'Clear';
  els.intelligenceBadge.classList.toggle('is-warning', conflicts.length > 0);
  els.conflictList.innerHTML = conflicts.slice(0, 4).map((item) => `<li><strong>${escapeHTML(item.title)}</strong><span>${escapeHTML(item.assignee || 'Household')}</span></li>`).join('');
  els.activityList.innerHTML = activity.slice(0, 4).map((item) => {
    const state = item.after || item.before || {};
    const label = state.title || state.name || item.entity_type;
    return `<li><strong>${escapeHTML(label)}</strong><span>${escapeHTML(item.action.replace('.', ' '))} · ${escapeHTML(item.actor)}</span></li>`;
  }).join('');
  els.choreList.innerHTML = chores.slice(0, 4).map((item) => {
    const next = item.participants?.[item.next_index % item.participants.length] || '...';
    return `<li><strong>${escapeHTML(item.title)}</strong><span>Next: ${escapeHTML(next)} · ${escapeHTML(item.cadence)}</span></li>`;
  }).join('');
  els.conflictList.classList.toggle('is-hidden', conflicts.length === 0);
  els.conflictEmpty.classList.toggle('is-hidden', conflicts.length !== 0);
  els.activityList.classList.toggle('is-hidden', activity.length === 0);
  els.activityEmpty.classList.toggle('is-hidden', activity.length !== 0);
  els.choreList.classList.toggle('is-hidden', chores.length === 0);
  els.choreEmpty.classList.toggle('is-hidden', chores.length !== 0);
}

function renderInbox(items) {
  els.inboxBadge.textContent = `${items.length} open`;
  els.inboxList.innerHTML = items.map((item) => {
    const suggestion = item.suggestion;
    const suggestedType = suggestion?.suggestion_type ? `Suggested ${suggestion.suggestion_type}` : 'Needs a review';
    const reviewAction = suggestion
      ? `<button class="inbox-action" type="button" data-inbox-id="${escapeHTML(item.id)}">Review · ${escapeHTML(suggestion.suggestion_type)}</button>`
      : '<span class="inbox-meta">No suggestion available</span>';
    return `
      <li class="inbox-item">
        <div class="inbox-item-copy">
          <div class="inbox-original">${escapeHTML(item.original_text)}</div>
          <div class="inbox-meta"><span>${escapeHTML(item.source || 'dashboard')}</span><span>·</span><span>${escapeHTML(suggestedType)}</span></div>
        </div>
        <div class="inbox-actions">
          ${reviewAction}
          <button class="inbox-action inbox-archive" type="button" data-inbox-id="${escapeHTML(item.id)}">Archive</button>
        </div>
      </li>
    `;
  }).join('');
  els.inboxList.classList.toggle('is-hidden', items.length === 0);
  els.inboxEmpty.classList.toggle('is-hidden', items.length !== 0);
  els.inboxList.querySelectorAll('.inbox-action:not(.inbox-archive)').forEach((button) => {
    button.addEventListener('click', () => {
      const item = items.find((candidate) => String(candidate.id) === String(button.dataset.inboxId));
      openInboxConversion(item, item?.suggestion?.suggestion_type || 'task');
    });
  });
  els.inboxList.querySelectorAll('.inbox-archive').forEach((button) => {
    button.addEventListener('click', () => archiveInboxItem(button.dataset.inboxId));
  });
}

function setInboxConversionFields() {
  const type = els.inboxConvertType.value;
  const isTask = type === 'task';
  const isEvent = type === 'event';
  const isMeal = type === 'meal';
  const isGrocery = type === 'grocery';
  els.inboxTitleField.classList.toggle('is-hidden', isGrocery);
  els.inboxNameField.classList.toggle('is-hidden', !isGrocery);
  els.inboxDateTimeField.classList.toggle('is-hidden', !(isTask || isEvent));
  els.inboxMealDateField.classList.toggle('is-hidden', !isMeal);
  els.inboxIngredientsField.classList.toggle('is-hidden', !isMeal);
  els.inboxConvertTitle.required = !isGrocery;
  els.inboxConvertName.required = isGrocery;
  els.inboxConvertDateTime.required = isEvent;
  els.inboxConvertMealDate.required = isMeal;
  els.inboxDateTimeField.firstChild.textContent = isEvent ? 'Starts date and time' : 'Due date and time';
  els.inboxTitleField.firstChild.textContent = type === 'note' ? 'Note' : 'Title';
}

function openInboxConversion(item, type) {
  if (!item || !item.suggestion) return;
  const proposed = item.suggestion.proposed_payload || {};
  els.inboxConvertId.value = item.id;
  els.inboxSuggestionId.value = item.suggestion.id;
  els.inboxConvertType.value = type;
  els.inboxConvertTitle.value = proposed.title || proposed.text || item.original_text;
  els.inboxConvertName.value = proposed.name || item.original_text;
  els.inboxConvertDateTime.value = proposed.starts_at || proposed.due_at || '';
  els.inboxConvertMealDate.value = proposed.meal_date || new Date().toISOString().slice(0, 10);
  els.inboxConvertIngredients.value = Array.isArray(proposed.ingredients) ? proposed.ingredients.join(', ') : '';
  els.inboxConvertFeedback.classList.add('is-hidden');
  els.inboxConvertForm.classList.remove('is-hidden');
  setInboxConversionFields();
  (type === 'grocery' ? els.inboxConvertName : els.inboxConvertTitle).focus();
}

function closeInboxConversion() {
  els.inboxConvertForm.classList.add('is-hidden');
  els.inboxConvertFeedback.classList.add('is-hidden');
}

async function rejectInboxSuggestion() {
  const submit = els.inboxConvertForm.querySelector('button[type="submit"]');
  els.inboxRejectSuggestion.disabled = true;
  submit.disabled = true;
  try {
    const response = await hearthstateFetch(`/api/inbox/${encodeURIComponent(els.inboxConvertId.value)}/suggestion/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suggestion_id: els.inboxSuggestionId.value, decision: 'reject' }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not reject Inbox suggestion');
    closeInboxConversion();
    await loadDashboard();
  } catch (error) {
    els.inboxConvertFeedback.textContent = error.message;
    els.inboxConvertFeedback.classList.remove('is-hidden');
  } finally {
    els.inboxRejectSuggestion.disabled = false;
    submit.disabled = false;
  }
}

async function archiveInboxItem(itemId) {
  try {
    const response = await hearthstateFetch(`/api/inbox/${encodeURIComponent(itemId)}/archive`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not archive Inbox item');
    await loadDashboard();
  } catch (error) {
    els.error.textContent = error.message;
    els.error.classList.remove('is-hidden');
  }
}

async function submitInboxConversion(event) {
  event.preventDefault();
  const type = els.inboxConvertType.value;
  const payload = {};
  if (type === 'grocery') {
    payload.name = els.inboxConvertName.value.trim();
    payload.quantity = 1;
    payload.unit = 'each';
    payload.category = 'Inbox';
  } else if (type === 'event') {
    payload.title = els.inboxConvertTitle.value.trim();
    payload.starts_at = els.inboxConvertDateTime.value;
  } else if (type === 'meal') {
    payload.title = els.inboxConvertTitle.value.trim();
    payload.meal_date = els.inboxConvertMealDate.value;
    payload.meal_type = 'dinner';
    payload.ingredients = els.inboxConvertIngredients.value.split(',').map((value) => value.trim()).filter(Boolean);
  } else if (type === 'note') {
    payload.text = els.inboxConvertTitle.value.trim();
  } else {
    payload.title = els.inboxConvertTitle.value.trim();
    payload.due_at = els.inboxConvertDateTime.value || null;
  }
  const submit = els.inboxConvertForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const response = await hearthstateFetch(`/api/inbox/${encodeURIComponent(els.inboxConvertId.value)}/suggestion/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        suggestion_id: els.inboxSuggestionId.value,
        decision: 'accept',
        suggestion_type: type,
        payload,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not confirm Inbox suggestion');
    closeInboxConversion();
    await loadDashboard();
  } catch (error) {
    els.inboxConvertFeedback.textContent = error.message;
    els.inboxConvertFeedback.classList.remove('is-hidden');
  } finally {
    submit.disabled = false;
  }
}

async function captureInboxItem(event) {
  event.preventDefault();
  const originalText = els.inboxCaptureText.value.trim();
  if (!originalText) return;
  const submit = els.inboxCaptureForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const response = await hearthstateFetch('/api/inbox', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ original_text: originalText, source: 'dashboard' }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not capture Inbox item');
    els.inboxCaptureText.value = '';
    await loadDashboard();
  } catch (error) {
    els.error.textContent = error.message;
    els.error.classList.remove('is-hidden');
  } finally {
    submit.disabled = false;
  }
}

function render(snapshot, intelligence = {}) {
  const current = snapshot.generated_at;
  currentViewerName = snapshot.viewer_name || 'family';
  updateGreeting(new Date(), currentViewerName);
  if (els.viewerName) els.viewerName.textContent = currentViewerName;
  if (els.viewerRole) els.viewerRole.textContent = snapshot.viewer_role || 'Household member';
  if (els.viewerAvatar) els.viewerAvatar.textContent = currentViewerName.charAt(0).toUpperCase();
  const todayLabel = formatDate(current, { weekday: 'long', month: 'long', day: 'numeric' });
  const shortDate = formatDate(current, { weekday: 'short', month: 'short', day: 'numeric' });
  const counts = snapshot.counts;
  const attentionItems = snapshot.attention_items || snapshot.attention || [];
  const todayItems = snapshot.today_items || snapshot.today || [];

  els.headerDate.textContent = todayLabel;
  els.todayHeading.textContent = formatDate(current, { weekday: 'long' });
  els.todayStamp.textContent = shortDate.toUpperCase();
  els.attentionMetric.textContent = attentionItems.length;
  els.todayMetric.textContent = todayItems.length;
  els.groceryMetric.textContent = counts.groceries;
  els.stateCount.textContent = attentionItems.length;
  els.stateTitle.textContent = attentionItems.length === 0 ? 'Clear the path' : attentionItems.length === 1 ? 'One loose thread' : 'Clear the path';
  els.stateRuleFill.style.width = `${Math.min(100, Math.max(8, attentionItems.length * 8))}%`;
  els.attentionBadge.textContent = `${attentionItems.length} open`;
  els.groceryCount.textContent = counts.groceries;
  els.footerTime.textContent = formatDate(current, { hour: 'numeric', minute: '2-digit' });

  renderAttention(attentionItems);
  renderTimeline(todayItems);
  renderUpcoming(snapshot.upcoming);
  renderPlanningWeek(snapshot.planning_week || []);
  renderGroceries(snapshot.groceries, snapshot.grocery_summary);
  renderInbox(snapshot.inbox || []);
  renderIntelligence(intelligence);
  els.error.classList.add('is-hidden');
}

async function loadDashboard() {
  setLoading(true);
  try {
    const [dashboardResponse, conflictsResponse, activityResponse, choresResponse] = await Promise.all([
      hearthstateFetch('/api/dashboard', { cache: 'no-store' }),
      hearthstateFetch('/api/conflicts', { cache: 'no-store' }),
      hearthstateFetch('/api/activity?viewer=you', { cache: 'no-store' }),
      hearthstateFetch('/api/chores', { cache: 'no-store' }),
    ]);
    if (!dashboardResponse.ok) throw new Error(`Dashboard request failed: ${dashboardResponse.status}`);
    const intelligence = {
      conflicts: conflictsResponse.ok ? (await conflictsResponse.json()).conflicts : [],
      activity: activityResponse.ok ? (await activityResponse.json()).activity : [],
      chores: choresResponse.ok ? (await choresResponse.json()).chores : [],
    };
    render(await dashboardResponse.json(), intelligence);
  } catch (error) {
    els.error.textContent = 'Could not load the household state. Check your hosted session and try again.';
    els.error.classList.remove('is-hidden');
    els.syncStatus.textContent = 'Offline';
    console.error(error);
  } finally {
    setLoading(false);
  }
}

els.themeToggle.addEventListener('click', () => {
  const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  setTheme(nextTheme);
});
els.refresh.addEventListener('click', loadDashboard);
els.inboxCaptureForm.addEventListener('submit', captureInboxItem);
els.inboxConvertForm.addEventListener('submit', submitInboxConversion);
els.inboxConvertType.addEventListener('change', setInboxConversionFields);
els.inboxConvertCancel.addEventListener('click', closeInboxConversion);
els.inboxRejectSuggestion.addEventListener('click', rejectInboxSuggestion);
syncThemeButton();
applyViewerBootstrap();
updateGreeting();
window.setInterval(updateGreeting, 60_000);
loadDashboard();
