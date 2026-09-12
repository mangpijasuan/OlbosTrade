/**
 * Auth endpoints, kept apart from api/client.ts on purpose.
 *
 * client.ts routes every call through a 401 handler that signals "your session
 * expired". These three calls must not: a 401 from /login IS the answer to the
 * question, not a session expiring, and bouncing on it would fight the login
 * form for control of the screen.
 */

export type Tier = "free" | "pro" | "elite";

export interface AuthUser {
  id: string;
  email: string;
  tier: Tier;
}

export interface AuthStatus {
  /** False on a single-operator install — there is no login to show. */
  auth_enabled: boolean;
  authenticated: boolean;
  user: AuthUser | null;
}

/**
 * Session cookies are httpOnly, so nothing here can read the token — that is
 * the point. `credentials: "same-origin"` is the default for same-origin
 * fetches, stated explicitly because the whole session mechanism rests on it.
 */
const CREDENTIALS: RequestCredentials = "same-origin";

export class LoginError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "LoginError";
  }
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const res = await fetch("/api/auth/status", { credentials: CREDENTIALS });
  if (!res.ok) throw new Error(`auth status ${res.status}`);
  return res.json();
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    credentials: CREDENTIALS,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (res.ok) return (await res.json()).user;

  // The server returns one message for every credential failure so that a
  // wrong password and a nonexistent account are indistinguishable. Echo it
  // rather than inventing something more specific, or the UI reintroduces the
  // enumeration oracle the backend went out of its way to avoid.
  let detail = "Invalid email or password";
  if (res.status === 429) {
    detail = "Too many attempts. Wait a few minutes and try again.";
  } else if (res.status === 404) {
    detail = "Authentication is not enabled on this instance.";
  } else if (res.status >= 500) {
    detail = "The server could not process the login. Try again shortly.";
  }
  throw new LoginError(detail, res.status);
}

/**
 * Three outcomes, not two — and the third is the one that matters.
 *
 *   "revoked"      the server cleared the cookie and killed the session row.
 *   "not-revoked"  the server answered 503: it cleared the cookie, but the
 *                  session row is still live and will work again when the
 *                  database recovers. Bounded by AUTH_SESSION_HOURS.
 *   "unreachable"  the request never arrived. NOTHING happened: the row is
 *                  live and the cookie is still in the browser.
 *
 * The last case cannot be papered over on the client. The session cookie is
 * httpOnly — deliberately, so XSS cannot lift it — which means script cannot
 * delete it either. If the request does not land, this app genuinely cannot
 * sign anyone out, and saying otherwise is a lie with consequences: on a
 * borrowed or shared machine someone walks away believing they are signed out
 * while a valid session cookie sits in the browser, and the next page load
 * puts them straight back into a trading terminal.
 */
export type LogoutOutcome = "revoked" | "not-revoked" | "unreachable";

export interface LogoutResult {
  outcome: LogoutOutcome;
  /** Whether the browser's session cookie is actually gone. */
  cookieCleared: boolean;
}

/** Unreachable is the safe answer: it keeps the caller signed in. */
const UNREACHABLE: LogoutResult = { outcome: "unreachable", cookieCleared: false };

export async function logout(): Promise<LogoutResult> {
  let res: Response;
  try {
    res = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: CREDENTIALS,
    });
  } catch {
    return UNREACHABLE;                  // never left the browser
  }

  // Deliberately NOT `res.ok ? … : …`, and deliberately not a check on 503.
  //
  // The cookie is only gone if the logout ROUTE ran, because delete_cookie
  // lives there. A status code does not prove that: nginx answers 502/504 when
  // the backend is down, and an unhandled error can produce a 500 raised before
  // the route reaches its cookie clearing. Trusting the status would report
  // cookieCleared on a response that never touched the cookie, sign the user
  // out in the UI, and leave a live httpOnly session in the browser — which is
  // precisely the bug this module was just changed to stop telling.
  //
  // So the route identifies itself: only its own JSON envelope, {ok: boolean},
  // counts as proof it ran. A proxy error page cannot forge that. Anything
  // unrecognised falls through to unreachable, which keeps the caller signed
  // in — the fail-safe direction, since a spurious "still signed in" costs a
  // retry and a spurious "signed out" costs a live session on a shared machine.
  try {
    const body = await res.json();
    if (body && typeof body.ok === "boolean") {
      return { outcome: body.ok ? "revoked" : "not-revoked", cookieCleared: true };
    }
  } catch {
    /* not JSON — a proxy error page, an empty body, a truncated response */
  }
  return UNREACHABLE;
}
