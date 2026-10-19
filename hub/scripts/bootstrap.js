// npm run bootstrap: create the first super admin from ADMIN_INITIAL_EMAIL and ADMIN_INITIAL_PASSWORD.
import { seedAdmin } from "../server/core/bootstrap.js";
import { loadConfig } from "../server/core/config.js";
import { HubDatabase } from "../server/core/database.js";
import { loadLocalEnv } from "../server/core/env.js";
import { HubError } from "../server/core/errors.js";

loadLocalEnv();
const db = new HubDatabase(loadConfig().databaseUrl);
try {
  await db.assertCurrent();
  console.log(await seedAdmin(db));
} catch (error) {
  if (!(error instanceof HubError)) throw error;
  console.error(error.message);
  process.exitCode = 1;
} finally {
  await db.close();
}
