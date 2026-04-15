import { supabase } from './supabaseClient';

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000';

/**
 * Fetch-wrapper joka lisaa Supabase-sessionin JWT:n Authorization-headeriin.
 *
 * Jos Supabase-client ei ole konfiguroitu (dev-moodi), pyyntö lahetetaan
 * ilman Bearer-tokenia — backendin tulee tällöin olla AUTH_DISABLED=true.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);

  if (supabase) {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
  }

  if (init.body && typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  return fetch(`${API_BASE}${path}`, { ...init, headers });
}
