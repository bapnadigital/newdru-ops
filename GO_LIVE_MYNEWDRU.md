# Going live on https://mynewdru.in (Cloudflare)

How NEWDRU Ops runs after the move, and the exact steps to get there.

## How it is set up

```
Staff / customers
      │  https://mynewdru.in
      ▼
Cloudflare  ── firewall (WAF), DDoS protection, rate limits
      │      ── Cloudflare Access: staff must pass an email code before they even see the login page
      ▼
Cloudflare Worker  ──►  one always-on container running the app (pinged every 5 minutes)
                              │  encrypted connection
                              ▼
                    MongoDB Atlas (Mumbai), owned by Shubham, daily backups
```

- **Code** lives on GitHub. It contains **no passwords, keys or customer data**.
- **Secrets** (database password, signing key, Shopify / Pine Labs keys) live only in Cloudflare, in Shubham's account.
- **Data** lives only in MongoDB Atlas, in Shubham's account. Developers never get the database password; they work on fake demo data on their own computers.
- **Going live** needs Shubham to click **Approve** on GitHub. Nobody else can push a change to mynewdru.in.
- **Emergent** is fully removed: no Emergent scripts in the app, no Emergent access to the code, no Emergent hosting.

## Monthly cost (approximate, check current prices on each site)

| Item | Why | Cost |
|---|---|---|
| Cloudflare Workers Paid | Required to run the container | $5/month + about $5–10 usage for one small always-on container |
| Cloudflare Pro plan for mynewdru.in (recommended) | Managed firewall rules against common attacks | about $20–25/month |
| Cloudflare Zero Trust (Access) | Email-code gate for staff | Free up to 50 users |
| MongoDB Atlas Flex, Mumbai (AWS ap-south-1) | Database with daily backups | from about $8/month, capped around $30 |

Roughly **$40–70 a month (₹3,500–6,000)** for everything.

---

## Steps only Shubham can do

These need your logins or a payment, so I cannot do them for you. Do them in order. Each takes 2–10 minutes. Never paste a password or key into chat, GitHub issues or WhatsApp.

### Step 1 — New, clean GitHub repository (cuts Emergent off)

Done: `bapnadigital/newdru-ops` now holds the clean code. The old repo `newdru-main` was created by Emergent, Emergent can still push to it, and its history contains the old demo password and your cost prices. We start a fresh repo with clean history.

1. Go to https://github.com/new
2. Owner: **bapnadigital**. Name: **newdru-ops**. Choose **Private**. Do **not** tick "Add a README".
3. Click **Create repository**, then tell Claude "repo created". Claude pushes the clean code.
4. Remove Emergent's GitHub access: GitHub → your profile picture → **Settings** → **Applications** → **Installed GitHub Apps** (and **Authorized OAuth Apps**) → **Emergent** → **Configure** → remove access to all repositories, or **Uninstall**. Do the same under the **bapnadigital** organisation settings if Emergent appears there.
5. Later, once mynewdru.in is live: open `newdru-main` → Settings → scroll down → **Archive this repository**. Never give the team access to the old repo.

### Step 2 — Put mynewdru.in on Cloudflare

1. Log in to Cloudflare → **Add a domain** → type `mynewdru.in` → choose the **Pro** plan (or Free to start).
2. Cloudflare shows two nameservers (like `xxx.ns.cloudflare.com`).
3. Log in where you bought mynewdru.in (Namecheap, GoDaddy, etc.) → domain → **Nameservers** → **Custom DNS** → paste the two Cloudflare nameservers → Save.
4. Wait until Cloudflare emails "mynewdru.in is now active" (usually under an hour).
5. In Cloudflare for mynewdru.in: **SSL/TLS** → set to **Full (strict)**. Turn on **Always Use HTTPS** and **HSTS**.
6. **Workers & Pages** → **Plans** → subscribe to **Workers Paid** ($5/month).

### Step 3 — Create the database (MongoDB Atlas, in your name)

1. Sign up at https://www.mongodb.com/cloud/atlas with **your own** email (not a developer's).
2. Create a project **NEWDRU** → **Create cluster** → **Flex** → provider **AWS**, region **Mumbai (ap-south-1)** → name `newdru-prod`.
3. **Database Access** → **Add new database user** → username `newdru_app` → **Autogenerate secure password** → copy it into your password manager → role: **Read and write to any database**. (Only this one user.)
4. **Network Access** → **Add IP address** → **Allow access from anywhere** (Cloudflare's servers don't have fixed addresses; the long random password and encryption protect it).
5. **Connect** → **Drivers** → copy the connection string. It looks like `mongodb+srv://newdru_app:<password>@newdru-prod.xxxx.mongodb.net/`. Replace `<password>` with the password from step 3. Keep it in your password manager only.
6. Turn on backups: cluster → **Backup** → make sure daily snapshots are on.

