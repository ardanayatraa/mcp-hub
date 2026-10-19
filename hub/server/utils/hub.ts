import type { IncomingMessage, ServerResponse } from "node:http";
import type { H3Event } from "h3";

import { seedAdmin } from "../core/bootstrap.js";
import { loadConfig } from "../core/config.js";
import { HubDatabase } from "../core/database.js";
import { loadLocalEnv } from "../core/env.js";
import { createHubHandler } from "../core/handler.js";
import { migrateDatabase } from "../core/migrate.js";

interface Hub {
  db: HubDatabase;
  handle: (request: IncomingMessage, response: ServerResponse) => Promise<void>;
}

let starting: Promise<Hub> | undefined;

async function start(): Promise<Hub> {
  loadLocalEnv();
  const config = loadConfig();
  // Containers set HUB_AUTO_MIGRATE=true, like the Python image runs alembic and bootstrap on start.
  const auto = process.env.HUB_AUTO_MIGRATE === "true";
  if (auto) console.log(JSON.stringify({ event: "hub_migrate", ...(await migrateDatabase(config.databaseUrl)) }));
  const db = new HubDatabase(config.databaseUrl);
  try {
    await db.assertCurrent();
    if (auto) console.log(JSON.stringify({ event: "hub_bootstrap", result: await seedAdmin(db) }));
  } catch (error) {
    await db.close();
    throw error;
  }
  return { db, handle: createHubHandler({ db, config }) };
}

// The Hub opens its database on first use. A failed start is retried on the next request,
// so `npm run migrate` fixes an outdated schema without a restart.
export function useHub(): Promise<Hub> {
  starting ??= start().catch((error) => {
    starting = undefined;
    throw error;
  });
  return starting;
}

export async function closeHub() {
  const hub = await starting?.catch(() => undefined);
  starting = undefined;
  await hub?.db.close();
}

export function logHubError(error: unknown) {
  console.error(JSON.stringify({ event: "hub_not_ready", message: error instanceof Error ? error.message : String(error) }));
}

// Hand the request to the Hub's Node handler, which writes the response itself.
export async function serveHub(event: H3Event) {
  let hub: Hub;
  try {
    hub = await useHub();
  } catch (error) {
    logHubError(error);
    setResponseStatus(event, 503);
    setResponseHeader(event, "Cache-Control", "no-store");
    return { success: false, error: { code: "NOT_READY", message: "The Hub is not ready. See the server log." } };
  }
  await hub.handle(event.node.req, event.node.res);
}
