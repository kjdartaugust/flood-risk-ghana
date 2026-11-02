"use client";

import useSWR from "swr";
import { api } from "./api";
import { ago } from "./rain";

/**
 * "Rain checked 40 min ago", from the scheduled refresh's own record, so the
 * page says how fresh its forecast is instead of implying it's live. Honest
 * when the last check failed, too.
 */
export function useRainCheck(): string | null {
  const { data } = useSWR("rain-check", () => api.lastRainCheck(), {
    refreshInterval: 5 * 60_000,
  });
  if (!data?.finished_at) return null;
  return data.error || !data.rainfall_rows
    ? `Last rain check failed ${ago(data.finished_at)}`
    : `Rain checked ${ago(data.finished_at)}`;
}
