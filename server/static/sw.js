const CACHE = 'family-portal-v2025-07-06b';

self.addEventListener('install', (e) => {
  // Warm the shell so an installed PWA can open offline; assets cache on first fetch.
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.add('/').catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.pathname.startsWith('/api/')) return;

  // App shell / navigations: network first so deploys reach installed clients,
  // falling back to cache when offline.
  if (req.mode === 'navigate' || url.pathname === '/') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(req, clone));
          }
          return res;
        })
        .catch(() => caches.match(req).then((cached) => cached || caches.match('/')))
    );
    return;
  }

  // Versioned same-origin static assets: cache first (immutable per ?v=),
  // then network, caching the response for next time.
  if (url.origin === self.location.origin && url.pathname.startsWith('/static/') && url.searchParams.has('v')) {
    e.respondWith(
      caches.match(req).then(
        (cached) =>
          cached ||
          fetch(req).then((res) => {
            if (res.ok) {
              const clone = res.clone();
              caches.open(CACHE).then((c) => c.put(req, clone));
            }
            return res;
          })
      )
    );
  }
  // Everything else (unversioned statics, fonts, etc.) goes straight to the network.
});
