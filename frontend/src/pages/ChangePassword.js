import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, formatApiError, setAuthToken } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

export default function ChangePassword() {
  const { user, setUser } = useAuth();
  const nav = useNavigate();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const forced = !!user?.must_change_password;

  const submit = async (e) => {
    e.preventDefault();
    if (pw.length < 10) return toast.error("New password needs at least 10 characters");
    if (pw !== pw2) return toast.error("The two new passwords don't match");
    setBusy(true);
    try {
      const { data } = await api.post("/auth/change-password", { current_password: cur, new_password: pw });
      setAuthToken(data.token);
      setUser(data.user);
      toast.success("Password changed. Other devices have been signed out.");
      nav("/", { replace: true });
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
    setBusy(false);
  };

  return (
    <div className="max-w-md">
      <h1 className="text-2xl md:text-3xl font-brand text-slate-900 mb-2">Change password</h1>
      {forced ? (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm mb-4">
          You signed in with the old shared password, which is no longer safe. Please choose your own new password to continue.
        </div>
      ) : (
        <p className="text-sm text-slate-500 mb-4">Use at least 10 characters. Changing it signs you out on every other device.</p>
      )}
      <form onSubmit={submit} className="bg-white border border-slate-200 rounded-xl p-4 space-y-3">
        <label className="block text-xs text-slate-600">Current password
          <input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)}
                 data-testid="cp-current" className="mt-1 w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
        </label>
        <label className="block text-xs text-slate-600">New password
          <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)}
                 data-testid="cp-new" className="mt-1 w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
        </label>
        <label className="block text-xs text-slate-600">New password again
          <input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                 data-testid="cp-new2" className="mt-1 w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
        </label>
        <button disabled={busy} data-testid="cp-save" className="btn-brand w-full disabled:opacity-50">{busy ? "Saving…" : "Save new password"}</button>
      </form>
    </div>
  );
}
