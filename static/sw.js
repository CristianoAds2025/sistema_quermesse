const CACHE_STATIC = "quermesse-static-v4";
const CACHE_DYNAMIC = "quermesse-dynamic-v4";

// Arquivos realmente estáticos
const STATIC_ASSETS = [
  "/static/css/style.css",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512x512.png"
];

// ================= INSTALL =================
self.addEventListener("install", event => {
  self.skipWaiting(); // ativa imediatamente

  event.waitUntil(
    caches.open(CACHE_STATIC)
      .then(cache => cache.addAll(STATIC_ASSETS))
  );
});

// ================= ACTIVATE =================
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(key => key !== CACHE_STATIC && key !== CACHE_DYNAMIC)
          .map(key => caches.delete(key))
      );
    })
  );

  return self.clients.claim(); // assume controle imediato
});

// ================= FETCH =================
self.addEventListener("fetch", event => {

  // Ignorar requisições que não são GET
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);

  // 1️⃣ Arquivos estáticos → Cache First
  if (STATIC_ASSETS.includes(url.pathname)) {
    event.respondWith(
      caches.match(event.request).then(response => {
        return response || fetch(event.request);
      })
    );
    return;
  }

  // 2️⃣ Rotas Flask / páginas → Network First
  event.respondWith(
    fetch(event.request)
      .then(response => {
        return caches.open(CACHE_DYNAMIC).then(cache => {
          cache.put(event.request, response.clone());
          return response;
        });
      })
      .catch(() => caches.match(event.request))
  );
});

// ================= ATUALIZAÇÃO AUTOMÁTICA =================
self.addEventListener("message", event => {
  if (event.data === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
