// Open the database at startup so a missing migration shows in the log right away.
export default defineNitroPlugin((nitroApp) => {
  useHub().catch((error) => {
    logHubError(error);
    // As in the Python edition, production refuses to run with an unsafe configuration.
    if (error?.code === "UNSAFE_CONFIGURATION" && process.env.ENVIRONMENT === "production") process.exit(1);
  });
  nitroApp.hooks.hook("close", closeHub);
});
