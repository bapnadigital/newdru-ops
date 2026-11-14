# Security audit scope

- **App:** NEWDRU Ops — internal POS, inventory, transfers, B2B, CRM and a public warranty portal for NEWDRU (Bapna Digital Services OPC Pvt Ltd).
- **Users:** owner, store and warehouse staff; public customers on /warranty.
- **Stack:** FastAPI + Motor/MongoDB (backend), React 19 (frontend). Moving from Emergent hosting to Cloudflare Workers + Containers at mynewdru.in, MongoDB Atlas (Mumbai).
- **Exposure:** internet-facing.
- **Data:** customer personal data (names, phones, emails, addresses, purchase history, invoice images), staff credentials, cost prices, payment references (masked card numbers from Pine Labs).
- **Country:** India (DPDP Act 2023 applies to customer personal data).
- **Authorisation:** owner (Shubham Bapna) asked for the audit and fixes on his own repository.
- **Repository:** private (bapnadigital/newdru-ops, clean history).
- **Gate:** default — no open Critical/High; Mediums fixed or accepted.
- **Coverage: Reduced.** Gitleaks and Semgrep rule downloads were blocked by the sandbox network; secrets were scanned with detect-secrets plus manual checks, code with Bandit plus manual review. pip-audit and yarn audit ran for dependencies. The CI workflow now runs Gitleaks on every change.

## Attack surface
- Entry points: ~120 REST endpoints under /api (FastAPI routers in backend/routes), public warranty endpoints, Pine Labs webhook, CSV imports.
- Auth: JWT (HS256) in httpOnly cookie, Bearer fallback; role checks via require_roles().
- Data stores: MongoDB; outbound calls to ipapi.co, Shopify, Pine Labs, Gupshup, MSG91.
- Hotspots reviewed: login/lockout, owner override, user management, customer/B2B/sales data access, exports, public warranty forms, payment webhook, CORS/cookies, frontend third-party scripts.
