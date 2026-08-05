/**
 * The browser's half of the session (M2-1).
 *
 * The Access Token is kept in `localStorage`, not in memory and not in a
 * cookie. In memory it would not survive an F5, and an operator eight hours
 * into a shift should not have to re-type a password because they refreshed a
 * dashboard. A cookie would drag in CSRF handling for no gain — this machine is
 * a single-purpose LAN box serving only its own first-party SPA.
 *
 * Subscribers exist so that a 401 raised anywhere in the app — most of all from
 * a token that expired while a tab sat open — drops the whole UI back to Login
 * without any page needing to know about any other page.
 */

/** The storage key. Namespaced so it cannot collide with anything else on the origin. */
const SESSION_KEY = "arichds.session";

/**
 * Who is signed in, as far as the browser knows.
 *
 * `id` is here from M2-2 because every User Management endpoint takes an id,
 * and the page has to know which row is *yours* to disable its own controls.
 * Keying that off the username instead would work only until someone is
 * renamed.
 */
export interface Session {
  id: number;
  token: string;
  username: string;
  role: "admin" | "user";
}

type Listener = (session: Session | null) => void;

const listeners = new Set<Listener>();

/** Return the stored session, or null when there is none (or it is unreadable). */
export function getSession(): Session | null {
  const raw = window.localStorage.getItem(SESSION_KEY);
  if (!raw) return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as Session).token === "string" &&
      typeof (parsed as Session).username === "string" &&
      // A session stored before M2-2 has no `id`, so it is discarded here and
      // the operator signs in once more. Acceptable on an unreleased product,
      // and far cheaper than making `id` optional everywhere downstream.
      typeof (parsed as Session).id === "number"
    ) {
      return parsed as Session;
    }
  } catch {
    // Corrupt or hand-edited storage — treat it as no session at all rather
    // than letting a parse error take the whole app down at boot.
  }

  window.localStorage.removeItem(SESSION_KEY);
  return null;
}

/** Store *session* and notify every subscriber. */
export function setSession(session: Session): void {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  notify(session);
}

/** Forget the session and notify every subscriber. */
export function clearSession(): void {
  window.localStorage.removeItem(SESSION_KEY);
  notify(null);
}

/**
 * Subscribe to session changes.
 *
 * @returns an unsubscribe function, for an effect's cleanup.
 */
export function onSessionChange(callback: Listener): () => void {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

function notify(session: Session | null): void {
  for (const listener of listeners) listener(session);
}
