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
  error: document.querySelector('#errorBanner'),
};

const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));

const formatDate = (value, options) => new Intl.DateTimeFormat(undefined, options).format(new Date(value));

function getTimeOfDayGreeting(hour = new Date().getHours()) {
  if (hour >= 5 && hour < 12) {
    return { title: 'Good morning, family.', eyebrow: 'A CALM START TO THE DAY' };
  }
  if (hour >= 12 && hour < 17) {
    return { title: 'Good afternoon, family.', eyebrow: 'A CALM PAUSE IN THE DAY' };
  }
  if (hour >= 17 && hour < 21) {
    return { title: 'Good evening, family.', eyebrow: 'A CALM EVENING AT HOME' };
  }
  return { title: 'Good evening, family.', eyebrow: 'A QUIET END TO THE DAY' };
}

function updateGreeting(now = new Date()) {
  const greeting = getTimeOfDayGreeting(now.getHours());
  els.greetingTitle.textContent = greeting.title;
  els.greetingEyebrow.textContent = greeting.eyebrow;
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
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/complete`, {
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

function render(snapshot) {
  const current = snapshot.generated_at;
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
  els.error.classList.add('is-hidden');
}

async function loadDashboard() {
  setLoading(true);
  try {
    const viewer = encodeURIComponent('you');
    const response = await fetch(`/api/dashboard?viewer=${viewer}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Dashboard request failed: ${response.status}`);
    render(await response.json());
  } catch (error) {
    els.error.textContent = 'Could not load the household state. Is the local Hearthstate service still running?';
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
syncThemeButton();
updateGreeting();
window.setInterval(updateGreeting, 60_000);
loadDashboard();
