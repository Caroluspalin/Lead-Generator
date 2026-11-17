import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deviceType, handleRequest, isDemoPath, isExpired, openKey, SECURITY_HEADERS } from '../src/index.ts';
import type { DemoBucket, DemoObject } from '../src/index.ts';

const TOKEN = 'A'.repeat(20) + '_-' + 'b'.repeat(21); // 43 merkkiä
const SLUG = 'taina-lantiainen-k7x2m';
const NOW = new Date('2026-11-06T12:00:00Z');

class FakeBucket implements DemoBucket {
  objects = new Map<string, DemoObject>();
  keys: string[] = [];

  async get(key: string): Promise<DemoObject | null> {
    this.keys.push(key);
    return this.objects.get(key) ?? null;
  }

  puts: string[] = [];
  failPut = false;
  async put(key: string): Promise<unknown> {
    if (this.failPut) throw new Error('R2 down');
    this.puts.push(key);
    return undefined;
  }
}

const env = (bucket: FakeBucket) => ({ DEMOS: bucket });
const get = (path: string, method = 'GET') => new Request(`https://agency-hunter-demos.example.workers.dev${path}`, { method });

test('serves published demo with security headers', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${TOKEN}.html`, {
    body: '<!doctype html><title>Demo</title>',
    customMetadata: { 'expires-at': '2026-12-06T12:00:00+00:00' },
  });
  const res = await handleRequest(get(`/${TOKEN}`), env(bucket), NOW);
  assert.equal(res.status, 200);
  assert.equal(await res.text(), '<!doctype html><title>Demo</title>');
  assert.equal(res.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(res.headers.get('x-robots-tag'), 'noindex, nofollow');
  assert.match(res.headers.get('content-security-policy') ?? '', /img-src data: https:\/\/images\.unsplash\.com https:\/\/scaled-images\.timma\.fi;/);
  assert.equal(res.headers.get('cache-control'), 'no-store');
  assert.deepEqual(bucket.keys, [`demos/${TOKEN}.html`]);
});

test('same path works on any domain (custom domain needs no code change)', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${TOKEN}.html`, { body: 'ok' });
  const res = await handleRequest(new Request(`https://demo.esimerkki.fi/${TOKEN}`), env(bucket), NOW);
  assert.equal(res.status, 200);
});

test('expired demo is 410 even if object still exists', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${TOKEN}.html`, { body: 'x', customMetadata: { 'expires-at': '2026-11-01T00:00:00+00:00' } });
  const res = await handleRequest(get(`/${TOKEN}`), env(bucket), NOW);
  assert.equal(res.status, 410);
  assert.equal(res.headers.get('x-robots-tag'), 'noindex, nofollow');
});

test('missing or malformed token is 404 without touching R2 for bad tokens', async () => {
  const bucket = new FakeBucket();
  assert.equal((await handleRequest(get(`/${TOKEN}`), env(bucket), NOW)).status, 404);
  for (const path of ['/', '/short', `/${TOKEN}x`, '/../secret', `/demos/${TOKEN}.html`]) {
    assert.equal((await handleRequest(get(path), env(bucket), NOW)).status, 404, path);
  }
  assert.equal(bucket.keys.length, 1);
});

test('only GET and HEAD allowed', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${TOKEN}.html`, { body: 'x' });
  assert.equal((await handleRequest(get(`/${TOKEN}`, 'POST'), env(bucket), NOW)).status, 405);
  const head = await handleRequest(get(`/${TOKEN}`, 'HEAD'), env(bucket), NOW);
  assert.equal(head.status, 200);
  assert.equal(await head.text(), '');
});

test('robots.txt disallows everything', async () => {
  const res = await handleRequest(get('/robots.txt'), env(new FakeBucket()), NOW);
  assert.equal(await res.text(), 'User-agent: *\nDisallow: /\n');
});

test('isExpired', () => {
  assert.equal(isExpired(undefined, NOW), false);
  assert.equal(isExpired({}, NOW), false);
  assert.equal(isExpired({ 'expires-at': 'garbage' }, NOW), false);
  assert.equal(isExpired({ 'expires-at': '2026-11-06T12:00:00Z' }, NOW), true);
  assert.equal(isExpired({ 'expires-at': '2026-11-06T12:00:01Z' }, NOW), false);
});

