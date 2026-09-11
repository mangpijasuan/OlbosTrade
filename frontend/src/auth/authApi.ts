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

export interface LogoutResult {
  /** False when the server could not revoke the session (it returns 503). */
  revoked: boolean;
}

export async function logout(): Promise<LogoutResult> {
  try {
    const res = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: CREDENTIALS,
    });
    // 503 means the cookie was cleared but the session row is still live. The
    // person is logged out here either way; what they must not get is a silent
    // success when the server could not revoke.
    return { revoked: res.ok };
  } catch {
    return { revoked: false };
  }
}