### Step 4 — Let GitHub deploy to Cloudflare, with your approval

1. Cloudflare → profile icon → **My Profile** → **API Tokens** → **Create Token** → use the template **Edit Cloudflare Workers** → Account: your account; Zone: **mynewdru.in**.
   Before creating, under **Permissions** click **+ Add more** and make sure these three Account rows are there (add any that are missing): **Containers → Edit**, **Workers R2 Storage → Edit**, **Workers Scripts → Edit**. Then **Continue to summary** → **Create**. Copy the token (shown once).
   *Already made the token without them?* API Tokens → the token's **⋯** → **Edit** → add the rows → **Save**. The token value stays the same, so GitHub doesn't need changing.
2. Cloudflare → **Workers & Pages** → right side shows **Account ID**. Copy it.
3. GitHub → `newdru-ops` → **Settings** → **Environments** → **New environment** → name `production`.
   - Tick **Required reviewers** → add **yourself** → Save.
   - Under **Environment secrets** → **Add secret**: `CLOUDFLARE_API_TOKEN` = the token. Add another: `CLOUDFLARE_ACCOUNT_ID` = the account ID.
4. GitHub → **Settings** → **Branches** → **Add branch protection rule** for `main`: tick **Require a pull request before merging** (1 approval), **Require status checks to pass** (pick "Backend security tests", "Frontend build", "Secret scan"), **Do not allow bypassing**. Save.
5. GitHub → **Settings** → **Code security** → turn on **Secret scanning**, **Push protection** and **Dependabot alerts**.

### Step 5 — First deploy and secrets

1. GitHub → **Actions** → **Deploy to mynewdru.in** → **Run workflow**. You'll get a request to approve: click **Review deployments** → **Approve**. The first run takes about 10 minutes.
2. Cloudflare → **Workers & Pages** → **newdru-ops** → **Settings** → **Variables and Secrets** → add each as type **Secret**:

