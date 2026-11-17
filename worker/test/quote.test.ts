import { test } from 'node:test';
import assert from 'node:assert/strict';
import { handleRequest } from '../src/index.ts';
import type { DemoBucket, DemoObject, PutOptions } from '../src/index.ts';
import { ACCEPT_END, ACCEPT_START, QUOTE_CSP, QUOTE_JS, escapeHtml, validateAcceptRequest } from '../src/quote.ts';

const TOKEN = 'Q'.repeat(20) + '_-' + 'z'.repeat(21);
const HASH = 'a'.repeat(64);
const NOW = new Date('2026-11-18T08:00:00Z');
const SIG = 'data:image/png;base64,' + 'A'.repeat(400);
const PAGE = `<html><body><h1>Tarjous</h1>${ACCEPT_START}<form id="accept-form">lomake</form>${ACCEPT_END}</body></html>`;

class FakeBucket implements DemoBucket {
  objects = new Map<string, DemoObject>();
  puts: { key: string; value: string; options?: PutOptions }[] = [];
  async get(key: string): Promise<DemoObject | null> {
    return this.objects.get(key) ?? null;
  }
  async put(key: string, value: string, options?: PutOptions): Promise<unknown> {
    if (options?.onlyIf?.etagDoesNotMatch === '*' && this.objects.has(key)) return null;
    this.puts.push({ key, value, options });
    this.objects.set(key, { body: value });
    return {};
  }
}

const env = (b: FakeBucket) => ({ DEMOS: b });
const publish = (b: FakeBucket, meta: Record<string, string> = {}) =>
  b.objects.set(`quotes/${TOKEN}.html`, {
    body: PAGE,
    customMetadata: { 'expires-at': '2026-12-18T08:00:00+00:00', 'content-hash': HASH, state: 'open', ...meta },
  });
const BASE = 'https://demo.palinweb.fi';
const get = (path: string, headers: Record<string, string> = {}) =>
  new Request(`${BASE}${path}`, { headers: { accept: 'text/html', 'user-agent': 'Mozilla/5.0 (iPhone) Mobile', ...headers } });
