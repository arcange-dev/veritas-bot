/**
 * Supabase session handling. The token lives in Supabase's own storage; we only
 * read it. No API key or token is ever placed in our own localStorage.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { env, isConfigured } from "./env";

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (!isConfigured) {
    throw new Error(
      "Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.",
    );
  }
  client ??= createClient(env.supabaseUrl, env.supabaseAnonKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  return client;
}

export async function getAccessToken(): Promise<string | null> {
  if (!isConfigured) return null;
  const { data } = await supabase().auth.getSession();
  return data.session?.access_token ?? null;
}

export async function signInWithOtp(email: string): Promise<void> {
  const { error } = await supabase().auth.signInWithOtp({
    email,
    options: { emailRedirectTo: window.location.origin },
  });
  if (error) throw new Error(error.message);
}

export async function signOut(): Promise<void> {
  await supabase().auth.signOut();
}

/** Subscribe to sign-in/out/refresh. Returns an unsubscribe function. */
export function onAuthChange(listener: (signedIn: boolean) => void): () => void {
  if (!isConfigured) return () => undefined;
  const { data } = supabase().auth.onAuthStateChange((_event, session) => listener(Boolean(session)));
  return () => data.subscription.unsubscribe();
}
