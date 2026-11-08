// 홈 화면 앱용 서비스 워커: 언제나 네트워크 먼저(최신 예측), 끊겼을 때만 마지막으로 본 내용을 보여 준다.
const CACHE = "horse-site-v2";
self.addEventListener("install", e => { self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const font = /fonts\.(googleapis|gstatic)\.com$/.test(url.hostname) || (url.hostname === "cdn.jsdelivr.net" && url.pathname.includes("/pretendard"));
  if (url.origin !== location.origin && !font) return;
  if (font) {   // 글꼴은 바뀌지 않으니 저장해 둔 것 먼저
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => { const c = res.clone(); caches.open(CACHE).then(x => x.put(req, c)); return res; })));
    return;
  }
  // 시뮬레이션 파일은 크고 많아서 저장하지 않음 (오프라인이면 그 화면만 안 열림)
  const keep = !url.pathname.includes("/data/sim/");
  e.respondWith(fetch(req).then(res => {
    if (keep && res.ok) { const c = res.clone(); caches.open(CACHE).then(x => x.put(req, c)); }
    return res;
  }).catch(() => caches.match(req, {ignoreSearch: url.pathname.endsWith(".html") || url.pathname.endsWith("/")})
    .then(hit => hit || new Response("오프라인입니다. 연결되면 다시 열어 주세요.", {status: 503, headers: {"Content-Type": "text/plain; charset=utf-8"}}))));
});
