(() => {
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

  fetch('/api/admin', { cache: 'no-store' })
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
