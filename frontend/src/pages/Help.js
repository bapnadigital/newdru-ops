/* In-app help / user guide.
   Renders /app/USER_GUIDE.md via a fetch to /api/help/user-guide. */
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { BookOpen, Download, Printer } from "lucide-react";

export default function Help() {
  const [md, setMd] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/help/user-guide");
        setMd(data.markdown || "");
      } catch (e) {
        setMd("# User Guide\n\nCould not load the user guide. Please contact your admin.");
      } finally { setLoading(false); }
    })();
  }, []);

  return (
    <div className="p-6 max-w-4xl mx-auto" data-testid="help-page">
      <div className="flex items-center justify-between mb-6 print:hidden">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg" style={{ background: "#FDECEA" }}>
            <BookOpen size={22} style={{ color: "#F0544A" }} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">User Guide</h1>
            <div className="text-sm text-slate-500">Everything you need to run Newdru, by role.</div>
          </div>
        </div>
        <div className="flex gap-2">
          <a href={`${process.env.REACT_APP_BACKEND_URL || ""}/api/help/user-guide.md`} target="_blank" rel="noreferrer"
             data-testid="download-guide"
             className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-300 text-sm font-semibold text-slate-700 hover:bg-slate-50">
            <Download size={14} /> Markdown
          </a>
          <button onClick={() => window.print()} data-testid="print-guide"
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white"
                  style={{ background: "#F0544A" }}>
            <Printer size={14} /> Print
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-slate-400">Loading user guide…</div>
      ) : (
        <article className="prose prose-slate max-w-none bg-white border rounded-2xl p-8 shadow-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
        </article>
      )}

      <style>{`
        .prose h1 { color: #0F172A; font-size: 2rem; font-weight: 800; margin-top: 0; }
        .prose h2 { color: #F0544A; font-size: 1.5rem; font-weight: 700; margin-top: 2rem; border-bottom: 1px solid #E2E8F0; padding-bottom: 0.5rem; }
        .prose h3 { color: #0F172A; font-size: 1.15rem; font-weight: 700; margin-top: 1.5rem; }
        .prose code { background: #F1F5F9; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.85em; }
        .prose table { border-collapse: collapse; }
        .prose th { background: #F8FAFC; text-align: left; padding: 0.5rem 0.75rem; border: 1px solid #E2E8F0; font-size: 0.85rem; }
        .prose td { padding: 0.5rem 0.75rem; border: 1px solid #E2E8F0; font-size: 0.9rem; }
        .prose a { color: #F0544A; }
        @media print {
          .prose h1 { page-break-before: always; }
        }
      `}</style>
    </div>
  );
}
