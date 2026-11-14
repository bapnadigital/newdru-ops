import { createContext, useContext, useEffect, useState } from "react";
import { api, formatApiError, setAuthToken } from "@/lib/api";
import { toast } from "sonner";

// Shared shop computers: sign out after this long with no mouse/keyboard/touch.
const IDLE_MIN = 30;
const LAST_KEY = "newdru_last_active";
const readLast = () => { try { return Number(localStorage.getItem(LAST_KEY)) || 0; } catch { return 0; } };
const writeLast = () => { try { localStorage.setItem(LAST_KEY, String(Date.now())); } catch { /* private mode */ } };

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/auth/me");
        const last = readLast();
        if (last && Date.now() - last > IDLE_MIN * 60000) {
          // Browser left signed in and walked away from: don't reopen the session.
          try { await api.post("/auth/logout"); } catch { /* ignore */ }
          setUser(null);
          return;
        }
        writeLast();
        setUser(data);
      }
      catch (err) {
        // 401 on initial load is expected when not signed in; swallow only that.
        if (err?.response?.status !== 401) console.error("auth/me failed:", err);
        setUser(null);
      }
    })();
  }, []);

  const login = async (email, password) => {
    setError(null);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      setAuthToken(data.token);
      writeLast();
      setUser(data.user);
      return { ok: true, user: data.user };
    } catch (e) {
      const msg = formatApiError(e.response?.data?.detail) || e.message || "Login failed";
      setError(msg);
      return { ok: false, error: msg };
    }
  };

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch (err) { console.warn("logout call failed:", err); }
    setAuthToken(null);
    setUser(null);
  };

  useEffect(() => {
    if (!user) return undefined;
    let lastWrite = 0;
    const bump = () => { const n = Date.now(); if (n - lastWrite > 15000) { lastWrite = n; writeLast(); } };
    const events = ["mousemove", "mousedown", "keydown", "touchstart", "scroll"];
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }));
    writeLast();
    const timer = setInterval(() => {
      if (Date.now() - readLast() > IDLE_MIN * 60000) {
        toast.message(`Signed out after ${IDLE_MIN} minutes with no activity`);
        logout();
      }
    }, 30000);
    return () => { events.forEach((e) => window.removeEventListener(e, bump)); clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const hasRole = (...roles) => !!user && roles.includes(user.role);

  return (
    <AuthCtx.Provider value={{ user, login, logout, setUser, error, hasRole }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
