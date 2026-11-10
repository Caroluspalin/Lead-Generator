/**
 * Julkaistujen demosivujen jakelu R2:sta.
 *
 * GET /<polku>  -> R2-objekti demos/<polku>.html (backend lataa sen S3-API:lla julkaistaessa)
 * Polku on luettava slug (taina-lantiainen-k7x2m) tai ennen slugeja julkaistuilla demoilla 43-merkkinen token.
 * Samat suojaheaderit kuin backendin /demo/<token>: noindex, tiukka CSP, ei välimuistia.
 *
 * GET /a/<ryhmä>/<tiedosto>?v=<tiiviste> -> R2-objekti assets/<ryhmä>/<tiiviste>/<tiedosto>
 * Version 2 demojen CSS, JS ja fontit. Avain sisältää sisällön tiivisteen, joten vastaus on
 * immutable ja vanha demo saa aina oman versionsa. Demon metadata format=2 valitsee CSP:n, joka
 * sallii nämä omat tiedostot ('self') mutta ei inline-tyylejä eikä -skriptejä.
 * Vanhentunut (customMetadata expires-at menneisyydessä) -> 410, vaikka backendin
 * poistoajo olisi myöhässä. Polku on domainista riippumaton: sama koodi toimii
 * workers.dev-osoitteessa ja omassa domainissa.
 */

// Minimaaliset R2-tyypit (ei @cloudflare/workers-types -riippuvuutta)
export interface DemoObject {
  body: ReadableStream | string | Uint8Array;
  customMetadata?: Record<string, string>;
}

export interface DemoBucket {
  get(key: string): Promise<DemoObject | null>;
}

export interface Env {
  DEMOS: DemoBucket;
}

// Vanha muoto: secrets.token_urlsafe(32) -> 43 merkkiä base64url
const TOKEN_RE = /^[A-Za-z0-9_-]{43}$/;
// Uusi muoto (backend demo_site.SLUG_RE): nimi max 40 merkkiä + '-' + 5 merkin satunnaisosa ilman 0/o/1/l/i
const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?-[abcdefghjkmnpqrstuvwxyz23456789]{5}$/;

export const isDemoPath = (path: string): boolean => TOKEN_RE.test(path) || SLUG_RE.test(path);

// Sama kuin backendin demo_site: ryhmä = pohjan tunniste tai "yhteinen", tiiviste = SHA-256:n 10 ensimmäistä heksaa
const ASSET_PATH_RE = /^a\/([a-z]{2,20})\/([a-z0-9-]+\.(css|js|woff2))$/;
const ASSET_DIGEST_RE = /^[0-9a-f]{10}$/;
const ASSET_TYPES: Record<string, string> = {
  css: 'text/css; charset=utf-8',
  js: 'text/javascript; charset=utf-8',
  woff2: 'font/woff2',
};

export function assetKey(path: string, version: string | null): string | null {
  const match = ASSET_PATH_RE.exec(path);
  if (!match || !version || !ASSET_DIGEST_RE.test(version)) return null;
  return `assets/${match[1]}/${version}/${match[2]}`;
}

export const SECURITY_HEADERS: Record<string, string> = {
  'X-Robots-Tag': 'noindex, nofollow',
  'Content-Security-Policy':
    "default-src 'none'; style-src 'unsafe-inline'; img-src data: https://images.unsplash.com https://scaled-images.timma.fi; " +
    "font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
  'Cache-Control': 'no-store',
};

// Version 2 demo: omat tiedostot samasta osoitteesta, ei inlineä
export const CSP_V2 =
  "default-src 'none'; style-src 'self'; script-src 'self'; font-src 'self'; " +
  "img-src data: https://images.unsplash.com https://scaled-images.timma.fi; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

const ASSET_HEADERS: Record<string, string> = {
  'X-Robots-Tag': 'noindex, nofollow',
  'X-Content-Type-Options': 'nosniff',
  'Cache-Control': 'public, max-age=31536000, immutable',
  // Fontit ladataan aina CORS-tilassa
  'Access-Control-Allow-Origin': '*',
};

const textResponse = (status: number, text: string): Response =>
  new Response(text, {
    status,
    headers: { ...SECURITY_HEADERS, 'Content-Type': 'text/plain; charset=utf-8' },
  });

export function isExpired(metadata: Record<string, string> | undefined, now: Date): boolean {
  const raw = metadata?.['expires-at'];
  if (!raw) return false;
  const expires = Date.parse(raw);
  return !Number.isNaN(expires) && expires <= now.getTime();
}

export async function handleRequest(request: Request, env: Env, now: Date = new Date()): Promise<Response> {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return textResponse(405, 'Method not allowed');
  }
  const url = new URL(request.url);
  const path = url.pathname;
  if (path === '/robots.txt') {
    return textResponse(200, 'User-agent: *\nDisallow: /\n');
  }

  // Vain tarkka avain: ei listausta, ei osittaisia hakuja, väärän muotoinen polku ei koske R2:een
  const demoPath = path.replace(/^\/+|\/+$/g, '');
  if (demoPath.startsWith('a/')) {
    const key = assetKey(demoPath, url.searchParams.get('v'));
    if (key === null) return textResponse(404, 'Not found');
    const asset = await env.DEMOS.get(key);
    if (asset === null) return textResponse(404, 'Not found');
    const extension = demoPath.slice(demoPath.lastIndexOf('.') + 1);
    return new Response(request.method === 'HEAD' ? null : asset.body, {
      status: 200,
      headers: { ...ASSET_HEADERS, 'Content-Type': ASSET_TYPES[extension] },
    });
  }
  if (!isDemoPath(demoPath)) {
    return textResponse(404, 'Not found');
  }

  const object = await env.DEMOS.get(`demos/${demoPath}.html`);
  if (object === null) {
    return textResponse(404, 'Not found');
  }
  if (isExpired(object.customMetadata, now)) {
    return textResponse(410, 'Tämä luonnos ei ole enää saatavilla.');
  }

  const csp = object.customMetadata?.['format'] === '2' ? CSP_V2 : SECURITY_HEADERS['Content-Security-Policy'];
  return new Response(request.method === 'HEAD' ? null : object.body, {
    status: 200,
    headers: { ...SECURITY_HEADERS, 'Content-Security-Policy': csp, 'Content-Type': 'text/html; charset=utf-8' },
  });
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },
};
