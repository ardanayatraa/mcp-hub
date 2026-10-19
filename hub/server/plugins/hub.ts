// Open the database at startup so a missing migration shows in the log right away.
export default defineNitroPlugin((nitroApp) => {
  useHub().catch(logHubError);
  nitroApp.hooks.hook("close", closeHub);
});
