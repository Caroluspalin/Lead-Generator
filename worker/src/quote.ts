/**
 * Tarjoussivut: GET /q/<token> (R2 quotes/<token>.html), POST /q/<token>/accept ja selaimen skripti /q/quote.js.
 *
 * Hyväksyntä kirjoitetaan R2:een (acceptances/<token>.json), josta paikallinen backend hakee sen. Kirjoitus on
 * kerran-vain (onlyIf etagDoesNotMatch '*'): jo tehtyä hyväksyntää ei voi ylikirjoittaa. Aika on Workerin kello,
 * tarjouksen tiiviste luetaan R2-objektin metadatasta (ei asiakkaan lähettämänä). Ei IP:tä eikä User-Agentia.
 * Hyväksytty sivu näytetään hyväksyntätiedoilla riippumatta vanhenemisesta.
 */
import type { DemoBucket, DemoObject } from './index.ts';

export const QUOTE_PATH_RE = /^q\/([A-Za-z0-9_-]{43})(\/accept)?$/;
export const ACCEPT_START = '<!--ACCEPT-START-->';
export const ACCEPT_END = '<!--ACCEPT-END-->';
const SIGNATURE_RE = /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/;
const MIN_SIGNATURE_CHARS = 200;
const MAX_SIGNATURE_CHARS = 250_000;
const MAX_BODY_CHARS = 300_000;

export const QUOTE_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src data:; connect-src 'self'; " +
  "base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

export const quoteKey = (token: string): string => `quotes/${token}.html`;
export const acceptanceKey = (token: string): string => `acceptances/${token}.json`;

export interface Acceptance {
  name: string;
  accepted_at: string;
  content_hash: string;
  authority: true;
  signature: string;
}

export const escapeHtml = (value: string): string =>
  value.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c);

export async function readText(object: DemoObject): Promise<string> {
  const body = object.body;
  if (typeof body === 'string') return body;
  if (body instanceof Uint8Array) return new TextDecoder().decode(body);
  return new Response(body).text();
}

export function parseAcceptance(raw: string): Acceptance | null {
  try {
    const data: unknown = JSON.parse(raw);
    if (typeof data !== 'object' || data === null) return null;
    const rec = data as Record<string, unknown>;
    if (
      typeof rec.name !== 'string' || typeof rec.accepted_at !== 'string' || typeof rec.content_hash !== 'string' ||
      typeof rec.signature !== 'string' || rec.authority !== true
    ) {
      return null;
    }
    return { name: rec.name, accepted_at: rec.accepted_at, content_hash: rec.content_hash, authority: true, signature: rec.signature };
  } catch {
    return null;
  }
}

export function formatHelsinki(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('fi-FI', { timeZone: 'Europe/Helsinki', dateStyle: 'long', timeStyle: 'short' }).format(date);
}

export function acceptedBlock(acceptance: Acceptance): string {
  const image = SIGNATURE_RE.test(acceptance.signature)
    ? `<img class="sig" alt="Allekirjoitus" src="${acceptance.signature}">`
    : '';
  return (
    '<div class="card ok"><h2>Tarjous hyväksytty</h2>' +
    `<p>Hyväksyjä: <strong>${escapeHtml(acceptance.name)}</strong><br>Aika: ${escapeHtml(formatHelsinki(acceptance.accepted_at))}</p>` +
    `${image}<div class="hash">Hyväksytyn tarjouksen tiiviste (SHA-256): ${escapeHtml(acceptance.content_hash)}</div></div>`
  );
}

export function withAcceptance(html: string, acceptance: Acceptance): string {
  const start = html.indexOf(ACCEPT_START);
  const end = html.indexOf(ACCEPT_END);
  if (start === -1 || end === -1 || end < start) return html;
  return html.slice(0, start) + acceptedBlock(acceptance) + html.slice(end + ACCEPT_END.length);
}

interface AcceptRequest {
  name: string;
  signature: string;
}

export function validateAcceptRequest(data: unknown): AcceptRequest | string {
  if (typeof data !== 'object' || data === null) return 'Virheellinen pyyntö.';
  const rec = data as Record<string, unknown>;
  const name = typeof rec.name === 'string' ? rec.name.trim() : '';
  // eslint-disable-next-line no-control-regex
  if (name.length < 1 || name.length > 100 || /[\u0000-\u001f\u007f]/.test(name)) return 'Kirjoita nimesi.';
  if (rec.authority !== true) return 'Vahvista, että sinulla on oikeus hyväksyä tarjous yrityksen puolesta.';
  if (rec.accept !== true) return 'Vahvista, että hyväksyt tarjouksen.';
  const signature = typeof rec.signature === 'string' ? rec.signature : '';
  if (!SIGNATURE_RE.test(signature) || signature.length < MIN_SIGNATURE_CHARS || signature.length > MAX_SIGNATURE_CHARS) {
    return 'Piirrä allekirjoitus.';
  }
  return { name, signature };
}

const jsonResponse = (status: number, body: Record<string, unknown>, headers: Record<string, string>): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, 'Content-Type': 'application/json; charset=utf-8' },
  });

