import { createClient, SupabaseClient } from "@supabase/supabase-js";

// Single shared service-role client. The Next.js routes run server-side
// (runtime = "nodejs") so this client never reaches the browser.
//
// In production these come from Vercel env vars. Locally they come from
// .env.local. If missing, we throw at first use so route handlers fail
// loudly instead of silently downgrading to anon.

let _client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (_client) return _client;

  const url = process.env.SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!url || !serviceRoleKey) {
    throw new Error(
      "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
    );
  }

  _client = createClient(url, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    db: { schema: "public" },
  });

  return _client;
}
