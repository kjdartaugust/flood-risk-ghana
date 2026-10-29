"use client";

import { createClient, SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// Auth is optional. The risk map, the tiles and the route list are all public
// endpoints — only *subscribing* to alerts needs a user. So when Supabase isn't
// configured we hand back null and the UI hides the sign-in affordance, rather
// than the whole app failing to boot over a feature most visitors never touch.
export const supabase: SupabaseClient | null =
  url && anon ? createClient(url, anon) : null;

export const authConfigured = supabase !== null;
