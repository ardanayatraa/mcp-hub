import { hash as hashPassword } from "argon2";
import { HubError } from "./errors.js";
import { id } from "./admin-common.js";
import { iso, passwordIsAcceptable } from "./security.js";

// Create the first super admin from ADMIN_INITIAL_EMAIL and ADMIN_INITIAL_PASSWORD.
export async function seedAdmin(db, env = process.env) {
  const email = (env.ADMIN_INITIAL_EMAIL || "admin@localhost").trim().toLowerCase();
  if (await db.one("SELECT id FROM admin_users WHERE email = ?", [email])) return "admin already exists";
  const password = env.ADMIN_INITIAL_PASSWORD ?? "";
  if (!passwordIsAcceptable(password)) {
    throw new HubError("ADMIN_INITIAL_PASSWORD must be at least 12 characters and include upper, lower, and a digit",
      "UNSAFE_CONFIGURATION", 500);
  }
  await db.run(`INSERT INTO admin_users (id, email, password_hash, role, mfa_enabled, is_active, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)`, [id(), email, await hashPassword(password), "super_admin", false, true, iso()]);
  return "admin created";
}
