export type HubActor = { tenantId: string; userRef: string };
export type HubEvent = { event: string; data: Record<string, unknown> };
export type HubRequestHeaders = Headers | Record<string, string> | Array<[string, string]>;

export class HubSdkError extends Error {
  code: string;
  status: number;
  constructor(message: string, code?: string, status?: number);
}

export function signDelegation(options: {
  appKey: string; tenantId: string; userRef: string; secret: string; ttlSeconds?: number;
}): string;

export function verifyAssertion(options: {
  token: string; appKey: string; audience: string; secret: string;
  consumeJti: (jti: string, exp: number) => Promise<boolean> | boolean;
}): Promise<HubActor>;

export class MemoryReplayStore {
  consume(jti: string, exp: number): Promise<boolean>;
}

export class HubSourceAuth<TActor = unknown> {
  constructor(options: {
    appKey: string; audience: string; bearerToken: string; delegationSecret: string;
    consumeJti: (jti: string, exp: number) => Promise<boolean> | boolean;
    authorize: (context: HubActor & { permission: string }) => Promise<{
      active: boolean; allowed: boolean; tenantId: string; actor: TActor;
    }> | { active: boolean; allowed: boolean; tenantId: string; actor: TActor };
  });
  verifyBearer(headers: HubRequestHeaders): void;
  authenticate(headers: HubRequestHeaders, permission: string): Promise<HubActor & { actor: TActor }>;
}

export class HubClient {
  constructor(options: {
    baseUrl: string; clientKey: string; appKey: string; delegationSecret: string;
    origin?: string; timeoutMs?: number; protocolVersion?: string; fetch?: typeof globalThis.fetch;
  });
  delegationFor(actor: HubActor): string;
  listTools(actor?: HubActor): Promise<Array<Record<string, unknown>>>;
  callTool(name: string, args?: Record<string, unknown>, actor?: HubActor): Promise<Record<string, unknown>>;
  listPrompts(actor?: HubActor): Promise<Array<Record<string, unknown>>>;
  getPrompt(name: string, args?: Record<string, unknown>, actor?: HubActor): Promise<Record<string, unknown>>;
  getChatConfig(): Promise<Record<string, unknown>>;
  chatTurn(request: Record<string, unknown>, actor?: HubActor): Promise<Record<string, unknown>>;
  streamChatTurn(request: Record<string, unknown>, actor?: HubActor): AsyncGenerator<HubEvent>;
}
