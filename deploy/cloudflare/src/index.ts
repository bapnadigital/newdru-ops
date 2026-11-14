/**
 * NEWDRU Ops on Cloudflare.
 *
 * mynewdru.in  ->  this Worker  ->  one always-warm container running the app.
 * Secrets live only in Cloudflare (set with `wrangler secret put`), never in GitHub.
 */
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  APP: DurableObjectNamespace<NewdruApp>;
  BACKUPS?: R2Bucket; // private nightly database backups
  // Secrets (wrangler secret put NAME)
  MONGO_URL: string;
  DB_NAME: string;
  JWT_SECRET: string;
  ADMIN_EMAIL?: string;
  SEED_PASSWORD?: string;
  PINELABS_MODE?: string;
  PINELABS_WEBHOOK_SECRET?: string;
  SHOPIFY_MODE?: string;
  SHOPIFY_SHOP_DOMAIN?: string;
  SHOPIFY_ACCESS_TOKEN?: string;
  SHOPIFY_LOCATION_ID?: string;
  SHOPIFY_WEBHOOK_SECRET?: string;
  SHOPIFY_CLIENT_ID?: string;
  SHOPIFY_CLIENT_SECRET?: string;
  UNICOMMERCE_MODE?: string;
  UNICOMMERCE_TENANT?: string;
  UNICOMMERCE_USER?: string;
  UNICOMMERCE_PASSWORD?: string;
  UNICOMMERCE_FACILITIES?: string;
  CRON_SECRET?: string;
  MSG91_AUTH_KEY?: string;
  MSG91_SENDER_ID?: string;
  UNICOMMERCE_PUSH_LOCATION?: string;
  UNICOMMERCE_PUSH_FACILITY?: string;
  UNICOMMERCE_SHELF?: string;
  UNICOMMERCE_PUSH_ENABLED?: string;
  UNICOMMERCE_AUTO_PUSH?: string;
  SHIPROCKET_MODE?: string;
  SHIPROCKET_EMAIL?: string;
  SHIPROCKET_PASSWORD?: string;
  SHIPROCKET_PICKUP_LOCATION?: string;
  SHIPROCKET_PICKUP_PINCODE?: string;
  SHIPROCKET_STORE_PICKUP_LOCATION?: string;
  SHIPROCKET_STORE_PICKUP_PINCODE?: string;
  SHIPROCKET_WEBHOOK_SECRET?: string;
  GUPSHUP_MODE?: string;
  GUPSHUP_API_KEY?: string;
  GUPSHUP_APP_NAME?: string;
  GUPSHUP_SOURCE_NUMBER?: string;
  MSG91_MODE?: string;
  BUSINESS_NAME?: string;
  BUSINESS_GSTIN?: string;
  INVOICE_PREFIX?: string;
}

// Only these settings are handed to the app. Anything else stays in Cloudflare.
const PASS_THROUGH: (keyof Env)[] = [
  "MONGO_URL", "DB_NAME", "JWT_SECRET", "ADMIN_EMAIL", "SEED_PASSWORD",
  "PINELABS_MODE", "PINELABS_WEBHOOK_SECRET",
  "SHOPIFY_MODE", "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_LOCATION_ID", "SHOPIFY_WEBHOOK_SECRET",
  "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
  "UNICOMMERCE_MODE", "UNICOMMERCE_TENANT", "UNICOMMERCE_USER", "UNICOMMERCE_PASSWORD",
  "UNICOMMERCE_FACILITIES", "CRON_SECRET", "MSG91_AUTH_KEY", "MSG91_SENDER_ID",
  "UNICOMMERCE_PUSH_LOCATION", "UNICOMMERCE_PUSH_FACILITY", "UNICOMMERCE_SHELF", "UNICOMMERCE_PUSH_ENABLED", "UNICOMMERCE_AUTO_PUSH",
  "SHIPROCKET_MODE", "SHIPROCKET_EMAIL", "SHIPROCKET_PASSWORD", "SHIPROCKET_PICKUP_LOCATION", "SHIPROCKET_PICKUP_PINCODE", "SHIPROCKET_STORE_PICKUP_LOCATION", "SHIPROCKET_STORE_PICKUP_PINCODE", "SHIPROCKET_WEBHOOK_SECRET", "GUPSHUP_MODE", "GUPSHUP_API_KEY", "GUPSHUP_APP_NAME", "GUPSHUP_SOURCE_NUMBER",
  "MSG91_MODE", "BUSINESS_NAME", "BUSINESS_GSTIN", "INVOICE_PREFIX",
];