const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request(`${BASE}/q/${TOKEN}/accept`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', origin: BASE, ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
const good = { name: ' Maija Meikäläinen ', authority: true, accept: true, signature: SIG };

test('serves quote page: noindex, own CSP, no Lead-Generator name', async () => {
  const b = new FakeBucket();
  publish(b);
  const res = await handleRequest(get(`/q/${TOKEN}`), env(b), NOW);
  assert.equal(res.status, 200);
  assert.equal(await res.text(), PAGE);
  assert.equal(res.headers.get('x-robots-tag'), 'noindex, nofollow');
  assert.equal(res.headers.get('content-security-policy'), QUOTE_CSP);
  assert.match(QUOTE_CSP, /script-src 'self'/);
  assert.doesNotMatch(QUOTE_CSP, /script-src[^;]*unsafe/);
  assert.equal(res.headers.get('cache-control'), 'no-store');
});

test('missing, malformed and expired quote paths', async () => {
  const b = new FakeBucket();
  assert.equal((await handleRequest(get(`/q/${TOKEN}`), env(b), NOW)).status, 404);
  for (const p of ['/q/', '/q/short', `/q/${TOKEN}x`, `/q/${TOKEN}/other`, '/q/../x']) {
    assert.equal((await handleRequest(get(p), env(b), NOW)).status, 404, p);
  }
  publish(b, { 'expires-at': '2026-11-01T00:00:00+00:00' });
  assert.equal((await handleRequest(get(`/q/${TOKEN}`), env(b), NOW)).status, 410);
});

test('serves quote script', async () => {
  const res = await handleRequest(get('/q/quote.js'), env(new FakeBucket()), NOW);
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-type') ?? '', /javascript/);
  assert.equal(await res.text(), QUOTE_JS);
  // Syntaksi kelpaa
  assert.doesNotThrow(() => new Function(QUOTE_JS));
});

test('open is recorded under q-<token> with the demo mechanism', async () => {
  const b = new FakeBucket();
  publish(b);
  const waits: Promise<unknown>[] = [];
  await handleRequest(get(`/q/${TOKEN}`), env(b), NOW, { waitUntil: (p) => void waits.push(p) });
  await Promise.all(waits);
  const slot = Math.floor(NOW.getTime() / 600000);
  assert.deepEqual(b.puts.map((p) => p.key), [`opens/q-${TOKEN}/${slot}-mobile`]);
});

test('previews, bots and ?preview=1 are not recorded', async () => {
  const b = new FakeBucket();
  publish(b);
  const ctx = { waitUntil: (p: Promise<unknown>) => void p };
  await handleRequest(get(`/q/${TOKEN}?preview=1`), env(b), NOW, ctx);
  await handleRequest(get(`/q/${TOKEN}`, { 'user-agent': 'WhatsApp/2.23' }), env(b), NOW, ctx);
  assert.equal(b.puts.length, 0);
});

test('accept stores name, Worker time, hash from metadata and signature; no IP or UA', async () => {
  const b = new FakeBucket();
  publish(b);
  const res = await handleRequest(post(good, { 'cf-connecting-ip': '1.2.3.4', 'user-agent': 'X' }), env(b), NOW);
  assert.equal(res.status, 200);
  const put = b.puts.find((p) => p.key === `acceptances/${TOKEN}.json`);
  assert.ok(put);
  assert.deepEqual(JSON.parse(put.value), {
    name: 'Maija Meikäläinen',
    accepted_at: '2026-11-18T08:00:00.000Z',
    content_hash: HASH,
    authority: true,
    signature: SIG,
  });
  assert.deepEqual(put.options?.onlyIf, { etagDoesNotMatch: '*' });
  assert.doesNotMatch(put.value, /1\.2\.3\.4|Mozilla/);
});

test('client cannot set time or hash', async () => {
  const b = new FakeBucket();
  publish(b);
  await handleRequest(post({ ...good, accepted_at: '2000-01-01T00:00:00Z', content_hash: 'f'.repeat(64) }), env(b), NOW);
  const stored = JSON.parse(b.puts[0].value);
  assert.equal(stored.accepted_at, NOW.toISOString());
  assert.equal(stored.content_hash, HASH);
});

test('existing acceptance is never overwritten (sequential and racing)', async () => {
  const b = new FakeBucket();
  publish(b);
  assert.equal((await handleRequest(post(good), env(b), NOW)).status, 200);
  const first = b.objects.get(`acceptances/${TOKEN}.json`);
  const second = await handleRequest(post({ ...good, name: 'Joku Toinen' }), env(b), new Date(NOW.getTime() + 60000));
  assert.equal(second.status, 409);
  assert.equal(b.objects.get(`acceptances/${TOKEN}.json`), first);

  // Kilpa: get ei vielä näe objektia, mutta onlyIf estää kirjoituksen
  const racing = new FakeBucket();
  publish(racing);
  racing.objects.set(`acceptances/${TOKEN}.json`, { body: '{}' });
  const realGet = racing.get.bind(racing);
  racing.get = async (key: string) => (key.startsWith('acceptances/') ? null : realGet(key));
  assert.equal((await handleRequest(post(good), env(racing), NOW)).status, 409);
});

test('accept rejects invalid input and wrong state', async () => {
  const b = new FakeBucket();
  publish(b);
  const cases: [unknown, number][] = [
    [{ ...good, name: '   ' }, 422],
    [{ ...good, name: 'x'.repeat(101) }, 422],
    [{ ...good, authority: false }, 422],
    [{ ...good, accept: undefined }, 422],
    [{ ...good, signature: 'data:text/html;base64,AAAA' }, 422],
    [{ ...good, signature: 'data:image/png;base64,AAAA' }, 422],
    ['not json', 400],
  ];
  for (const [body, status] of cases) {
    assert.equal((await handleRequest(post(body), env(b), NOW)).status, status, JSON.stringify(body).slice(0, 60));
  }
  assert.equal(b.puts.length, 0);
  assert.equal((await handleRequest(post(good, { origin: 'https://evil.example' }), env(b), NOW)).status, 403);
  assert.equal((await handleRequest(post(good, { 'content-type': 'text/plain' }), env(b), NOW)).status, 415);

  publish(b, { state: 'superseded' });
  assert.equal((await handleRequest(post(good), env(b), NOW)).status, 409);
  publish(b, { 'expires-at': '2026-11-01T00:00:00+00:00' });
  assert.equal((await handleRequest(post(good), env(b), NOW)).status, 410);
  publish(b, { 'content-hash': '' });
  assert.equal((await handleRequest(post(good), env(b), NOW)).status, 409);
  assert.equal((await handleRequest(post(good), env(new FakeBucket()), NOW)).status, 404);
  assert.equal(b.puts.length, 0);
});

test('accepted page shows name, time and signature in place of the form, even after expiry', async () => {
  const b = new FakeBucket();
  publish(b, { 'expires-at': '2026-11-01T00:00:00+00:00' });
  b.objects.set(`acceptances/${TOKEN}.json`, {
    body: JSON.stringify({ name: '<b>Maija</b>', accepted_at: '2026-11-18T08:00:00.000Z', content_hash: HASH, authority: true, signature: SIG }),
  });
  const res = await handleRequest(get(`/q/${TOKEN}`), env(b), NOW);
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.match(html, /Tarjous hyväksytty/);
  assert.match(html, /&lt;b&gt;Maija&lt;\/b&gt;/);
  assert.match(html, /18\. marraskuuta 2026 klo 10\.00/);
  assert.ok(html.includes(`src="${SIG}"`));
  assert.ok(html.includes(HASH));
  assert.ok(!html.includes('accept-form'));
});

test('corrupt acceptance object does not hide the form', async () => {
  const b = new FakeBucket();
  publish(b);
  b.objects.set(`acceptances/${TOKEN}.json`, { body: 'nope' });
  const html = await (await handleRequest(get(`/q/${TOKEN}`), env(b), NOW)).text();
  assert.ok(html.includes('accept-form'));
});

test('validateAcceptRequest and escapeHtml', () => {
  assert.deepEqual(validateAcceptRequest(good), { name: 'Maija Meikäläinen', signature: SIG });
  assert.equal(typeof validateAcceptRequest({ ...good, name: 'a\nb' }), 'string');
  assert.equal(escapeHtml(`<a href="x">&'`), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;');
});

test('GET only on page, POST only on accept', async () => {
  const b = new FakeBucket();
  publish(b);
  assert.equal((await handleRequest(new Request(`${BASE}/q/${TOKEN}`, { method: 'POST' }), env(b), NOW)).status, 405);
  assert.equal((await handleRequest(new Request(`${BASE}/q/${TOKEN}/accept`), env(b), NOW)).status, 405);
});
