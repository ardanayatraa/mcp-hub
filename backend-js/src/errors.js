export class HubSdkError extends Error {
  constructor(message, code = "HUB_ERROR", status = 0) {
    super(message);
    this.name = "HubSdkError";
    this.code = code;
    this.status = status;
  }
}
