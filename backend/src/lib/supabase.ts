import { createClient, SupabaseClient } from "@supabase/supabase-js";

const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SERVICE_KEY;

export const DEV_FIXTURE = process.env.ELEVATE_DEV_FIXTURE === "1";

// In fixture mode we never touch Supabase — routes short-circuit before using this.
// The client is still exported (as null) so imports don't break.
export const supabase: SupabaseClient = DEV_FIXTURE
  ? (null as unknown as SupabaseClient)
  : (() => {
      if (!url || !key) {
        throw new Error(
          "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set (or use ELEVATE_DEV_FIXTURE=1)",
        );
      }
      return createClient(url, key, {
        auth: { persistSession: false, autoRefreshToken: false },
      });
    })();
