/** Fixed command arguments only; never place one-use codes in shell arguments. */
export function pairingCommand(address: string, replace = false): string {
  const url = new URL(address);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash
    || /[^A-Za-z0-9._~%:/\[\]-]/.test(url.href)) throw new Error("The Hub connection URL is invalid.");
  return "php artisan mcp-hub:connect --hub='" + url.href.replace(/\/$/, "") + "'" + (replace ? " --replace" : "");
}
