import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { loadEnvFile } from "node:process";
import { fileURLToPath } from "node:url";

export function loadLocalEnv() {
  const file = resolve(dirname(fileURLToPath(import.meta.url)), "..", ".env");
  if (existsSync(file)) loadEnvFile(file);
}
