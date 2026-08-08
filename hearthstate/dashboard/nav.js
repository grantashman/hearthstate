(() => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
      // Progressive enhancement only: the hosted dashboard remains usable without a service worker.
    });
  }

  window.hearthstateFetch = (input, options = {}) => {
    const headers = new Headers(options.headers || {});
    const householdId = window.__HEARTHSTATE_VIEWER__?.household_id;
    if (householdId) headers.set('X-Hearthstate-Household', householdId);
    return fetch(input, { ...options, headers });
  };

  const viewer = window.__HEARTHSTATE_VIEWER__;
  if (viewer) {
    document.querySelectorAll('#viewerName').forEach((element) => { element.textContent = viewer.name || 'Household member'; });
    document.querySelectorAll('#viewerRole').forEach((element) => { element.textContent = viewer.role || 'Household member'; });
    document.querySelectorAll('#viewerAvatar').forEach((element) => { element.textContent = (viewer.name || 'H').charAt(0).toUpperCase(); });
  }

  const toggle = document.querySelector('.mobile-nav-toggle');
  const nav = document.querySelector('#primaryNav');
  const sidebar = document.querySelector('.sidebar');

  const navIconMarkup = {
    '/': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12.5 12 5l8 7.5v7a1 1 0 0 1-1 1h-4.2v-5.2H9.2V20H5a1 1 0 0 1-1-1v-6.5Z"/><path d="m8 9.8 4-3.7 4 3.7"/></svg>',
    '/calendar': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5.5" width="16" height="14" rx="1.5"/><path d="M8 3.5v4M16 3.5v4M4 10h16"/></svg>',
    '/tasks': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5.5h12a1.5 1.5 0 0 1 1.5 1.5v10.5A1.5 1.5 0 0 1 18 19H6a1.5 1.5 0 0 1-1.5-1.5V7A1.5 1.5 0 0 1 6 5.5Z"/><path d="m8 12 2.2 2.2L16 8.5"/></svg>',
    '/chores': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7a7 7 0 1 1-1 9"/><path d="M7 3.5v4h4"/></svg>',
    '/meals': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 15h14M6 15a6 6 0 0 0 12 0M9 11.5c0-1.6 1.2-2.1 1.2-3.5M12 11.5c0-1.6 1.2-2.1 1.2-3.5M15 11.5c0-1.6 1.2-2.1 1.2-3.5"/></svg>',
    '/recipes': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3.8 2.4 5 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5-3.9-4.2 5.4-.8L12 3.8Z"/></svg>',
    '/groceries': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9h14l-1 11H6L5 9Z"/><path d="M8.5 9a3.5 3.5 0 0 1 7 0"/></svg>',
    '/admin': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.5"/><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6 18 18M18 6l-1.4 1.4M7.4 16.6 6 18"/></svg>',
  };

  const normalizeNavIcons = () => {
    if (!nav) return;
    nav.querySelectorAll('.nav-item').forEach((item) => {
      if (item.querySelector('svg')) return;
      const icon = item.querySelector('.nav-symbol');
      if (!icon) return;
      const pathname = new URL(item.getAttribute('href') || '/', window.location.href).pathname.replace(/\/$/, '') || '/';
      const markup = navIconMarkup[pathname];
      if (markup) icon.innerHTML = markup;
    });
  };

  const normalizeActionIcons = () => {
    const themeButton = document.querySelector('.theme-button');
    if (themeButton && !themeButton.querySelector('svg')) {
      themeButton.innerHTML = '<svg class="theme-icon theme-icon-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 14.3A7.8 7.8 0 0 1 9.7 4.5 7.8 7.8 0 1 0 19.5 14.3Z"/></svg><svg class="theme-icon theme-icon-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.5"/><path d="M12 2.8v2M12 19.2v2M21.2 12h-2M4.8 12h-2M18.5 5.5l-1.4 1.4M6.9 17.1l-1.4 1.4M18.5 18.5l-1.4-1.4M6.9 6.9 5.5 5.5"/></svg>';
    }
    const refreshButton = document.querySelector('button.refresh-button');
    if (refreshButton && !refreshButton.querySelector('svg')) {
      refreshButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8.1 8.1 0 0 0-14.8-3L4 10"/><path d="M4 5v5h5M4 13a8.1 8.1 0 0 0 14.8 3L20 14"/><path d="M20 19v-5h-5"/></svg>';
    }
    const adminRefresh = document.querySelector('a.admin-refresh');
    if (adminRefresh && !adminRefresh.querySelector('svg')) {
      adminRefresh.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8.1 8.1 0 0 0-14.8-3L4 10"/><path d="M4 5v5h5M4 13a8.1 8.1 0 0 0 14.8 3L20 14"/><path d="M20 19v-5h-5"/></svg>';
    }
    const settingsLink = document.querySelector('a.refresh-button:not(.admin-refresh)');
    if (settingsLink && !settingsLink.querySelector('svg')) {
      settingsLink.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 17 10-10M9 7h8v8"/></svg>';
    }
  };

  if (!toggle || !nav || !sidebar) return;

  normalizeNavIcons();
  normalizeActionIcons();

  const closeMenu = () => {
    sidebar.classList.remove('nav-open');
    toggle.setAttribute('aria-expanded', 'false');
  };

  toggle.addEventListener('click', () => {
    const isOpen = sidebar.classList.toggle('nav-open');
    toggle.setAttribute('aria-expanded', String(isOpen));
  });

  nav.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeMenu();
  });

  document.addEventListener('click', (event) => {
    if (!sidebar.contains(event.target)) closeMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenu();
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 780) closeMenu();
  });

  let deferredInstallPrompt = null;
  const topbarActions = document.querySelector('.topbar-actions');
  if (topbarActions && !document.querySelector('#installAppButton')) {
    const installButton = document.createElement('button');
    installButton.id = 'installAppButton';
    installButton.className = 'install-button is-hidden';
    installButton.type = 'button';
    installButton.setAttribute('aria-label', 'Install Hearthstate as an app');
    installButton.textContent = 'Install app';
    topbarActions.insertBefore(installButton, topbarActions.firstChild);

    window.addEventListener('beforeinstallprompt', (event) => {
      event.preventDefault();
      deferredInstallPrompt = event;
      installButton.classList.remove('is-hidden');
    });
    window.addEventListener('appinstalled', () => {
      deferredInstallPrompt = null;
      installButton.classList.add('is-hidden');
    });
    installButton.addEventListener('click', async () => {
      if (!deferredInstallPrompt) return;
      const promptEvent = deferredInstallPrompt;
      deferredInstallPrompt = null;
      installButton.classList.add('is-hidden');
      await promptEvent.prompt();
      await promptEvent.userChoice;
    });
  }

  window.hearthstateFetch('/api/admin', { cache: 'no-store' })
    .then((response) => {
      if (!response.ok || document.querySelector('a[href="/admin"]')) return;
      const adminLink = document.createElement('a');
      adminLink.className = 'nav-item';
      adminLink.href = '/admin';
      adminLink.innerHTML = '<span class="nav-symbol">⚙</span>Administration';
      nav.appendChild(adminLink);
      normalizeNavIcons();
    })
    .catch(() => {
      // Compatibility-mode households do not have an administration area.
    });
})();
