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

  const toggle = document.querySelector('.mobile-nav-toggle');
  const nav = document.querySelector('#primaryNav');
  const sidebar = document.querySelector('.sidebar');
  if (!toggle || !nav || !sidebar) return;

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
    })
    .catch(() => {
      // Compatibility-mode households do not have an administration area.
    });
})();
