// npm run migrate: create the Hub database, or upgrade one from an earlier revision.
import { loadConfig } from "../server/core/config.js";
import { HubDatabase } from "../server/core/database.js";
import { loadLocalEnv } from "../server/core/env.js";
import { migrateDatabase } from "../server/core/migrate.js";

loadLocalEnv();
const config = loadConfig();
const result = await migrateDatabase(config.databaseUrl);
const db = new HubDatabase(config.databaseUrl);
await db.assertCurrent();
await db.close();
console.log(JSON.stringify(result));
