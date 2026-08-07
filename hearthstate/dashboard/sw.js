const CACHE_NAME = 'hearthstate-static-v9';
const PRECACHE_URLS = [
  '/manifest.webmanifest',
  '/favicon.svg?v=hearthstate-rebrand-1',
  '/brand-mark.svg?v=hearthstate-brand-1',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/styles.css?v=hearthstate-ui-5',
  '/nav.js?v=hearthstate-pwa-3',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  const cacheablePath = new Set([
    '/manifest.webmanifest',
    '/favicon.svg',
    '/brand-mark.svg',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/styles.css',
    '/nav.js',
    '/app.js',
    '/section.js',
    '/meals.js',
    '/chores.js',
    '/groceries.js',
    '/recipes.js',
    '/admin.js',
    '/notifications.js',
  ]);

  // Never cache household HTML, API responses, analytics, or cross-origin data.
  if (request.method !== 'GET' || url.origin !== self.location.origin || !cacheablePath.has(url.pathname)) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (!response.ok) return response;
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
      });
    }),
  );
});
