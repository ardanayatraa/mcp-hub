// Liveness only: answers without the database. /ready checks the database.
export default defineEventHandler((event) => {
  setResponseHeader(event, "Cache-Control", "no-store");
  return { status: "ok" };
});
