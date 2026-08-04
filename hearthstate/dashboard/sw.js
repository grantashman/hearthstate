const CACHE_NAME = 'hearthstate-static-v2';
const PRECACHE_URLS = [
  '/manifest.webmanifest',
  '/favicon.svg?v=hearthstate-pwa-1',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/styles.css?v=hearthstate-pwa-1',
  '/nav.js?v=hearthstate-pwa-1',
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
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/styles.css',
    '/nav.js',
    '/app.js',
    '/section.js',
    '/meals.js',
    '/groceries.js',
    '/recipes.js',
    '/admin.js',
    '/notifications.js',
  ]);

  // Never cache household HTML, API responses, analytics, or cross-origin data.
  if (request.method !== 'GET' || url.origin !== self.location.origin || !cacheablePath.has(url.pathname)) return;

  event.respondWith(
    caches.match(request, { ignoreSearch: true }).then((cached) => {
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
