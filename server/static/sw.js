const CACHE = 'family-portal-v2025-07-09';

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

// --- Push notifications ---
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    // Non-JSON payload — treat the raw text as the body.
    data = { body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'The Hub';
  // Update the home-screen app-icon badge count (iOS 16.4+ / Android / desktop PWA).
  if (typeof data.badge_count === 'number') {
    try {
      if (data.badge_count > 0) navigator.setAppBadge?.(data.badge_count);
      else navigator.clearAppBadge?.();
    } catch { /* badging unsupported — ignore */ }
  }
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Focus an already-open tab (and navigate it) rather than opening a duplicate.
      for (const client of clients) {
        if ('focus' in client) {
          if (client.navigate) client.navigate(url).catch(() => {});
          return client.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