test('headers match backend demo headers (frame-ancestors added on worker)', () => {
  assert.equal(SECURITY_HEADERS['Referrer-Policy'], 'no-referrer');
});

test('serves demo by readable slug address', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${SLUG}.html`, { body: 'slug demo', customMetadata: { 'expires-at': '2026-12-06T12:00:00+00:00' } });
  const res = await handleRequest(get(`/${SLUG}`), env(bucket), NOW);
  assert.equal(res.status, 200);
  assert.equal(await res.text(), 'slug demo');
  assert.equal(res.headers.get('x-robots-tag'), 'noindex, nofollow');
  assert.deepEqual(bucket.keys, [`demos/${SLUG}.html`]);
});

test('old token address keeps working next to slugs', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${TOKEN}.html`, { body: 'old' });
  bucket.objects.set(`demos/${SLUG}.html`, { body: 'new' });
  assert.equal(await (await handleRequest(get(`/${TOKEN}`), env(bucket), NOW)).text(), 'old');
  assert.equal(await (await handleRequest(get(`/${SLUG}`), env(bucket), NOW)).text(), 'new');
});

test('expired slug demo is 410', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${SLUG}.html`, { body: 'x', customMetadata: { 'expires-at': '2026-11-01T00:00:00+00:00' } });
  assert.equal((await handleRequest(get(`/${SLUG}`), env(bucket), NOW)).status, 410);
});

test('isDemoPath accepts only exact slug or token shapes', () => {
  for (const ok of [SLUG, TOKEN, 'demo-abcde', 'kahvila-sade-pollo-23456', `${'a'.repeat(40)}-k7x2m`]) {
    assert.equal(isDemoPath(ok), true, ok);
  }
  for (const bad of [
    'taina-lantiainen', // ei satunnaisosaa
    'taina-lantiainen-k7x2', // liian lyhyt satunnaisosa
    'taina-lantiainen-k7x2m9', // liian pitkä
    'taina-lantiainen-k0x2m', // 0 ei kuulu aakkostoon
    'Taina-Lantiainen-k7x2m', // isot kirjaimet
    '-taina-k7x2m',
    'taina--k7x2m',
    `${'a'.repeat(41)}-k7x2m`, // nimiosa yli 40
    'taina/../k7x2m',
    'demos/taina-lantiainen-k7x2m.html',
    '',
  ]) {
    assert.equal(isDemoPath(bad), false, bad);
  }
});

test('malformed slug-like paths are 404 without touching R2', async () => {
  const bucket = new FakeBucket();
  for (const path of ['/taina-lantiainen', '/taina-lantiainen-k7x2', '/TAINA-k7x2m', '/taina-lantiainen-k7x2m.html']) {
    assert.equal((await handleRequest(get(path), env(bucket), NOW)).status, 404, path);
  }
  assert.equal(bucket.keys.length, 0);
});

// --- Version 2: erilliset tiedostot ja CSP ---

test('format 2 demo gets CSP that allows own files but no inline code', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${SLUG}.html`, { body: 'x', customMetadata: { format: '2' } });
  const res = await handleRequest(get(`/${SLUG}`), env(bucket), NOW);
  const csp = res.headers.get('content-security-policy') ?? '';
  assert.match(csp, /style-src 'self';/);
  assert.match(csp, /script-src 'self';/);
  assert.match(csp, /font-src 'self';/);
  // Pohjan omat kuvat (/a/...) samasta osoitteesta; ei media-src:ää
  assert.match(csp, /img-src 'self' data: https:\/\/images\.unsplash\.com https:\/\/scaled-images\.timma\.fi;/);
  assert.doesNotMatch(csp, /media-src/);
  assert.match(csp, /frame-ancestors 'none'/);
  assert.doesNotMatch(csp, /unsafe-inline/);
});

test('format 2 demo on custom domain is noindex and keeps the demo banner unchanged', async () => {
  const bucket = new FakeBucket();
  const html = '<!doctype html><p class="demo-bar">Tämä on luonnos – ei yrityksen virallinen sivu.</p>';
  bucket.objects.set(`demos/${SLUG}.html`, { body: html, customMetadata: { format: '2' } });
  const res = await handleRequest(new Request(`https://demo.palinweb.fi/${SLUG}`), env(bucket), NOW);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('x-robots-tag'), 'noindex, nofollow');
  assert.equal(await res.text(), html);
});

