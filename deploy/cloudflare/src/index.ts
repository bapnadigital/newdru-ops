/**
 * NEWDRU Ops on Cloudflare.
 *
 * mynewdru.in  ->  this Worker  ->  one always-warm container running the app.
 * Secrets live only in Cloudflare (set with `wrangler secret put`), never in GitHub.
 */
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  APP: DurableObjectNamespace<NewdruApp>;
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
  UNICOMMERCE_MODE?: string;
  UNICOMMERCE_TENANT?: string;
  UNICOMMERCE_USER?: string;
  UNICOMMERCE_PASSWORD?: string;
  UNICOMMERCE_FACILITIES?: string;
  CRON_SECRET?: string;
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
  "UNICOMMERCE_MODE", "UNICOMMERCE_TENANT", "UNICOMMERCE_USER", "UNICOMMERCE_PASSWORD",
  "UNICOMMERCE_FACILITIES", "CRON_SECRET", "GUPSHUP_MODE", "GUPSHUP_API_KEY", "GUPSHUP_APP_NAME", "GUPSHUP_SOURCE_NUMBER",
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
    return instance(env).fetch(request);
  },

  // Every 5 minutes: keep the app warm, check health, and let it run any
  // scheduled jobs that are due (Unicommerce stock every 30 min, orders hourly).
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext) {
    const app = instance(env);
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
