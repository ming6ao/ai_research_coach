import { create } from 'zustand';
import { apiClient, getAuthToken, setAuthToken, type AuthUser } from '../api/client';

interface AuthState {
  user: AuthUser | null;
  authLoading: boolean;
  authError: string | null;
  googleLogin: () => Promise<void>;
  logout: () => Promise<void>;
  restore: () => Promise<void>;
  clearAuthError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  authLoading: false,
  authError: null,

  restore: async () => {
    if (!getAuthToken()) {
      set({ user: null, authLoading: false });
      return;
    }
    set({ authLoading: true });
    try {
      const res = await apiClient.me();
      set({ user: res.user, authError: null });
    } catch {
      setAuthToken(null);
      set({ user: null, authError: null });
    } finally {
      set({ authLoading: false });
    }
  },

  googleLogin: async () => {
    set({ authLoading: true, authError: null });
    try {
      const res = await apiClient.googleAuthUrl();
      window.location.href = res.url;
    } catch (e) {
      set({ authLoading: false, authError: e instanceof Error ? e.message : String(e) });
    }
  },

  logout: async () => {
    try {
      await apiClient.logout();
    } catch {
      // Token may already be invalid — clear locally regardless.
    }
    setAuthToken(null);
    set({ user: null, authError: null });
  },

  clearAuthError: () => set({ authError: null }),
}));