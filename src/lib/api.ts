import { supabase } from './supabaseClient';

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000';

/**
 * Fetch-wrapper joka lisaa Supabase-sessionin JWT:n Authorization-headeriin.
 *
 * Käytä tätä kaikkiin backend-kutsuihin — muuten pyyntö epäonnistuu 401:lla.
 * Polku annetaan suhteellisena (esim. "/leads"), API_BASE liitetaan automaattisesti.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;

  const headers = new Headers(init.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  // Aseta JSON-Content-Type jos body on string ja headeria ei ole ennestaan
  if (init.body && typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  return fetch(`${API_BASE}${path}`, { ...init, headers });
}
