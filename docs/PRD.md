# Newdru — Multi-location Retail + Wholesale Operations

## Problem Statement (Original)
Build a multi-location retail + wholesale operations web app called "Newdru" with role-based access. Standard React + FastAPI + MongoDB stack. Phase-1 foundation first; integrations (Pine Labs, Unicommerce, WhatsApp/SMS/Omnisend) stubbed for later rounds. Store & Bhiwandi live, Amazon FC & Flipkart FC placeholders for future sync.

## Personas / Roles
- **Owner / Admin** (`owner`) — full access, user management, integration settings, all reports
- **Store Manager** — POS, store stock, scan I/O, print labels, request transfers, store CRM
- **Cashier** — POS, take payments, add/lookup customers, own-shift sales only, cost/margin hidden
- **Warehouse Manager** — manage Bhiwandi stock, approve/dispatch transfers, print labels
- **Warehouse Staff** — scan receive, pick/pack transfers, counts

## Core Requirements (Static)
- Server-side role checks on every request, audit log on every stock/payment action
- SKU-keyed product master, FNSKU or Code128 barcode
- GST-inclusive Buy Price → Base Cost → Recommended (2×+GST) → editable Sell Price → GST margin
- Packaging fields (weight, dimensions, units/carton), CSV import/export
- Unified inventory grid across 4 locations, low-stock thresholds per SKU per location
- Immutable stock movements ledger
- Store ⇄ Bhiwandi transfer workflow (request → approve → dispatch → receive)
- Barcode-driven goods receipt with carton math
- Label printing (thermal + PDF fallback)
- Touch-friendly POS with GST-compliant invoices, cash + split; Pine Labs UPI/card
- Offline-tolerant sale queue that syncs when back online
- Mini-CRM auto-captured on paid sales, tags, segments, purchase history, CSV export
- Owner dashboard + inventory / sales / CRM reports with CSV export
- Email + password auth (bcrypt), httpOnly cookies + Bearer fallback, expiring sessions, brute-force lockout
- Currency INR (₹)

## Phase 1 — Delivered (2026-07-27)
Auth, RBAC, brute-force lockout, audit log. 5 seeded users, 4 seeded locations. Product master + CSV. Barcode + label PDF. Unified inventory grid + immutable ledger. Barcode goods receipt, adjustments. Transfer workflow. POS + offline queue + GST invoice. Mini-CRM + segments. Owner dashboard + reports.

## Phase 2 — Delivered (2026-07-27)
Pine Labs Cloud, POS "Pine Labs terminal" panel, B2B / wholesale, Collections dashboard, Unicommerce FC sync (CSV + live scaffold), WhatsApp (Gupshup) + SMS (MSG91) senders, Integrations settings page.

## Phase 2.3 — Delivered (2026-07-31)
Catalog cleanup (49 real SKUs), Box-Fit Planner, Bulk customer CSV import, POS typeahead + tiles, strict RBAC UI, COGS floor with owner override, Users Management.

## Phase 3.0 — Warranty Module + Shopify Sync — Delivered (2026-09-06)
Replaces Dyrect.co warranty portal (₹60k/yr).

### Backend
- **Public**: `/api/public/warranty/{product-lookup,register,status/{id},claim/{id}}` (no auth).
- **Admin**: `/api/warranty/{registrations,activity,claims,analytics,export.csv,settings,public/certificate/{id}.pdf}`.
- **Shopify**: `/api/shopify/{config,settings,sync/orders,sync/inventory}` (owner-only).
- **Services**: `services/geoip.py` (ipapi.co, 24 h cache), `services/warranty_pdf.py` (A4 certificate), `services/shopify.py` (Admin API 2024-10).
- **Collections**: `warranty_registrations`, `warranty_activity`, `warranty_claims`.
- **Model**: added `warranty_months: int = 6` on ProductBase.
- 30/30 pytest cases pass.

### Frontend
- Public form at `/warranty` (2-step: SKU lookup → customer + purchase details + invoice upload → warranty ID + PDF certificate).
- Admin sidebar "Warranty" section: `/warranty-admin`, `/warranty-activity`, `/warranty-claims`, `/warranty-analytics`, `/warranty-settings`.
- All owner+store_manager for view; owner-only for mutations; cashier blocked.

## Phase 3.1 — Warranty Analytics Dashboard — Delivered (2026-09-06)
- `/warranty-analytics` page for owner + store_manager.
- 5 KPIs: total, last 30d (with MoM %), active, claims, claim rate %.
- Month-over-month bar chart (registrations + claims) with claim-rate line overlay.
- Registrations by source donut.
- Top SKUs table with red pill when claim-rate > 5%.
- Top 10 states bar chart.
- Range selector 3 / 6 / 12 / 24 months.
- Backend `/api/warranty/analytics?months=N` extended with `mom_change_pct`, `claim_rate_pct`, `mom_series[]`, per-SKU claim rates.
- 15/15 pytest cases pass (`test_warranty_analytics.py`).

## Phase 3.2 — In-app User Guide — Delivered (2026-09-09)
- `/app/USER_GUIDE.md` (313 lines) — full manual by role.
- Backend: `GET /api/help/user-guide` (JSON) + `/api/help/user-guide.md` (raw download).
- Frontend: `/help` page renders with react-markdown + remark-gfm, print + markdown-download buttons. Visible to all roles under Admin > User Guide.