| Name | Value |
|---|---|
| `MONGO_URL` | The Atlas connection string from Step 3 |
| `DB_NAME` | `newdru` |
| `JWT_SECRET` | A 64-character random password made with your password manager's **Generate password** button (letters and numbers). Don't use a website to generate it |
| `SEED_PASSWORD` | A strong first-time password for the starter accounts (you'll change them in Users anyway) |
| `BUSINESS_NAME` | `NEWDRU` |
| `BUSINESS_GSTIN` | Your GSTIN |
| `INVOICE_PREFIX` | `NW` (or what the store uses today) |
| `PINELABS_MODE` | `simulator` for now |
| `CRON_SECRET` | Another 64-character random password from your password manager (lets the 5-minute scheduler run sync jobs) |
| `UNICOMMERCE_MODE` | `live` (after the Unicommerce step below) |
| `UNICOMMERCE_TENANT` | The first part of your Uniware address: for `newdru.unicommerce.com` it is `newdru` |
| `UNICOMMERCE_USER` | The Uniware API user's login (see below) |
| `UNICOMMERCE_PASSWORD` | That user's password |
| `UNICOMMERCE_FACILITIES` | Which app location reads from which Uniware facility, e.g. `AMAZON_FC=AMZFBA01,FLIPKART_FC=FKSMART01` |

3. Click **Deploy** (or re-run the GitHub deploy) so the app picks up the secrets.

### Step 5b — Connect Unicommerce

What we found in your Unicommerce (15 Nov 2026): one warehouse (`bapnadigital`, Khopat, Thane), channels Amazon Easy Ship, Flipkart, Shopify and Custom, 33 products — and **zero stock on every product** while 400+ units of orders wait (e.g. 165 GlowSkin masks, 48 sofa vacuums, 46 eye massagers). So the job is to **send the app's real stock into Unicommerce**, not the other way round.

1. Uniware → **Settings → Users → Add user**: name `NEWDRU Ops API`, role **Admin**, facility `bapnadigital`. Set the password yourself (password manager).
2. Confirm the SKU matching sheet (`NEWDRU_Unicommerce_SKU_Mapping_DRAFT.csv`): fill the rows marked `check`/`missing`, fix the codes Uniware cut off on screen, then upload it in **Integrations → Unicommerce → Upload SKU mapping**.
3. Cloudflare secrets: `UNICOMMERCE_MODE=live`, `UNICOMMERCE_TENANT=bapnadigital`, `UNICOMMERCE_USER`, `UNICOMMERCE_PASSWORD`, `UNICOMMERCE_PUSH_LOCATION=BHIWANDI` (or whichever app location holds the stock that the Thane warehouse ships), `UNICOMMERCE_PUSH_FACILITY=bapnadigital`, `UNICOMMERCE_SHELF` (your Uniware shelf code, ask your warehouse team; default `DEFAULT`), `CRON_SECRET`. Leave `UNICOMMERCE_PUSH_ENABLED` unset for now.
4. In the app: **Integrations → Unicommerce → Preview**. It lists every SKU with app stock, Unicommerce now and what it will set. Nothing is sent.
5. When the preview looks right: add `UNICOMMERCE_PUSH_ENABLED=true`, then press **Send N changes**. Unicommerce then pushes those quantities to Amazon, Flipkart and Shopify — so do a stock count first (Step 5d).
6. Optional, once you trust it: `UNICOMMERCE_AUTO_PUSH=true` sends stock every 30 minutes automatically. Marketplace orders are pulled hourly either way.

### Step 5c — Pine Labs machine in the store

The app already talks to Pine Labs' **Plutus Cloud** service: the cashier presses **Card** or **UPI** in the app, the amount appears on the Pine Labs machine, the customer pays, and the app automatically creates the GST bill and reduces store stock.

1. Call your Pine Labs relationship manager (or support) and ask to **enable "Plutus Cloud Based Integration (CBI)" on your store terminal for a billing software**. Ask them for: **Merchant ID, Security Token, Store ID, Client ID / IMEI of the terminal, and the UAT test details**. Also give them the callback URL: `https://mynewdru.in/api/pinelabs/webhook?token=<your PINELABS_WEBHOOK_SECRET>`.
2. In the app: **Admin → Integrations → Pine Labs terminal** → type the details they gave you → mode **UAT** → Save.
3. Cloudflare secrets: `PINELABS_MODE=uat` and `PINELABS_WEBHOOK_SECRET` (a long random password). Redeploy.
4. Test with Pine Labs on the line: POS → add any product → **Card** → the machine should show the amount → pay → bill prints. Then refund it on the machine.
5. Ask Pine Labs to move you to production, change `PINELABS_MODE=production`, redeploy, do one real ₹1 sale and refund.

Once the machine is live, the app **refuses** a card/UPI bill unless the money really came through the machine (each machine payment can be used on one bill only). Cash bills work as before.

### Step 5d — Store stock that staff keep right

- **Every sale** reduces Store stock automatically. **Goods In** adds stock; **Transfers** move stock between Bhiwandi and the Store.
- **Stock Count** (new menu item): staff scan or type what is physically on the shelf. They do **not** see the system number, so they can't just copy it. Differences are saved as "count" entries in the Stock Ledger with the person's name.
- You see each count's missing / extra units on the same page. Suggested routine: full store count every Sunday night, and a quick count of the top 10 products every evening.
- Before the first push to Unicommerce, do a full count of Bhiwandi too, so marketplaces get real numbers.

### Step 5e — Shiprocket (wholesale orders and store home-deliveries)

Marketplace and newdru.com orders keep shipping the way they do today. From the app you can ship **wholesale (B2B) orders** and **store bills that need home delivery**: one click books the courier (cheapest recommended, or pick one), schedules pickup, opens the label, and tracking updates the order until it is delivered.

1. Shiprocket → **Settings → API → Create API User**. Use a **different email** from your main login (e.g. `ops@newdru.com`). Save the password in your password manager.
2. Shiprocket → **Settings → Pickup Addresses**: note the exact **nickname** of the Bhiwandi pickup (and the store's, if the store ships too).
3. Cloudflare secrets: `SHIPROCKET_MODE=live`, `SHIPROCKET_EMAIL`, `SHIPROCKET_PASSWORD`, `SHIPROCKET_PICKUP_LOCATION` (nickname), `SHIPROCKET_PICKUP_PINCODE`, optionally `SHIPROCKET_STORE_PICKUP_LOCATION` / `SHIPROCKET_STORE_PICKUP_PINCODE`, and `SHIPROCKET_WEBHOOK_SECRET` (random password).
4. Shiprocket → **Settings → API → Webhooks**: URL `https://mynewdru.in/api/courier-updates`, token = your `SHIPROCKET_WEBHOOK_SECRET`, turn it on. (Tracking is also checked hourly without it.)
5. Test: B2B → any order → **Ship** → enter address and weight → **Check couriers** → **Ship now**.

### Step 5f — Nightly backups (automatic, nothing to do)

Every night at 2:00 am the whole database is saved to a private Cloudflare storage bucket called **newdru-backups** (Cloudflare → R2). The last 35 days are kept; older ones are deleted automatically. Only your Cloudflare login can see them.

To check: Cloudflare → **R2** → **newdru-backups** → folder `newdru-ops` — you should see one file per day, e.g. `2026-11-16.json.gz`.
To restore (only if something goes badly wrong): download that day's file and ask your developer to run `scripts/restore_backup.py` (instructions are at the top of that file). It restores into a new database first, so nothing is overwritten by mistake.

### Step 6 — Staff-only gate (Cloudflare Access)

1. Cloudflare → **Zero Trust** (free plan) → **Access** → **Applications** → **Add an application** → **Self-hosted**.
2. Name `NEWDRU Ops staff`, domain `mynewdru.in`, path empty (whole site). Session duration **1 month**.
3. Policy: **Allow** → Include → **Emails** → list each staff member's email (and yours). Login method: **One-time PIN**.
4. Add a second application **NEWDRU public warranty** with these paths on `mynewdru.in`, policy action **Bypass** → Include **Everyone**:
   `warranty`, `api/public/*`, `api/warranty/public/*`, `api/pinelabs/webhook`, `static/*`, `newdru-logo.png`, `api/health`, `api/courier-updates`
5. Test: open mynewdru.in in a private window. You should see a Cloudflare email-code screen. `mynewdru.in/warranty` should open without it.

### Step 7 — Move the data from Emergent (one time, 10 minutes, at closing time)

1. Tell Claude "ready to move data". Claude asks Emergent's agent to run `scripts/migrate_db.py` once, copying the live database into Atlas, and shows you the counts (every collection must say OK).
2. Right after: Atlas → **Database Access** → `newdru_app` → **Edit** → **Edit password** → autogenerate a new one → update `MONGO_URL` in Cloudflare with it. This makes the password Emergent saw useless.
3. Log in at `https://mynewdru.in/manage-access-nd26`, check products, stock, a few customers and warranty records.
4. Change every staff password in **Users**. Give each person their own login.
5. Once happy (give it a week): stop the Emergent deployment and ask Emergent to delete the app and its database.

### Step 8 — Firewall rules (Cloudflare)

Cloudflare → mynewdru.in → **Security** → **WAF**:
- **Managed rules** (Pro plan): turn on the **Cloudflare Managed Ruleset** and **OWASP Core Ruleset**.
- **Rate limiting rule**: if URI path contains `/api/auth/login` → more than 10 requests per minute from the same IP → **Block** for 10 minutes.
- **Rate limiting rule**: if URI path starts with `/api/public/` → more than 30 requests per minute → **Managed Challenge**.
- **Bots**: turn on **Bot Fight Mode**.

---

## What keeps your data safe, in plain words

| Risk | What stops it |
|---|---|
| A stranger on the internet | Cloudflare email-code gate, firewall, rate limits, login lockout |
| A staff member copying the customer list | Only the owner can browse or export customers, B2B and message logs. Staff can only search a few results at a time. Every login and stock/payment action is logged |
| A developer taking data | Developers never get the database or Cloudflare logins. Nothing goes live without your Approve click. Ask Claude to review a pull request before you approve it |
| Secrets leaking on GitHub | No secrets in code, `.env` files blocked, secret scanning + push protection, automatic secret scan on every change |
| Emergent | No Emergent code or tracking in the app, no access to the new repo, data deleted after the move |
| Losing data | Atlas daily backups in Mumbai |
| The app going down | Cloudflare restarts the container automatically, a check runs every 5 minutes, Cloudflare emails on errors (turn on notifications in Workers → newdru-ops → Settings) |

No setup is 100% secure. The biggest remaining risk is people: a staff member sharing their login, or a bad change being approved. Keep logins personal and approve only changes Claude or a trusted developer has reviewed.
