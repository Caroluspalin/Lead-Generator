/**
 * Julkaistujen demosivujen jakelu R2:sta.
 *
 * GET /<token>  -> R2-objekti demos/<token>.html (backend lataa sen S3-API:lla julkaistaessa)
 * Samat suojaheaderit kuin backendin /demo/<token>: noindex, tiukka CSP, ei välimuistia.
 * Vanhentunut (customMetadata expires-at menneisyydessä) -> 410, vaikka backendin
 * poistoajo olisi myöhässä. Polku on domainista riippumaton: sama koodi toimii
 * workers.dev-osoitteessa ja omassa domainissa.
 */

// Minimaaliset R2-tyypit (ei @cloudflare/workers-types -riippuvuutta)
export interface DemoObject {
  body: ReadableStream | string;
  customMetadata?: Record<string, string>;
}

export interface DemoBucket {
  get(key: string): Promise<DemoObject | null>;
}

export interface Env {
  DEMOS: DemoBucket;
}

// secrets.token_urlsafe(32) -> 43 merkkiä base64url
const TOKEN_RE = /^[A-Za-z0-9_-]{43}$/;

export const SECURITY_HEADERS: Record<string, string> = {
  'X-Robots-Tag': 'noindex, nofollow',
  'Content-Security-Policy':
    "default-src 'none'; style-src 'unsafe-inline'; img-src data: https://images.unsplash.com; " +
    "font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
  'Cache-Control': 'no-store',
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
  const path = new URL(request.url).pathname;
  if (path === '/robots.txt') {
    return textResponse(200, 'User-agent: *\nDisallow: /\n');
  }

  const token = path.replace(/^\/+|\/+$/g, '');
  if (!TOKEN_RE.test(token)) {
    return textResponse(404, 'Not found');
  }

  const object = await env.DEMOS.get(`demos/${token}.html`);
  if (object === null) {
    return textResponse(404, 'Not found');
  }
  if (isExpired(object.customMetadata, now)) {
    return textResponse(410, 'Tämä luonnos ei ole enää saatavilla.');
  }

  return new Response(request.method === 'HEAD' ? null : object.body, {
    status: 200,
    headers: { ...SECURITY_HEADERS, 'Content-Type': 'text/html; charset=utf-8' },
  });
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },
};
