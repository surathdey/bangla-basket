/**
 * Anonymous launch analytics — fire-and-forget, never PII.
 *
 * Session id: a random hex string. On web it is stored in localStorage
 * (key bb_analytics_session) so one browser = one session across visits.
 * On native there is no persistence here — a fresh random value per app
 * mount (sessions just split; nothing personal is ever used as a session).
 *
 * Deliberately does NOT use the shared api client: that client attaches the
 * user's/guest's Authorization bearer token, and analytics events must stay
 * fully anonymous. This posts with only a Content-Type header, no auth.
 *
 * track() never throws, never awaits, and never blocks UI — if the backend
 * is unreachable the event is silently dropped.
 */
import { Platform } from "react-native";
import { getBackendUrl } from "@/src/utils/backendUrl";

export type AnalyticsType = "page_view" | "cart_view" | "cart_add" | "checkout_start" | "search";

const SESSION_KEY = "bb_analytics_session";

function randomHex(bytes = 16): string {
  const arr = new Uint8Array(bytes);
  try {
    if (typeof crypto !== "undefined" && crypto.getRandomValues) {
      crypto.getRandomValues(arr);
    } else {
      for (let i = 0; i < bytes; i++) arr[i] = Math.floor(Math.random() * 256);
    }
  } catch {
    for (let i = 0; i < bytes; i++) arr[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
}

let nativeSession: string | null = null;

export function getAnalyticsSession(): string {
  if (Platform.OS === "web") {
    try {
      if (typeof window !== "undefined" && window.localStorage) {
        const existing = window.localStorage.getItem(SESSION_KEY);
        if (existing) return existing;
        const fresh = randomHex();
        window.localStorage.setItem(SESSION_KEY, fresh);
        return fresh;
      }
    } catch {
      // Storage unavailable (e.g. private mode) — fall through to a
      // per-mount random value; the event is still anonymous.
    }
  }
  if (!nativeSession) nativeSession = randomHex();
  return nativeSession;
}

export function track(
  type: AnalyticsType,
  fields: { path?: string; item_id?: string; item_name?: string; qty?: number } = {},
): void {
  try {
    const base = getBackendUrl();
    if (!base) return;
    const body: Record<string, unknown> = { type, session: getAnalyticsSession() };
    if (fields.path !== undefined) body.path = fields.path;
    if (fields.item_id !== undefined) body.item_id = fields.item_id;
    if (fields.item_name !== undefined) body.item_name = fields.item_name;
    if (fields.qty !== undefined) body.qty = fields.qty;
    fetch(`${base}/api/analytics/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => {
      // Analytics must never break the app.
    });
  } catch {
    // Never throw.
  }
}
