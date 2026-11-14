import { useEffect, useState } from "react";
import { api, formatApiError, ROLE_LABELS, ALL_ROLES } from "@/lib/api";
import { toast } from "sonner";
import { Plus, X, ShieldCheck, Edit3, KeyRound } from "lucide-react";

export default function Users() {
  const [users, setUsers] = useState([]);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try { const { data } = await api.get("/users"); setUsers(data); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  useEffect(() => { load(); }, []);

  const toggle = async (u) => {
    try { await api.patch(`/users/${u.id}`, { active: !u.active });
      toast.success(u.active ? "Deactivated" : "Activated"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <div>
          <div className="text-xs uppercase tracking-widest text-slate-500">Access &amp; Roles</div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Users &amp; Roles</h1>
          <p className="text-slate-500 text-sm mt-1">Owner only. Roles enforce access on every server route.</p>
        </div>
        <button data-testid="user-new" onClick={() => setCreating(true)}
                className="bg-[#F0544A] hover:bg-[#D84038] text-white px-3 py-2 rounded-md text-sm flex items-center gap-1 shadow-sm">
          <Plus size={14} />New user
        </button>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto scroll-thin">
          <table className="newdru-table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th className="text-right">Actions</th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} data-testid={`user-row-${u.email}`}>
                  <td className="font-medium">{u.name}</td>
                  <td className="mono">{u.email}</td>
                  <td><span className="chip chip-info"><ShieldCheck size={12} />{ROLE_LABELS[u.role] || u.role}</span></td>
                  <td><span className={`chip ${u.active ? "chip-ok" : "chip-slate"}`}>{u.active ? "Active" : "Disabled"}</span></td>
                  <td className="text-right">
                    <button data-testid={`user-edit-${u.email}`} onClick={() => setEditing(u)}
                            className="p-1.5 hover:bg-slate-100 rounded text-slate-600" title="Edit / reset password"><Edit3 size={14} /></button>
                    <button data-testid={`user-toggle-${u.email}`} onClick={() => toggle(u)}
                            className="ml-2 text-sm text-indigo-700 hover:underline">
                      {u.active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {creating && <UserModal onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load(); }} />}
      {editing && <UserModal user={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
    </div>
  );
}

function UserModal({ user, onClose, onSaved }) {
  const isEdit = !!user;
  const [u, setU] = useState(
    user
      ? { name: user.name, email: user.email, role: user.role, password: "", active: user.active }
      : { email: "", name: "", role: "store_manager", password: "", active: true }
  );

  const save = async () => {
    try {
      if (isEdit) {
        const patch = { name: u.name, role: u.role, active: u.active };
        if (u.password) patch.password = u.password;
        await api.patch(`/users/${user.id}`, patch);
        toast.success("User updated");
      } else {
        await api.post("/users", u);
        toast.success("User created");
      }
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
        <div className="px-5 py-3 border-b flex justify-between items-center">
          <h3 className="font-semibold text-lg">{isEdit ? `Edit ${user.email}` : "New user"}</h3>
          <button onClick={onClose} className="p-1 hover:bg-slate-100 rounded"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-3">
          <label className="block">
            <div className="text-xs text-slate-600 mb-1 font-medium">Name</div>
            <input data-testid="user-name-input" value={u.name}
                   onChange={(e) => setU({ ...u, name: e.target.value })}
                   className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
          </label>
          <label className="block">
            <div className="text-xs text-slate-600 mb-1 font-medium">Email</div>
            <input data-testid="user-email-input" type="email" value={u.email} disabled={isEdit}
                   onChange={(e) => setU({ ...u, email: e.target.value })}
                   className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm disabled:bg-slate-50 disabled:text-slate-500" />
          </label>
          <label className="block">
            <div className="text-xs text-slate-600 mb-1 font-medium flex items-center gap-1">
              <KeyRound size={12} /> {isEdit ? "New password (leave blank to keep current)" : "Password"}
            </div>
            <input data-testid="user-password-input" type="password" value={u.password}
                   onChange={(e) => setU({ ...u, password: e.target.value })}
                   className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
          </label>
          <label className="block">
            <div className="text-xs text-slate-600 mb-1 font-medium">Role</div>
            <select data-testid="user-role-select" value={u.role}
                    onChange={(e) => setU({ ...u, role: e.target.value })}
                    className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm">
              {ALL_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
            <div className="text-[11px] text-slate-500 mt-1">
              Owner = full access · Store (Manager/Cashier) = POS, till, store stock, goods in/out · Warehouse = all-location inventory, transfers, Box-Fit.
            </div>
          </label>
          {isEdit && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={u.active} onChange={(e) => setU({ ...u, active: e.target.checked })} />
              <span>Active (user can log in)</span>
            </label>
          )}
        </div>
        <div className="border-t px-5 py-3 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 border border-slate-300 rounded-md text-sm">Cancel</button>
          <button data-testid="user-save" onClick={save}
                  className="px-4 py-2 bg-[#F0544A] hover:bg-[#D84038] text-white rounded-md text-sm font-semibold">
            {isEdit ? "Save changes" : "Create user"}
          </button>
        </div>
      </div>
    </div>
  );
}