test('old demo without format keeps inline-only CSP', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${SLUG}.html`, { body: 'x' });
  const csp = (await handleRequest(get(`/${SLUG}`), env(bucket), NOW)).headers.get('content-security-policy') ?? '';
  assert.match(csp, /style-src 'unsafe-inline'/);
  assert.doesNotMatch(csp, /script-src/);
});

test('serves versioned asset from content-addressed key with immutable caching and CORS', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set('assets/cafe/0123456789/young-serif.woff2', { body: 'font' });
  const res = await handleRequest(get('/a/cafe/young-serif.woff2?v=0123456789'), env(bucket), NOW);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-type'), 'font/woff2');
  assert.equal(res.headers.get('cache-control'), 'public, max-age=31536000, immutable');
  assert.equal(res.headers.get('access-control-allow-origin'), '*');
  assert.equal(res.headers.get('x-robots-tag'), 'noindex, nofollow');
  assert.deepEqual(bucket.keys, ['assets/cafe/0123456789/young-serif.woff2']);
});

test('asset content type comes from extension', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set('assets/yhteinen/abcdef0123/aukiolo.js', { body: 'js' });
  bucket.objects.set('assets/cafe/abcdef0123/tyylit.css', { body: 'css' });
  assert.equal(
    (await handleRequest(get('/a/yhteinen/aukiolo.js?v=abcdef0123'), env(bucket), NOW)).headers.get('content-type'),
    'text/javascript; charset=utf-8',
  );
  assert.equal(
    (await handleRequest(get('/a/cafe/tyylit.css?v=abcdef0123'), env(bucket), NOW)).headers.get('content-type'),
    'text/css; charset=utf-8',
  );
});

test('template images are served as webp and avif', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set('assets/premium/abcdef0123/rappaus.avif', { body: 'avif' });
  bucket.objects.set('assets/premium/abcdef0123/rappaus.webp', { body: 'webp' });
  const avif = await handleRequest(get('/a/premium/rappaus.avif?v=abcdef0123'), env(bucket), NOW);
  assert.equal(avif.status, 200);
  assert.equal(avif.headers.get('content-type'), 'image/avif');
  assert.equal(avif.headers.get('cache-control'), 'public, max-age=31536000, immutable');
  assert.equal(
    (await handleRequest(get('/a/premium/rappaus.webp?v=abcdef0123'), env(bucket), NOW)).headers.get('content-type'),
    'image/webp',
  );
});

test('malformed asset paths and missing version are 404 without touching R2', async () => {
  const bucket = new FakeBucket();
  for (const path of [
    '/a/cafe/tyylit.css',
    '/a/cafe/tyylit.css?v=zz',
    '/a/cafe/tyylit.html?v=0123456789',
    '/a/../demos/x.html?v=0123456789',
    '/a/cafe/sub/tyylit.css?v=0123456789',
    '/a/Cafe/tyylit.css?v=0123456789',
    '/a/cafe/OFL.txt?v=0123456789',
    '/a/barber_premium/tyylit.css?v=0123456789',
    '/a/premium/rappaus.png?v=0123456789',
    '/a/premium/video.mp4?v=0123456789',
  ]) {
    assert.equal((await handleRequest(get(path), env(bucket), NOW)).status, 404, path);
  }
  assert.deepEqual(bucket.keys, []);
});

test('unknown asset version is 404', async () => {
  const bucket = new FakeBucket();
  assert.equal((await handleRequest(get('/a/cafe/tyylit.css?v=0123456789'), env(bucket), NOW)).status, 404);
});

// --- Avausten kirjaus ---

const CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

function openRequest(path: string, headers: Record<string, string>, method = 'GET'): Request {
  return new Request(`https://demo.example.fi${path}`, {
    method,
    headers: { accept: 'text/html,application/xhtml+xml', ...headers },
  });
}

