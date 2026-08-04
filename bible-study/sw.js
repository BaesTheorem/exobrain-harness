/* Service worker: offline-first app shell, cache-as-you-read scripture data. */
'use strict';

const SHELL_CACHE = 'sb-shell-v1';
const DATA_CACHE = 'sb-data-v1';

const SHELL = [
  './',
  'index.html',
  'css/app.css',
  'js/app.js',
  'manifest.webmanifest',
  'icons/icon.svg',
  'icons/icon-192.png',
  'icons/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(SHELL_CACHE)
      .then(c => Promise.allSettled(SHELL.map(u => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== SHELL_CACHE && k !== DATA_CACHE).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || e.request.method !== 'GET') return;

  // Scripture data rarely changes after a build: cache first, then network.
  if (url.pathname.includes('/data/')) {
    e.respondWith(
      caches.open(DATA_CACHE).then(async cache => {
        const hit = await cache.match(e.request);
        if (hit) return hit;
        const resp = await fetch(e.request);
        if (resp.ok) cache.put(e.request, resp.clone());
        return resp;
      })
    );
    return;
  }

  // App shell: network first so updates land, cache fallback for offline.
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp.ok) {
        const copy = resp.clone();
        caches.open(SHELL_CACHE).then(c => c.put(e.request, copy));
      }
      return resp;
    }).catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
