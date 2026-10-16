import { create } from "zustand";
import axios from "axios";

import {
  getMe,
  logout as apiLogout,
  deleteCurrentUser,
  startSession,
  updateMe,
} from "@/api/client";
import { extensions } from "@/extensions";
import { clearAccountStorage } from "@/stores/account_storage";
import type { User } from "@/types/plan";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  logout: () => Promise<void>;
  deleteAccount: () => Promise<void>;
  /** Saves the account's display name. Rejects on failure so the form keeps the draft. */
  updateProfile: (displayName: string) => Promise<void>;
  ensureSession: () => Promise<void>;
  /** Re-read the session, e.g. after the account changed elsewhere. */
  refreshSession: () => Promise<User>;
}

let _sessionPromise: Promise<void> | null = null;
/** A first visit: no session cookie, so the probe answered 204 rather than 401. */
const NO_SESSION = Symbol("no session");

/** Marks the session as known, e.g. after a sign-in provider set it. */
export function sessionSettled() {
  _sessionPromise = Promise.resolve();
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  ensureSession: async () => {
    if (!_sessionPromise) {
      set({ isLoading: true, error: null });
      _sessionPromise = getMe(true)
        .then((user) => {
          if (!user) throw NO_SESSION;
          set({ user, isAuthenticated: true, isLoading: false, error: null });
        })
        .catch(async (error) => {
          _sessionPromise = null;
          if (
            error === NO_SESSION ||
            (axios.isAxiosError(error) && error.response?.status === 401)
          ) {
            if (extensions.session) {
              // Signed out: the sign-in extension shows its read-only sample,
              // which has no session and creates no rows.
              set({ user: null, isAuthenticated: false, isLoading: false, error: null });
              return;
            }
            try {
              const user = await startSession();
              _sessionPromise = Promise.resolve();
              set({ user, isAuthenticated: true, isLoading: false, error: null });
              return;
            } catch {
              /* Reported below. */
            }
          }
          set({
            isLoading: false,
            error: "Could not open your planning session. Check your connection and try again.",
          });
        });
    }
    await _sessionPromise;
  },

  refreshSession: async () => {
    const user = await getMe();
    set({ user, isAuthenticated: true, error: null });
    return user;
  },

  logout: async () => {
    await apiLogout(); // Keep the current identity if server revocation fails.
    await extensions.session?.signOut();
    _sessionPromise = null;
    clearAccountStorage();
    set({ user: null, isAuthenticated: false });
    window.location.assign(extensions.session?.afterSignOut ?? "/"); // Discard all in-memory plan data.
  },
  updateProfile: async (displayName) => {
    set({ user: await updateMe(displayName) });
  },
  deleteAccount: async () => {
    const user = get().user;
    try {
      const handled =
        user && extensions.session ? await extensions.session.deleteAccount(user) : false;
      if (!handled) await deleteCurrentUser();
    } catch (error) {
      // Deletion may have durably started before a provider/network failure.
      // Restore that state so reload/retry uses the deletion-only session.
      try {
        set({ user: await getMe() });
      } catch {
        /* Preserve existing identity for retry. */
      }
      throw error;
    }
    _sessionPromise = null;
    clearAccountStorage();
    set({ user: null, isAuthenticated: false });
    window.location.assign("/");
  },
}));