## Phase 3.3 — Login security hardening — Delivered (2026-09-09)
- Removed the "Default admin: admin@newdru.com / Newdru@2026" hint from the login page.
- Staff login moved from `/login` to `/manage-access-nd26` (unguessable path). Old `/login` intentionally renders a blank page.
- Constant: `/app/frontend/src/lib/loginPath.js` → `LOGIN_PATH`. To rotate the URL, change that one string.
- All references updated: `App.js` route, `ProtectedRoute.js` redirect, `lib/api.js` 401 interceptor.

## Phase 3.4 — Code-review fixes — Delivered (2026-09-09)
Applied the high-value, low-risk fixes from the code-quality report. Explicitly deferred large refactors (600-line component splits, complexity-30+ function breakdowns) because they change too much surface area for a live app with no functional issue — flagged in the deferred list below.

### Backend
- **Fixed circular import** `server.py → routes/pinelabs.py → services/pinelabs.py → server.py`. The simulator's `PineLabsClient.get_status()` used to do `from server import db` inside the function to reach the txn collection. Refactored to accept `db=None` kwarg injected by the route handler at `routes/pinelabs.py:141`. Verified end-to-end: `pay → simulate/approve → status = APPROVED` with RRN + masked PAN.
- **Replaced `random` with `secrets`** in `routes/warranty.py` — the 8-char warranty ID generator now uses `secrets.choice()` for cryptographically-strong values. Verified with a fresh registration returning `#N9XZ54LV`.

### Frontend
- **Empty catch blocks** upgraded across `POS.js`, `Dashboard.js`, `Customers.js`, `AuthContext.js` — each swallowed error now logs to console with context (still user-friendly, no toast spam for expected 401s on `/auth/me`).
- **Array-index React keys** replaced with stable keys in `POS.js` (cart rows use `product_id`, payments use `method+i`), `WarrantyAnalytics.js` (source name), `Transfers.js` (item product_id).
- **`WarrantyPublic.js` hook deps + closure bug** fixed. `doLookup` is now a `useCallback([code])` that safely handles both event-object and string arguments, so the `?sku=BAPNA-BLACK` prefill from a QR code works without the earlier `e.preventDefault is not a function` runtime crash. `params` moved into a `useMemo` so it's not recreated every render.
- **`WarrantySettings.js`** — cleaner error logging in the load callback, kept the intentional owner-only 403 swallow.
- **`POS.js` typeahead / browse / poll / offline-sync catches** now log with `console.warn` and their HTTP status, preserving the offline-tolerant behavior.

### Deferred (safe to leave for a follow-up pass)
- Splitting `POS.js` (618 lines) into `POSCart.js` / `POSPayment.js` / `POSCustomerSearch.js` / `POSProductScanner.js`. High-risk touch of the checkout critical path.
- Breaking apart `create_sale()` (cx 38), `import_csv()` (cx 30), `box_fit()` (cx 27) — same reasoning.
- Migrating auth token from `localStorage` to memory-only + refresh token flow. The current setup is per the auth integration playbook (httpOnly cookie primary + Bearer fallback for cookie-blocked clients) and works with the deployment.
- Full `useMemo` sweep on `Customers.js:206` and `WarrantyClaims.js:99` filters (perf-only, no functional bug).

### Verification (2026-09-09)
- Backend health: 200 ✅
- Warranty register: 200 `#N9XZ54LV` ✅
- Pine Labs simulator round-trip (pay → approve → status): APPROVED with RRN + masked PAN ✅
- Public `/warranty?sku=BAPNA-BLACK` end-to-end submit: warranty ID displayed + certificate link ✅
- Login credential hint gone ✅
- Frontend compiled with 1 pre-existing lint warning only ✅

### Env additions (Phase 3)
- `SHOPIFY_MODE=disabled` (disabled | pull_only | full)
- `SHOPIFY_SHOP_DOMAIN`, `SHOPIFY_ACCESS_TOKEN`, `SHOPIFY_LOCATION_ID`, `SHOPIFY_WEBHOOK_SECRET` — all optional; DB settings take precedence.

### Known behavioural note
Geo columns show "—" in preview because `ipapi.co` returns null for internal ingress IPs (34.x/35.x). In production behind Cloudflare/nginx the real client IP is forwarded correctly and city/state/country populate.

## Pending / P0
- **Shopify credentials** from user (shop_domain, `shpat_…` access_token, location_id, mode preference) so we can flip mode from `disabled` → `pull_only` → `full`. Ask asked via `ask_human` in iteration 5.

## Deferred (Phase 3.3+)
- P1: Unicommerce Live API pull for AMAZON_FC / FLIPKART_FC (scaffold behind `UNICOMMERCE_MODE=live`).
- P1: Send warranty confirmation email + WhatsApp on registration (hooks in `services/messaging.py`).
- P1: Nightly cron on Shopify sync (APScheduler) once creds are pasted.
- P2: Revenue Analytics module (BiteSpeed attribution) — hooks in place on POS.
- P2: Object-storage image upload for POS product tiles (replace Shopify hotlinks).
- P2: Audit log viewer UI.
- P2: Thermal printer ZPL/ESC-POS test path.

## Test Credentials
See `/app/memory/test_credentials.md`

## Architecture
- **Backend**: FastAPI + Motor; routes in `/app/backend/routes/`; services in `/app/backend/services/`; tests in `/app/backend/tests/`.
- **Frontend**: React 19 + React Router 7 + Tailwind + shadcn + Sonner + JsBarcode + Recharts + react-markdown + remark-gfm; pages in `/app/frontend/src/pages/`.
