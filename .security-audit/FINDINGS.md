# Security findings — run R1 (14 Nov 2026)

Gate after fixes on branch `security/mynewdru-cloudflare`: **all Critical and High fixed in code** (pending review, merge and deploy). Coverage: Reduced (see scope.md).

| ID | Severity | Title | Status |
|---|---|---|---|
| SEC-001 | Critical | Emergent session-recording (PostHog → ap.emergent.sh) and a remote Emergent script ran on every page, sending staff screens and customer data to a third party and letting that third party run code inside the app | Fixed: removed from `frontend/public/index.html`; Emergent build plugin removed; CI blocks re-adding it |
| SEC-002 | Critical | CORS default `*` with credentials and `SameSite=None` cookies: any website a staff member visited could read app data with their session | Fixed: no wildcard, same-origin by default, `SameSite=Lax` |
| SEC-003 | High | Starter accounts reset to a shared demo password (published in the user guide and tests) on every restart | Fixed (PR #1): seed only when missing |
| SEC-004 | High | Role checks only in the menu: any logged-in user (incl. cashier/warehouse) could pull the full customer list (`limit` unbounded), all B2B customers/orders/receivables, message logs (phone numbers), all sales, and send SMS/WhatsApp to any number | Fixed: server-side role checks; non-owners can only search ≤10 customers |
| SEC-005 | High | Login lockout bypass: lockout keyed on the client-supplied X-Forwarded-For header, so guessing could continue forever | Fixed: Cloudflare client IP, per-email lockout, per-IP cap |
| SEC-006 | High | Owner-override endpoint let any logged-in user guess the owner password without limit | Fixed: 5 tries / 15 min |
| SEC-007 | High | Pine Labs webhook unauthenticated: anyone could mark a card payment APPROVED | Fixed: shared secret required; closed if unset |
| SEC-008 | High | Confidential cost prices (COGS) for every SKU committed in `scripts/apply_newdru_pricing.py` (still in git history) | Fixed in code; history: move to a new clean repo (see GO_LIVE_MYNEWDRU.md Step 1) |
| SEC-009 | High | Vulnerable dependencies: starlette (via fastapi 0.110), pillow 12.3, pymongo 4.6.3, python-jose/ecdsa; frontend axios, react-router | Fixed: upgraded; unused packages removed; pip-audit clean |
| SEC-010 | Medium | Public warranty endpoints: no rate limit, unlimited upload size, `javascript:` links accepted as invoice/claim images (stored XSS risk in admin) | Fixed: limits, rate limits, image/PDF/https only |
| SEC-011 | Medium | Sessions not revoked on password change / deactivation (7-day refresh tokens) | Fixed: token version |
| SEC-012 | Medium | Regex injection / ReDoS in search boxes (user text passed to `$regex`) | Fixed: escaped |
| SEC-013 | Medium | API docs (`/docs`, `/openapi.json`) public in production, listing every endpoint | Fixed: off in production |
| SEC-014 | Medium | No security headers (clickjacking, MIME sniffing, HSTS) | Fixed: headers middleware |
| SEC-015 | Medium | Weak passwords allowed for staff accounts | Fixed: min 10 characters |
| SEC-016 | Medium | `.gitignore` had no `.env` patterns despite the comment | Fixed |
| SEC-017 | Low | Public warranty status page showed the customer's full name | Fixed: first name only |
| SEC-018 | Low | Login token kept in browser localStorage (an injected script could steal it) | Fixed (R2): token kept in memory only; httpOnly cookie is the session |
| SEC-019 | Low | Customer IP addresses are sent to ipapi.co for geolocation (third-party data sharing under DPDP) | Open — owner decision; can switch to Cloudflare's own `CF-IPCountry`/`cf` data |
| SEC-020 | Low | Build-time-only frontend advisories (react-scripts toolchain: fast-uri, js-yaml, svgo, postcss) | Open — not shipped to browsers; replace react-scripts with Vite later |
| SEC-021 | Info | Secrets (Shopify token, Pine Labs keys) entered in the app are stored in MongoDB in plain text | Open — acceptable with Atlas encryption at rest and owner-only access; consider moving to Cloudflare secrets |

Triage dismissals: detect-secrets hits in `frontend/src/constants/testIds/auth.js` (test ID names, not secrets) and the warranty ID alphabet constant.

## Run R2 (15 Nov 2026) — re-scan after Unicommerce, Pine Labs and stock-count work

Scanners: pip-audit (clean), Bandit (only false positives / low), yarn audit (build-time toolchain only), npm audit for deploy tools (clean), detect-secrets (test values and docs only). Manual review of new code plus a real-browser login check.

| ID | Severity | Title | Status |
|---|---|---|---|
| SEC-022 | High | Card/UPI bills could be saved without a real Pine Labs payment (terminal reference was dropped and never checked) | Fixed: approved, unused, amount-matching terminal transaction required when the terminal is live |
| SEC-023 | Medium | Spreadsheet formula injection: a customer name like `=HYPERLINK(...)` from the public warranty form would run as a formula when the owner opens a CSV export | Fixed: all CSV exports neutralise formula cells |
| SEC-024 | Medium | No request size limit: large uploads could exhaust memory | Fixed: 6 MB cap on every request |
| SEC-025 | Medium | No Content-Security-Policy: any injected script could run and call out | Fixed: strict CSP (own scripts only), no inline scripts in the build |
| SEC-026 | Low | Free MongoDB tier has no automatic backups | Mitigated — nightly backup to private R2 bucket (35 days), restore script; still upgrade to Flex for point-in-time recovery |
| SEC-027 | Info | Offline POS queue stores unsent sales (with customer name/phone) in the till browser until it reconnects | Accepted — needed for offline billing; cleared on sync |
| SEC-028 | Medium | Production could create starter logins with the public demo password if SEED_PASSWORD was not set | Fixed — refused in production, test added |
