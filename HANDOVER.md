# NEWDRU Ops — Team Handover

_Handover date: 14 Nov 2026 · Owner: Shubham Bapna_

This is the starting point for anyone joining the NEWDRU Ops app. Read it first, then pick an issue.

## 1. What this app is

NEWDRU Ops is our internal operations app, built on Emergent. It runs:

- **Point of Sale (POS)** for the store, with GST invoices, cash and split payments, and an offline queue
- **Inventory** across Store, Bhiwandi warehouse, Amazon FC and Flipkart FC, with an unchangeable stock ledger
- **Transfers** between Store and Bhiwandi (request → approve → dispatch → receive), goods receipt and labels
- **B2B / wholesale** orders and a collections dashboard
- **Mini-CRM** of store customers
- **Warranty portal** (public page at `/warranty`) that replaces Dyrect.co, plus warranty admin, claims and analytics
- **Box-Fit planner** for shipments
- **User guide** inside the app at `/help` (source: `USER_GUIDE.md`)

Full feature history: `docs/PRD.md`.

## 2. Tech stack

| Part | Tech | Where |
|---|---|---|
| Backend | Python, FastAPI, Motor (MongoDB) | `backend/` (routes in `backend/routes/`, services in `backend/services/`) |
| Frontend | React 19, React Router 7, Tailwind, shadcn/ui, Recharts | `frontend/src/pages/` |
| Database | MongoDB | connection in `backend/.env` (`MONGO_URL`, `DB_NAME`) |
| Tests | pytest (calls a running server) | `backend/tests/` |
| Data scripts | One-off import and sync scripts | `scripts/` |

Staff login is at `/manage-access-nd26` (set in `frontend/src/lib/loginPath.js`). `/login` is blank on purpose.

## 3. Settings (backend `.env`)

Never commit `.env` files or real keys to GitHub.

| Setting | What it does |
|---|---|
| `MONGO_URL`, `DB_NAME` | Database |
| `CORS_ORIGINS` | Leave empty in production (the app and API share mynewdru.in). Only for local development with a separate frontend; `*` is ignored |
| `APP_ENV` | `production` turns off API docs and requires a strong `JWT_SECRET` |
| `COOKIE_SAMESITE` | `lax` (default). Only `none` for a split frontend/backend setup |
| `PINELABS_WEBHOOK_SECRET` | Shared secret Pine Labs must send to the webhook; without it the webhook is closed |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | First-time owner account (only used if the account does not exist yet) |
| `SEED_PASSWORD` | First-time password for the starter store and warehouse accounts |
| `SEED_RESET_PASSWORDS` | `true` forces starter passwords back to the seed value on restart. Demo only. Keep `false` in production |
| `PINELABS_MODE` | `simulator` (fake card payments), `uat`, `production` |
| `SHOPIFY_MODE` + `SHOPIFY_*` | `disabled`, `pull_only`, `full`. Settings saved in the app take priority |
| `UNICOMMERCE_MODE` | `live` turns on automatic stock (30 min) and order (60 min) sync |
| `UNICOMMERCE_TENANT`, `UNICOMMERCE_USER`, `UNICOMMERCE_PASSWORD` | Read-only Uniware API login |
| `UNICOMMERCE_FACILITIES` | `LOCATION=FACILITY_CODE` pairs; only mapped locations are overwritten |
| `CRON_SECRET` | Lets the Cloudflare 5-minute scheduler trigger sync jobs |
| `GUPSHUP_MODE`, `MSG91_MODE` + keys | WhatsApp and SMS: `disabled`, `simulator`, `live` |
| `BUSINESS_NAME`, `BUSINESS_GSTIN`, `INVOICE_PREFIX` | Invoice details |

Frontend `.env`: `REACT_APP_BACKEND_URL` = the public address of the app (changes when we move to the custom domain).

## 4. Current status (14 Nov 2026)

**Built and tested:** everything in section 1. The original builder's last test round passed 100%.

**Not live yet:**
- Card payments are in **simulator** mode. They are not real until Pine Labs is switched to UAT and then production.
- Shopify sync is **disabled** (needs credentials).
- WhatsApp / SMS are in **simulator** mode.
- Unicommerce live sync is built (stock + marketplace orders, read-only) and waits for the Uniware API login.

**Fixed in this handover (branch `handover/team-setup`):**
- Starter account passwords were reset to the demo password on every server restart. That meant any password the owner changed in Users reverted. Now passwords are only set when an account is first created.
- The shared demo password was printed in the user guide. Removed.
- The user guide path was hard-wired to Emergent's `/app` folder. It now works on any server.
- Two test files pointed at the old Emergent preview address. They now default to a local server.

## 5. How we work (rules for the team)

1. **GitHub is the single source of truth.** Every change goes through a branch and a pull request into `main`. No direct pushes to `main`.
2. **No Emergent.** The app no longer uses Emergent in any way. Do not connect this repository to Emergent or any other AI app builder.
3. **One issue = one piece of work.** Assign yourself before you start. If it is not in an issue, it is not on the plan.
4. **Move the issue forward with labels:** add `status: in progress` when you start, `status: review` when your pull request is open. Closing the pull request with `Closes #N` closes the issue.
5. **Blocked on Shubham?** Add the `needs-shubham` label and write exactly what you need in one comment.
6. **Never** put passwords, API keys or customer data in issues, commits or chat.
7. **Test before review:** run the backend tests against a local server (`REACT_APP_BACKEND_URL=http://localhost:8001 pytest backend/tests`) and click through the page you changed.

## 6. Where Shubham tracks progress

- **Milestones** (progress bar per goal): https://github.com/bapnadigital/newdru-ops/milestones
- **Everything waiting on Shubham:** https://github.com/bapnadigital/newdru-ops/issues?q=is%3Aopen+label%3Aneeds-shubham
- **Work in progress:** https://github.com/bapnadigital/newdru-ops/issues?q=is%3Aopen+label%3A%22status%3A+in+progress%22
- **Open pull requests:** https://github.com/bapnadigital/newdru-ops/pulls

### Milestones

| Milestone | Goal |
|---|---|
| **M1 · Go live on custom domain** | Safe to use daily on our own domain with real passwords and backups |
| **M2 · Integrations live** | Real card payments, Shopify sync, warranty messages, FC stock |
| **M3 · Improvements** | Nice-to-haves and clean-up |

### Labels

- Priority: `P0` (must do before go-live), `P1` (next), `P2` (later)
- Area: `area: backend`, `area: frontend`, `area: devops`, `area: integrations`
- Status: `status: in progress`, `status: review`
- `needs-shubham`: blocked until Shubham gives an answer, a login or an approval

## 7. Hosting, security and data rules

Production runs at **https://mynewdru.in** on Cloudflare, with data in MongoDB Atlas. See `GO_LIVE_MYNEWDRU.md`.

- Developers **never** get production database or Cloudflare access. Work locally with demo data (`backend/seed_demo.py`) or the in-memory test database.
- Never download, copy or paste real customer data into issues, chats, spreadsheets or AI tools.
- Every change goes live only after Shubham approves the deployment.
- Run the security tests before opening a pull request: `cd backend && pip install -r requirements-dev.txt && pytest tests/test_security.py -q`.
