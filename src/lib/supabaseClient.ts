import { createClient, SupabaseClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

/**
 * Supabase-client. `null` jos env-muuttujat puuttuvat → sovellus toimii
 * dev-moodissa (edellyttaa AUTH_DISABLED=true backendissa).
 */
export const supabase: SupabaseClient | null =
  supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  }) : null;

export const isAuthConfigured = supabase !== null;

if (!isAuthConfigured) {
  console.warn(
    '[Auth] VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY puuttuu — ' +
    'sovellus toimii dev-moodissa. Aseta AUTH_DISABLED=true backendin .env:iin.',
  );
}
