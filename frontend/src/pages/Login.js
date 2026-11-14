import { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import NewdruLogo from "@/components/NewdruLogo";
import { Loader2 } from "lucide-react";

export default function Login() {
  const { user, login, error } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    const res = await login(email, password);
    setLoading(false);
    if (res.ok) nav("/");
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2" style={{ background: "#F7F8FA" }}>
      <div className="hidden lg:flex flex-col justify-between p-12" style={{ background: "linear-gradient(135deg,#FDECEA 0%,#FFF3F1 60%,#FFFFFF 100%)" }}>
        <NewdruLogo size="xl" tagline />
        <div className="max-w-md">
          <h1 className="text-4xl font-brand text-slate-900 leading-tight">
            Retail + wholesale, <span style={{ color: "#F0544A" }}>run from one clean dashboard.</span>
          </h1>
          <p className="text-slate-600 mt-4 text-sm leading-relaxed">
            POS, inventory across Store, Bhiwandi, Amazon FC & Flipkart FC, GST-compliant invoicing, barcode
            scanning, transfers, and a mini-CRM — all in one place.
          </p>
          <div className="mt-8 flex gap-6 text-sm">
            <div><div className="text-2xl font-brand" style={{ color: "#F0544A" }}>4</div><div className="text-slate-500">locations</div></div>
            <div><div className="text-2xl font-brand" style={{ color: "#F0544A" }}>18%</div><div className="text-slate-500">default GST</div></div>
            <div><div className="text-2xl font-brand" style={{ color: "#F0544A" }}>5</div><div className="text-slate-500">roles</div></div>
          </div>
        </div>
        <div className="text-xs text-slate-500">© Newdru · Power Your Style</div>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="lg:hidden mb-8 flex justify-center"><NewdruLogo size="lg" tagline /></div>
          <div className="card-surface p-8">
            <h2 className="text-2xl font-brand text-slate-900">Welcome back</h2>
            <p className="text-sm text-slate-500 mt-1">Sign in to your Newdru workspace.</p>

            <form onSubmit={submit} className="mt-6 space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Email</label>
                <input data-testid="login-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                  className="w-full mt-1.5 border border-slate-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F0544A]/40 focus:border-[#F0544A]"
                  placeholder="admin@newdru.com" />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Password</label>
                <input data-testid="login-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                  className="w-full mt-1.5 border border-slate-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F0544A]/40 focus:border-[#F0544A]"
                  placeholder="••••••••" />
              </div>
              {error && (
                <div data-testid="login-error" className="text-sm rounded-md px-3 py-2" style={{ background: "#FEF2F2", color: "#B91C1C", border: "1px solid #FECACA" }}>
                  {error}
                </div>
              )}
              <button data-testid="login-submit" type="submit" disabled={loading} className="btn-brand w-full flex items-center justify-center gap-2">
                {loading && <Loader2 size={16} className="animate-spin" />}
                Sign in
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
