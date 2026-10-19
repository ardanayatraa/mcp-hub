// Unknown /api paths get the Hub's JSON error, not the admin UI page.
export default defineEventHandler((event) => {
  setResponseStatus(event, 404);
  return { success: false, error: { code: "HTTP_ERROR", message: "Request was rejected" } };
});
