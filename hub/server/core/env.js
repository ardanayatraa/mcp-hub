import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { loadEnvFile } from "node:process";

// Read hub/.env when the server or a script starts from the hub directory. Variables
// already set in the environment win. `nuxt dev` loads the same file on its own.
export function loadLocalEnv() {
  const file = resolve(process.cwd(), ".env");
  if (existsSync(file)) loadEnvFile(file);
}