export async function handleAccept(
  request: Request,
  bucket: DemoBucket,
  token: string,
  now: Date,
  headers: Record<string, string>,
): Promise<Response> {
  // Selain lähettää aina Originin POSTissa: vieraan sivun lomake ei kelpaa
  const origin = request.headers.get('origin');
  if (origin !== null && origin !== new URL(request.url).origin) return jsonResponse(403, { error: 'Kielletty.' }, headers);
  if (!(request.headers.get('content-type') ?? '').includes('application/json')) {
    return jsonResponse(415, { error: 'Virheellinen pyyntö.' }, headers);
  }
  const text = await request.text();
  if (text.length > MAX_BODY_CHARS) return jsonResponse(413, { error: 'Liian suuri pyyntö.' }, headers);
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return jsonResponse(400, { error: 'Virheellinen pyyntö.' }, headers);
  }
  const valid = validateAcceptRequest(parsed);
  if (typeof valid === 'string') return jsonResponse(422, { error: valid }, headers);

  const quote = await bucket.get(quoteKey(token));
  if (quote === null) return jsonResponse(404, { error: 'Tarjousta ei löydy.' }, headers);
  if (await bucket.get(acceptanceKey(token)) !== null) {
    return jsonResponse(409, { error: 'Tarjous on jo hyväksytty.' }, headers);
  }
  const meta = quote.customMetadata ?? {};
  if (meta['state'] === 'superseded') {
    return jsonResponse(409, { error: 'Tämä tarjous on korvattu uudemmalla versiolla.' }, headers);
  }
  const expires = Date.parse(meta['expires-at'] ?? '');
  if (!Number.isNaN(expires) && expires <= now.getTime()) {
    return jsonResponse(410, { error: 'Tarjous ei ole enää voimassa.' }, headers);
  }
  const hash = meta['content-hash'];
  if (!hash) return jsonResponse(409, { error: 'Tarjousta ei voi hyväksyä.' }, headers);

  const record: Acceptance = {
    name: valid.name,
    accepted_at: now.toISOString(),
    content_hash: hash,
    authority: true,
    signature: valid.signature,
  };
  // null = avain on jo olemassa (rinnakkainen hyväksyntä): ensimmäinen voittaa
  const written = await bucket.put(acceptanceKey(token), JSON.stringify(record), {
    onlyIf: { etagDoesNotMatch: '*' },
    httpMetadata: { contentType: 'application/json' },
  });
  if (written === null) return jsonResponse(409, { error: 'Tarjous on jo hyväksytty.' }, headers);
  return jsonResponse(200, { ok: true, accepted_at: record.accepted_at }, headers);
}

// Selaimen skripti: allekirjoituskanvas ja lomakkeen lähetys. Omana tiedostonaan, jotta CSP ei tarvitse inline-skriptiä.
export const QUOTE_JS = `(function () {
  var printBtn = document.getElementById('print-btn');
  if (printBtn) printBtn.addEventListener('click', function () { window.print(); });
  var form = document.getElementById('accept-form');
  if (!form) return;
  var canvas = document.getElementById('sig-canvas');
  var ctx = canvas.getContext('2d');
  ctx.lineWidth = 4;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = '#111111';
  var drawing = false;
  var drawn = false;
  function point(e) {
    var r = canvas.getBoundingClientRect();
    return { x: (e.clientX - r.left) * canvas.width / r.width, y: (e.clientY - r.top) * canvas.height / r.height };
  }
  canvas.addEventListener('pointerdown', function (e) {
    drawing = true;
    drawn = true;
    canvas.setPointerCapture(e.pointerId);
    var p = point(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x + 0.1, p.y);
    ctx.stroke();
    e.preventDefault();
  });
  canvas.addEventListener('pointermove', function (e) {
    if (!drawing) return;
    var p = point(e);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    e.preventDefault();
  });
  function stop() { drawing = false; }
  canvas.addEventListener('pointerup', stop);
  canvas.addEventListener('pointercancel', stop);
  document.getElementById('sig-clear').addEventListener('click', function () {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawn = false;
  });
  var msg = document.getElementById('accept-msg');
  var btn = document.getElementById('accept-btn');
  btn.addEventListener('click', function () {
    var name = document.getElementById('signer-name').value.trim();
    var authority = document.getElementById('chk-authority').checked;
    var accept = document.getElementById('chk-accept').checked;
    msg.textContent = '';
    if (!name) { msg.textContent = 'Kirjoita nimesi.'; return; }
    if (!drawn) { msg.textContent = 'Piirrä allekirjoitus.'; return; }
    if (!authority || !accept) { msg.textContent = 'Rastita molemmat vahvistukset.'; return; }
    btn.disabled = true;
    fetch(location.pathname.replace(/\\/$/, '') + '/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, authority: authority, accept: accept, signature: canvas.toDataURL('image/png') })
    }).then(function (res) {
      return res.json().then(function (data) { return { ok: res.ok, data: data }; });
    }).then(function (r) {
      if (r.ok || (r.data && r.data.error === 'Tarjous on jo hyväksytty.')) { location.reload(); return; }
      msg.textContent = (r.data && r.data.error) || 'Hyväksyminen epäonnistui.';
      btn.disabled = false;
    }).catch(function () {
      msg.textContent = 'Yhteysvirhe. Yritä uudelleen.';
      btn.disabled = false;
    });
  });
})();
`;
