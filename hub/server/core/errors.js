export class HubError extends Error {
  constructor(message, code = "HUB_ERROR", status = 0) {
    super(message);
    this.name = "HubError";
    this.code = code;
    this.status = status;
  }
}
