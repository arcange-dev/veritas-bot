/**
 * The only place `import.meta.env` is read. No secret ever enters a VITE_
 * variable: everything here is a public URL.
 */
const read = (value: unknown, fallback: string): string =>
  typeof value === "string" && value.length > 0 ? value : fallback;

export const env = {
  apiBaseUrl: read(import.meta.env.VITE_API_BASE_URL, "http://localhost:8000"),
  wsBaseUrl: read(import.meta.env.VITE_WS_BASE_URL, "ws://localhost:8000"),
  supabaseUrl: read(import.meta.env.VITE_SUPABASE_URL, ""),
  supabaseAnonKey: read(import.meta.env.VITE_SUPABASE_ANON_KEY, ""),
} as const;

export const isConfigured = env.supabaseUrl.length > 0 && env.supabaseAnonKey.length > 0;
