/**
 * Who is signed in, and whether this instance asks at all.
 *
 * Boot does one call to /api/auth/status, which answers both questions. The
 * four states below are kept distinct because collapsing any two of them
 * produces a specific wrong screen:
 *
 *   checking  — don't know yet; showing either the app or a login form here
 *               would be a guess that flashes and then corrects itself
 *   disabled  — auth is off (the default); there is no login to show and no
 *               identity to display
 *   anonymous — auth is on, nobody is signed in
 *   signed-in — auth is on, we know who
 *   error     — the server could not be reached; say so rather than picking
 *               one of the above and hoping
 */

import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";

import {
  AuthUser, fetchAuthStatus, login as apiLogin, logout as apiLogout,
} from "./authApi";
import { installSessionExpiryInterceptor, onSessionExpired } from "./sessionExpiry";

export type AuthPhase = "checking" | "disabled" | "anonymous" | "signed-in" | "error";

export interface AuthContextValue {
  phase: AuthPhase;
  user: AuthUser | null;
  /** Set when a session ended under us, so the login screen can say why. */
  expiredNotice: string | null;
  /** Set when logout could not revoke server-side — worth telling the user. */
  logoutWarning: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  /**
   * Resolves true when the session actually ended. False means the server
   * could not be reached and the caller is STILL SIGNED IN — callers must not
   * dismiss their UI on a false, or the warning explaining why goes with it.
   */
  signOut: () => Promise<boolean>;
  retry: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * For components that cannot work without auth — the login form, the gate.
 * Throwing here is correct: rendering them outside a provider is a wiring bug.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/**
 * For optional identity chrome, which must degrade rather than explode.
 *
 * The status-bar user chip lives deep inside TerminalLayout, and a layout that
 * cannot be rendered without an auth provider is a layout that cannot be
 * tested or reused. A missing provider means "no identity to show" — which is
 * exactly what an auth-disabled install looks like anyway — not a crash that
 * takes the whole shell down with it.
 */
export function useAuthOptional(): AuthContextValue | null {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<AuthPhase>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [expiredNotice, setExpiredNotice] = useState<string | null>(null);
  const [logoutWarning, setLogoutWarning] = useState<string | null>(null);

  // Guards against a slow status call resolving after unmount, and against the
  // expiry interceptor firing once per in-flight request during a page's worth
  // of parallel polls.
  const alive = useRef(true);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const check = useCallback(async () => {
    setPhase("checking");
    try {
      const status = await fetchAuthStatus();
      if (!alive.current) return;
      if (!status.auth_enabled) {
        setUser(null);
        setPhase("disabled");
      } else if (status.authenticated && status.user) {
        setUser(status.user);
        setPhase("signed-in");
      } else {
        setUser(null);
        setPhase("anonymous");
      }
    } catch {
      if (!alive.current) return;
      // Unreachable server. Not "logged out" and not "auth is off" — both
      // would be guesses, and one of them silently drops the identity display
      // on an instance that does have auth on.
      setUser(null);
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const uninstall = installSessionExpiryInterceptor();

    const off = onSessionExpired(() => {
      // Only meaningful while we believe we are signed in. During "anonymous"
      // every API call 401s by design, and reacting to those would spam the
      // notice over the login form the user is already looking at.
      if (phaseRef.current !== "signed-in") return;
      setUser(null);
      setPhase("anonymous");
      setExpiredNotice("Your session ended. Please sign in again.");
    });

    check();
    return () => {
      alive.current = false;
      off();
      uninstall();
    };
  }, [check]);

  const signIn = useCallback(async (email: string, password: string) => {
    const signedIn = await apiLogin(email, password);   // throws LoginError
    setUser(signedIn);
    setExpiredNotice(null);
    setLogoutWarning(null);
    setPhase("signed-in");
  }, []);

  const signOut = useCallback(async (): Promise<boolean> => {
    const { outcome, cookieCleared } = await apiLogout();

    if (!cookieCleared) {
      // The request never landed, so nothing happened: the session row is live
      // and the cookie is still in the browser. The cookie is httpOnly, so
      // script cannot remove it — this app cannot sign anyone out without the
      // server, and pretending otherwise is the dangerous option. Someone on a
      // borrowed machine would walk away believing they were signed out while
      // a valid session sat in the browser, and the next load would drop them
      // back into the terminal.
      //
      // So: stay signed in, say plainly that it failed, and let them retry.
      // NOT "close the browser". Raised in review, and it was worse than the
      // bug this whole change fixes: the session cookie is set with
      // max_age = AUTH_SESSION_HOURS * 3600, so it is PERSISTENT. Closing and
      // reopening the browser keeps it, and the next person to open the app on
      // that machine walks into the terminal. Telling someone that closing the
      // browser makes them safe is false confidence with a specific action
      // attached, which is worse than no advice at all.
      //
      // Retrying is the only thing that actually ends the session from here.
      setLogoutWarning(
        "Could not reach the server, so you are still signed in. Try again — " +
        "closing the browser will NOT sign you out, and the session stays " +
        "active until it expires."
      );
      return false;
    }

    setUser(null);
    setExpiredNotice(null);
    // The cookie is gone. If the server could not revoke the row, a copied
    // token starts working again once the database recovers, which the
    // operator should hear about rather than assume away.
    // "Sign out again when it recovers" was not actionable, also raised in
    // review: by this point the phase is anonymous, the login screen has no
    // sign-out control, and signing in later and out again would revoke a NEW
    // session rather than the un-revoked one. It read like a remedy and was a
    // no-op.
    //
    // What is true: this browser is clean, the risk is only a token copied
    // before, and it stays valid until expires_at. The one real early-out is
    // server-side — deactivating the account, which require_session rechecks
    // on every request, so it takes effect immediately.
    setLogoutWarning(
      outcome === "revoked"
        ? null
        : "Signed out on this device, but the server could not revoke the " +
          "session. A copied token would stay valid until it expires; an " +
          "operator can deactivate the account to end it sooner."
    );
    setPhase("anonymous");
    return true;
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    phase, user, expiredNotice, logoutWarning, signIn, signOut, retry: check,
  }), [phase, user, expiredNotice, logoutWarning, signIn, signOut, check]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
