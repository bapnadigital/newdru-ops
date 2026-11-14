import { createContext, useContext, useEffect, useState } from "react";
import { api, formatApiError, setAuthToken } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try { const { data } = await api.get("/auth/me"); setUser(data); }
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

  const hasRole = (...roles) => !!user && roles.includes(user.role);

  return (
    <AuthCtx.Provider value={{ user, login, logout, setUser, error, hasRole }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