async function openPuts(request: Request, setup?: (b: FakeBucket) => void): Promise<{ bucket: FakeBucket; res: Response; waited: Promise<unknown>[] }> {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${SLUG}.html`, { body: 'ok' });
  setup?.(bucket);
  const waited: Promise<unknown>[] = [];
  const res = await handleRequest(request, env(bucket), NOW, { waitUntil: (p) => void waited.push(p) });
  await Promise.all(waited);
  return { bucket, res, waited };
}

test('records a normal open with bucket and device only', async () => {
  const { bucket, res } = await openPuts(openRequest(`/${SLUG}`, { 'user-agent': CHROME }));
  assert.equal(res.status, 200);
  assert.deepEqual(bucket.puts, [openKey(SLUG, 'desktop', NOW)]);
  assert.match(bucket.puts[0], /^opens\/taina-lantiainen-k7x2m\/\d+-desktop$/);
});

test('mobile device from user agent and from client hint', async () => {
  const { bucket } = await openPuts(openRequest(`/${SLUG}`, { 'user-agent': IPHONE }));
  assert.match(bucket.puts[0], /-mobile$/);
  assert.equal(deviceType(new Headers({ 'sec-ch-ua-mobile': '?0', 'user-agent': IPHONE })), 'desktop');
});

test('same bucket and device gives the same key (dedup), new bucket a new key', () => {
  const later = new Date(NOW.getTime() + 5 * 60 * 1000);
  const muchLater = new Date(NOW.getTime() + 11 * 60 * 1000);
  const base = openKey(SLUG, 'desktop', NOW);
  assert.equal(base, openKey(SLUG, 'desktop', later));
  assert.notEqual(openKey(SLUG, 'desktop', NOW), openKey(SLUG, 'mobile', NOW));
  assert.notEqual(openKey(SLUG, 'desktop', NOW), openKey(SLUG, 'desktop', muchLater));
});

test('own opens with ?preview=1 are not recorded', async () => {
  const { bucket, res } = await openPuts(openRequest(`/${SLUG}?preview=1`, { 'user-agent': CHROME }));
  assert.equal(res.status, 200);
  assert.deepEqual(bucket.puts, []);
});

test('bots and link previewers are not recorded', async () => {
  const agents = [
    '',
    'facebookexternalhit/1.1',
    'WhatsApp/2.23.20 A',
    'Slackbot-LinkExpanding 1.0',
    'Googlebot/2.1',
    'Mozilla/5.0 (Macintosh) Mimecast Link Scanner',
    'python-requests/2.31',
    'curl/8.0',
    'Mozilla/5.0 AppleWebKit/537.36 HeadlessChrome/120.0 Safari/537.36',
    'Mozilla/5.0 (compatible; Microsoft Office Protocol Discovery)',
  ];
  for (const ua of agents) {
    const { bucket, res } = await openPuts(openRequest(`/${SLUG}`, { 'user-agent': ua }));
    assert.equal(res.status, 200, ua);
    assert.deepEqual(bucket.puts, [], ua);
  }
});

test('prefetch, non-html accept, HEAD, 404 and 410 are not recorded', async () => {
  const cases: Request[] = [
    openRequest(`/${SLUG}`, { 'user-agent': CHROME, purpose: 'prefetch' }),
    openRequest(`/${SLUG}`, { 'user-agent': CHROME, 'sec-purpose': 'prefetch;prerender' }),
    openRequest(`/${SLUG}`, { 'user-agent': CHROME, accept: '*/*' }),
    openRequest(`/${SLUG}`, { 'user-agent': CHROME }, 'HEAD'),
    openRequest('/ei-olemassa-k7x2m', { 'user-agent': CHROME }),
  ];
  for (const request of cases) {
    const { bucket } = await openPuts(request);
    assert.deepEqual(bucket.puts, [], request.url);
  }
  const { bucket } = await openPuts(openRequest(`/${SLUG}`, { 'user-agent': CHROME }), (b) =>
    b.objects.set(`demos/${SLUG}.html`, { body: 'x', customMetadata: { 'expires-at': '2026-11-01T00:00:00+00:00' } }),
  );
  assert.deepEqual(bucket.puts, []);
});

test('recording is deferred via waitUntil and a failing write does not break the page', async () => {
  const bucket = new FakeBucket();
  bucket.objects.set(`demos/${SLUG}.html`, { body: 'ok' });
  bucket.failPut = true;
  const waited: Promise<unknown>[] = [];
  const res = await handleRequest(openRequest(`/${SLUG}`, { 'user-agent': CHROME }), env(bucket), NOW, {
    waitUntil: (p) => void waited.push(p),
  });
  assert.equal(res.status, 200);
  assert.equal(await res.text(), 'ok');
  assert.equal(waited.length, 1);
  await assert.doesNotReject(Promise.all(waited));
});