export class NewdruApp extends Container<Env> {
  defaultPort = 8001;
  // Stay up for a full day after the last request; the cron below pings every
  // 5 minutes, so in practice the app never sleeps.
  sleepAfter = "24h";
  // Needed to reach MongoDB Atlas, Shopify, Pine Labs and messaging providers.
  enableInternet = true;

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    const vars: Record<string, string> = {
      APP_ENV: "production",
      COOKIE_SAMESITE: "lax",
      SEED_RESET_PASSWORDS: "false",
      ENABLE_API_DOCS: "false",
    };
    for (const k of PASS_THROUGH) {
      const v = env[k];
      if (typeof v === "string" && v.length) vars[k] = v;
    }
    this.envVars = vars;
  }

  override onError(error: unknown) {
    console.error("container error", error);
    throw error;
  }
}

const BACKUP_CRON = "30 20 * * *"; // 20:30 UTC = 02:00 IST
const KEEP_BACKUP_DAYS = 35;

async function nightlyBackup(app: DurableObjectStub<NewdruApp>, env: Env) {
  if (!env.BACKUPS || !env.CRON_SECRET) {
    console.error("backup skipped: R2 bucket or CRON_SECRET missing");
    return;
  }
  const r = await app.fetch(new Request("https://mynewdru.in/api/internal/backup", {
    method: "POST", headers: { "X-Cron-Token": env.CRON_SECRET },
  }));
  if (!r.ok) { console.error("backup failed", r.status); return; }
  const day = new Date().toISOString().slice(0, 10);
  await env.BACKUPS.put(`newdru-ops/${day}.json.gz`, await r.arrayBuffer(), {
    httpMetadata: { contentType: "application/gzip" },
    customMetadata: { documents: r.headers.get("X-Backup-Documents") || "" },
  });
  // keep the last 35 days
  const cutoff = Date.now() - KEEP_BACKUP_DAYS * 86400_000;
  const list = await env.BACKUPS.list({ prefix: "newdru-ops/" });
  const old = list.objects.filter((o) => o.uploaded.getTime() < cutoff).map((o) => o.key);
  if (old.length) await env.BACKUPS.delete(old);
}

// One named instance so every request and the keep-warm ping hit the same app.
const instance = (env: Env) => getContainer(env.APP, "newdru-ops-main");

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    // Never serve the old Emergent/preview hosts or plain HTTP.
    if (url.protocol !== "https:") {
      url.protocol = "https:";
      return Response.redirect(url.toString(), 301);
    }
    // Scheduled jobs and backups are only ever called by this Worker's own
    // scheduler (straight to the container), never from the internet.
    if (url.pathname.startsWith("/api/internal/")) {
      return new Response("Not found", { status: 404 });
    }
    return instance(env).fetch(request);
  },

  // Every 5 minutes: keep the app warm, check health, and let it run any
  // scheduled jobs that are due (Unicommerce stock every 30 min, orders hourly).
  // Once a night (02:00 IST): full database backup into the private R2 bucket.
  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext) {
    const app = instance(env);
    if (event.cron === BACKUP_CRON) {
      ctx.waitUntil(nightlyBackup(app, env));
      return;
    }
    ctx.waitUntil((async () => {
      try {
        const h = await app.fetch(new Request("https://mynewdru.in/api/health"));
        if (!h.ok) console.error("health check failed", h.status);
        if (env.CRON_SECRET) {
          const r = await app.fetch(new Request("https://mynewdru.in/api/internal/cron", {
            method: "POST",
            headers: { "X-Cron-Token": env.CRON_SECRET },
          }));
          if (!r.ok) console.error("scheduled jobs failed", r.status);
        }
      } catch (e) {
        console.error("scheduler error", e);
      }
    })());
  },
} satisfies ExportedHandler<Env>;
