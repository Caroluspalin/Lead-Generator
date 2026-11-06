import { test } from 'node:test';
import assert from 'node:assert/strict';
import { handleRequest, isExpired, SECURITY_HEADERS } from '../src/index.ts';
import type { DemoBucket, DemoObject } from '../src/index.ts';

const TOKEN = 'A'.repeat(20) + '_-' + 'b'.repeat(21); // 43 merkkiä
const NOW = new Date('2026-11-06T12:00:00Z');

class FakeBucket implements DemoBucket {
  objects = new Map<string, DemoObject>();
  keys: string[] = [];

  async get(key: string): Promise<DemoObject | null> {
    this.keys.push(key);
    return this.objects.get(key) ?? null;
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
  assert.match(res.headers.get('content-security-policy') ?? '', /img-src data: https:\/\/images\.unsplash\.com/);
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
