# Newdru — User Guide

_Last updated: 6 Sep 2026 · Version 3.0 (Warranty & Shopify)_

Welcome to Newdru — the single dashboard that runs Newdru's Store, Bhiwandi warehouse, Amazon FC and Flipkart FC inventory, POS, wholesale, warranty and marketing.

## Contents
1. [Getting started](#1-getting-started)
2. [Who does what (roles)](#2-who-does-what-roles)
3. [Owner playbook](#3-owner-playbook)
4. [Store Manager playbook](#4-store-manager-playbook)
5. [Cashier playbook](#5-cashier-playbook)
6. [Warehouse Manager playbook](#6-warehouse-manager-playbook)
7. [Warehouse Staff playbook](#7-warehouse-staff-playbook)
8. [Warranty registration (customer + admin)](#8-warranty-registration)
9. [Shopify sync](#9-shopify-sync)
10. [Pine Labs card terminal](#10-pine-labs-card-terminal)
11. [B2B / Wholesale + Collections](#11-b2b--wholesale--collections)
12. [Box-Fit / Shipment Planner](#12-box-fit--shipment-planner)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Getting started

**URL**: your Newdru workspace (production URL).
**Staff login**: `…/manage-access-nd26` — this path is intentionally unguessable. Don't share it publicly. Bookmark it.
**Sign-in**: use the email and password the owner gave you. The owner sets and resets passwords in **Users**. Never share passwords in chat groups.

| Account | Role | Where you land |
|---|---|---|
| admin@newdru.com | Owner | Dashboard |
| store@newdru.com | Store Manager | Point of Sale |
| cashier@newdru.com | Cashier | Point of Sale |
| warehouse@newdru.com | Warehouse Manager | Inventory |
| staff@newdru.com | Warehouse Staff | Inventory |

**Forgot your password?** Ask the owner to reset it in **Users**.
**Locked out?** 5 wrong tries triggers a 15-minute IP lockout. Wait it out or ask the owner to clear you.

---

## 2. Who does what (roles)

| Feature | Owner | Store Mgr | Cashier | WH Mgr | WH Staff |
|---|:-:|:-:|:-:|:-:|:-:|
| Dashboard | ✅ | | | | |
| Point of Sale + Cash | ✅ | ✅ | ✅ | | |
| Products (edit) | ✅ | | | ✅ | |
| Inventory (view) | ✅ | ✅ | | ✅ | ✅ |
| Inventory (edit) | ✅ | Store only | | ✅ | Receive only |
| Goods In / Out | ✅ | Store only | | ✅ | ✅ |
| Transfers | ✅ | request only | | ✅ | pick/pack |
| Stock Ledger | ✅ | | | ✅ | |
| Box-Fit Planner | ✅ | | | ✅ | ✅ |
| Customers (CRM) | ✅ | ✅ import | ✅ add | | |
| B2B Orders + Collections | ✅ | | | | |
| Reports | ✅ | | | | |
| Warranty Registrations + Activity + Claims + Analytics | ✅ | ✅ (view) | | | |
| Warranty Settings + Shopify | ✅ | | | | |
| Users | ✅ | | | | |
| Integrations | ✅ | | | | |
| See cost / buy price / margin | ✅ | | | | |

Any URL you're not allowed to open redirects you to your home screen.

---

## 3. Owner playbook

### 3.1 Daily
1. Open **Dashboard**. Read Today's sales, Payment split, Top SKUs, Low-stock alerts.
2. Open **Warranty → User Activities**. See yesterday's registrations + purchases. Any red pill in Top SKUs on **Warranty → Analytics** deserves a look.
3. Open **Collections**. Anything in the `31-60` bucket gets a WhatsApp reminder button.

### 3.2 Weekly
1. **Products** — flag any placeholder-priced SKU (chip filter is on the top).
2. **Reports → Inventory** — export CSV to reconcile with Bhiwandi count.
3. **Users** — deactivate any staff who left.

### 3.3 Configuring the app
- **Users** — Add / disable / change roles. Passwords are hashed with bcrypt, never stored plaintext.
- **Integrations** — Pine Labs terminal, Unicommerce sync mode, Gupshup (WhatsApp), MSG91 (SMS). Toggles are `disabled | simulator | live` — simulator runs everything with fake responses so you can demo without spending.
- **Warranty Settings** — default is **6 months, manufacturing defect only**. Override per SKU (0–60 months). Shopify credentials also live here.

### 3.4 Below-COGS sale override
When a cashier tries to sell below cost the POS blocks the sale and asks for an owner's email + password + reason. Type them; the sale goes through and is tagged in Reports for review.

---

## 4. Store Manager playbook

### 4.1 Opening the shop
1. **Cash / Till** — record opening float.
2. **Inventory** — glance at STORE column; low-stock rows glow amber.
3. **Transfers** — if you're short, click **Request Transfer** from Bhiwandi.

### 4.2 Selling at the counter
1. Open **Point of Sale**.
2. **Scan the barcode** or **type product name** — clickable image tiles appear.
3. Adjust qty / discount per line; add a cart discount at the bottom.
4. Add customer (phone or email) — auto-adds to CRM.
5. Choose payment method. For card/UPI click **Pine Labs terminal** → the amount is sent to the terminal → tap card / enter UPI → status auto-updates to APPROVED with RRN.
6. Click **Complete sale** → GST invoice prints (or emails).

**Offline mode**: if internet drops, sales are queued in `localStorage` and sync automatically when you're back online (blue chip in header shows queued count).

### 4.3 Importing customers
**Customers → Bulk Import CSV**. Column order:
```
name, email, phone, total_spent, order_count,
consent_email, consent_sms, consent_whatsapp,
city, state, country, tags, channel
```
Dedupe order is email → phone → skip. 14k rows takes ~15 seconds.

### 4.4 Requesting stock
**Transfers → New Request** → from **BHIWANDI** to **STORE** → add SKUs and requested quantity → Submit. Warehouse Manager approves and dispatches. When it arrives, you scan each carton at **Goods In / Out** and quantities move automatically.

---

## 5. Cashier playbook

You can only:
- Run the POS.
- Add / look up customers.
- See your own shift totals in **Cash / Till**.

You **cannot** see cost, margin, other cashiers' sales, or edit inventory. That's by design.

### Below-COGS block
If any cart line is below cost, a red modal asks for the owner's email + password. Call the owner over — never share their password. The sale gets tagged.

### Ending shift
**Cash / Till → End shift** → count physical cash → Newdru shows the variance and prints the shift Z-report.

---

## 6. Warehouse Manager playbook

### 6.1 Bhiwandi goods-in from suppliers
1. Open **Goods In / Out**.
2. Scan the shipping-mark label or FNSKU on the carton.
3. Enter cartons × units-per-carton (+ any loose units). Newdru auto-computes the total and records an immutable movement.

### 6.2 Approving a store transfer
1. **Transfers** → open the pending row → click **Approve**.
2. Pick / pack → click **Dispatch** → Bhiwandi qty drops immediately.
3. When the store scans it in, it flips to **Received** and STORE qty rises.

### 6.3 Adjustments
Damaged / lost / recount. Click **Adjust** on any row → reason is mandatory → written to the immutable ledger. Only Manager + Owner can adjust; Staff can't.

### 6.4 Box-Fit / Shipment Planner
See section 12.

---

## 7. Warehouse Staff playbook

You can:
- View inventory across all locations.
- Scan-receive at Bhiwandi.
- Pick + pack transfers dispatched by the Manager.
- Print labels.

You cannot adjust quantities or approve transfers — that's on the Manager.

---

## 8. Warranty registration

### 8.1 Customer flow (public — no login)
1. Go to **newdru.com/pages/warranty-registration** or scan the QR on the box.
2. Type / scan your SKU (found on the invoice). Click **Look up** — you see the product photo and confirmation.
3. Fill in Name, Email, Phone, Date of purchase (max 400 days ago), Where you bought it (Amazon / Flipkart / newdru.com / offline / other), optional Retailer.
4. Upload your invoice (image or PDF, max 3 MB).
5. Click **Register warranty**. You'll see:
   - Your 8-character **Warranty ID** (e.g. `#YUVBEALQ`)
   - Warranty end date
   - **Download Certificate (PDF)** — save it, print it, or email it. The PDF has your Warranty ID, product, dates and coverage terms.

**Coverage**: **6 months, manufacturing defects only.** Not covered: physical damage, water damage, wear-and-tear, unauthorised repair, missing invoice.

### 8.2 Filing a claim
Email `hello@newdru.com` with your Warranty ID, describe the issue, attach 1–3 photos of the defect. Support opens the claim inside Newdru under your Warranty ID.

### 8.3 Admin (Owner + Store Manager)
| Screen | What you do |
|---|---|
| **Warranty → Registrations** | Search / filter / open any record. Drawer shows product / customer / IP tracking / activity feed / claims. Change status (active → approved / rejected / expired). Export CSV. |
| **Warranty → User Activities** | The Dyrect-style event feed. Date · SKU · Product · Event · Tracking Info · IP City / State / Country. Filter by event or SKU. |
| **Warranty → Claims** | Workflow: `submitted → under_review → approved / rejected → resolved`. Change status from the dropdown. |
| **Warranty → Analytics** | 5 KPIs, MoM chart, source donut, top-SKU claim-rate table, top-10 states. Choose 3 / 6 / 12 / 24-month range. |
| **Warranty Settings** | Change warranty months per SKU (0–60). Default is 6. |

### 8.4 What we replaced
This module replaces Dyrect.co (₹60,000/year). Same table shape, same fields, same PDF certificate — now inside Newdru with your data on your servers.

---

## 9. Shopify sync

Turn it on: **Warranty Settings → Shopify Sync**.

### 9.1 One-time setup
1. Shopify admin → **Settings → Apps and sales channels → Develop apps → Create an app**.
2. Name it "Newdru Sync" → **Configure Admin API scopes** → tick:
   - `read_orders`, `read_products`, `read_inventory`, `write_inventory`, `read_customers`
3. **Install app** → copy the **Admin API access token** (starts `shpat_…`). It's shown only once.
4. **Settings → Locations** → open your primary location → the numeric ID at the end of the URL is your **Location ID**.
5. In Newdru: paste `shop_domain` (e.g. `newdru.myshopify.com`), `access_token`, `location_id`, choose **Mode**, click **Save Shopify settings**.

### 9.2 Modes
| Mode | What happens |
|---|---|
| `disabled` | Nothing. |
| `pull_only` | Pull Shopify orders every time you hit **Pull orders (24h)**. Each line item becomes a `purchased` event in User Activities so you can spot Shopify buyers who haven't registered warranty yet. |
| `full` | Also pushes STORE stock levels to newdru.com (absolute values). Use once you've verified orders arrive correctly. |

### 9.3 Running it
- Click **Pull orders (24h)** to backfill.
- Click **Push store inventory** in `full` mode.
- Set up a nightly cron externally to hit these endpoints — or ask us to wire APScheduler on the backend.

**Security**: `access_token` is stored in Mongo; `GET /api/shopify/config` never returns the token, only `access_token_set: true`. Rotate the token in Shopify at any time — just paste the new one back.

---

## 10. Pine Labs card terminal

**Integrations → Pine Labs** (owner only). Modes:
- `simulator` — full end-to-end flow with fake RRN + approval code. Perfect for training.
- `uat` — staging Pine Labs environment.
- `production` — real card + UPI on your terminal.

Enter `merchant_id`, `security_token`, `store_id`, `terminal_id`, `user_id`, flip mode → Save.

At the POS:
1. Click **Pine Labs terminal**.
2. Amount is sent to the terminal → customer taps / dips card or scans UPI.
3. Newdru polls status every 2 seconds. On APPROVED, RRN + masked PAN are captured on the sale.
4. You can **Cancel** any pending txn from the same panel.

Newdru never stores raw PAN / CVV / PIN — only the last 4 digits + RRN.

---

## 11. B2B / Wholesale + Collections

**B2B Orders → New Order**
1. Pick / add a wholesale customer (has `gstin`, `credit_limit`, `payment_terms_days`).
2. Add lines. Newdru blocks the order if it would push outstanding > credit_limit.
3. Save → status = `confirmed`.
4. Click **Dispatch** → dispatch note `DN-…` is generated, stock leaves Bhiwandi/Store.
5. Click **Raise Invoice** → invoice `WI-YY-#####` + due date.
6. Record partial payments as they come in — status flips to `partially_paid` → `paid`.

**Collections** dashboard:
- Buckets `0-30 / 31-60 / 61-90 / 90+`.
- Top 20 debtors.
- Receivables CSV export.
- One-click **WhatsApp reminder** / **SMS reminder** per overdue order.

---

## 12. Box-Fit / Shipment Planner

Answers "How many cartons is 500 units of BAPNA-BLACK, and does Bhiwandi have enough?"

1. **Box-Fit Planner** → search product → type quantity → **Calculate**.
2. Result cards:
   - **Boxes**: full boxes + loose units + total (ceil)
   - **Weight**: total gross weight (Q × unit_weight)
   - **Volume**: total CFT and CBM
   - **Amazon label**: FNSKU + ASIN + MSKU
   - **Verdict banner**: green **YES** or red **SHORT by N**

Uses exact carton dims + units-per-carton set on each product. If any packaging field is missing, you get a friendly warning telling you which SKU to fix.

---

## 13. Troubleshooting

### Login says "Invalid email or password"
1. Confirm you're using the exact email from **Users** (case-sensitive server-side).
2. Try an incognito tab to rule out a stale cached token.
3. After 5 wrong tries, wait 15 minutes or ask the owner to clear you via the DB (`db.login_attempts.deleteMany({})`).

### POS doesn't accept card payment
Check **Integrations → Pine Labs → Mode**. If it says `disabled` or `simulator` you can still take card offline and mark it `card` manually — but you won't get RRN capture.

### Warranty page says "Product not found"
The SKU on the invoice must exist in **Products**. If you added a new product but the customer registered with an older shipping-mark, add it as a variant or set `barcode` / `amazon_fnsku` so the lookup can find it.

### Shopify sync returns `not_configured`
Open **Warranty Settings → Shopify** and confirm `shop_domain` and `access_token` are both saved. Then re-run.

### Bhiwandi qty seems off after a transfer
Every stock change writes an immutable row to **Stock Ledger** (`/movements`). Filter by SKU and location to see who did what and when.

### I can't find a page in the sidebar
Your role likely doesn't have it. Ask the owner to check **Users → Role**.

---

## Support
- Owner escalation: `admin@newdru.com`
- Support email: `hello@newdru.com`
- WhatsApp: use the Newdru business number configured in **Integrations → Gupshup**

---

_Newdru — Retail + wholesale, run from one clean dashboard._


## 14. Stock Count (store and warehouse staff)

1. Open **Stock Count** in the menu.
2. Scan each item's barcode (each scan adds 1), or type the number next to the product.
3. Leave a product empty if you didn't count it — it won't be changed.
4. Add a note (e.g. "Sunday count") and press **Save count**.

You won't see the system quantity; that is on purpose. The owner sees the differences.

## 15. Card / UPI on the Pine Labs machine

1. Build the bill as usual.
2. Press **Card** or **UPI** in the Pine Labs panel. The amount appears on the machine.
3. Customer pays on the machine. When it is approved the bill completes and prints by itself.
4. If the customer cancels, press **Cancel** in the panel.

Never type a card/UPI payment by hand — the app will refuse it once the machine is live.


## 16. Shipping with Shiprocket

**Wholesale orders (owner):** B2B → order → **Ship** → check the address, enter weight and box size → **Check couriers** (cheapest first) → **Ship now**. The label opens in a new tab; print it and stick it on the box. The order shows the AWB and updates to *delivered* on its own.

**Store home delivery (owner / store manager):** after completing a bill, press **Home delivery (Shiprocket)** under "Sale complete" and do the same.

Amazon, Flipkart and newdru.com orders are not shipped from this app.

## 17. System health (owner only)

**Integrations → System health** shows whether the background work is still happening:

| Line | Should say "Running" and… |
|---|---|
| Background scheduler | last OK within 5–15 min. If "Late", the site may be down; open mynewdru.in and check. |
| Unicommerce stock pull / orders | once Unicommerce is connected; every 30 min / hourly |
| Shopify orders | once the Shopify secret is added; hourly |
| Nightly backup | once a day, around 2 am |

"Not started" just means that connection has not been set up yet. "Failing" means the last attempt gave an error; hover over the time to see it.

## 18. Returns and exchanges (owner and store manager)

1. **Returns** in the menu → type the bill number from the customer's receipt → **Find bill**.
2. Enter how many of each item came back (you can't return more than was bought, or return the same item twice).
3. Choose how the money goes back: cash from the till, UPI, card reversal, or store credit. Write a short reason (e.g. "wrong size, exchanged for L").
4. **Confirm return** → a numbered GST credit note appears → **Print credit note** and give it to the customer.

For GST filing, **Reports → Credit notes CSV** downloads every credit note for the dates you pick, split by GST rate.

The items go straight back into store stock. Cash refunds are taken off the expected cash in the till report. Cashiers cannot do returns; this is deliberate, because returns are the most common way cash goes missing. Bills older than 30 days need the owner.

For an exchange: do the return first (refund as store credit), then ring up the new item as a normal sale.

## 19. Automatic sign-out

If nobody touches the mouse, keyboard or screen for **30 minutes**, the app signs out by itself. This stops someone billing or doing returns under another person's name on the shop computer. Just sign in again; nothing is lost (a half-made cart may need re-scanning).

## 20. Who can change prices

Only the **owner** can change the selling price, MRP, cost or GST rate of an existing product (on the Products screen or by CSV import). Managers can still fix names, barcodes and other details. At the till, prices always come from the product list. Cashiers cannot give discounts; the owner and store manager can.

## 21. Activity log (owner only)

**Activity Log** in the Admin menu shows who did what and when: bills, returns, stock changes, price edits, staff account changes, sign-ins and every data download. Nobody can edit or delete these entries. Pick **Data downloads** now and then: it shows anyone who downloaded the customer or sales list (highlighted in yellow).
