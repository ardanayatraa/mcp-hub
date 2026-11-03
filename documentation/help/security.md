# Security and trust boundaries

Effective permissions are the intersection of several layers. Knowing an endpoint or opaque reference does not grant record access.

## Identity

A service credential authenticates the server-to-server connection. A client key restricts the application, tools, profile, and write scope. Delegation establishes the actor from a trusted server; a single-use assertion binds the Hub request to the source. The host resolver and policies recheck the active account, tenant, records, and current permissions.

Laravel 1.0 uses SQL uniqueness to reject replay across workers and cache resets. Missing security metadata causes readiness to fail closed. Do not add a local-cache fallback to bypass this failure.

## Secrets and data

Provider keys stay in the Hub. Connection credentials and private payloads are encrypted. Keys, pairing codes, APP_KEY, database URLs, and private reports must never enter Git, browser HTML, URL queries, logs, or public documentation.

Sensitive fields and model-supplied identity or routing arguments are rejected. Allowlists and policies still require review: automated PII detection does not replace application data classification.

## Networking and approval

Use egress allowlists, reviewed endpoints, size and time limits, HTTPS, and specific origins and hosts. HTTP reachability does not prove actor authentication.

Transaction approval takes place within an application session belonging to the proposal's actor. Report files remain private, encrypted, expiring, and rechecked on download. References and URLs are not bearer grants.

## Reporting vulnerabilities

Use GitHub private vulnerability reporting when available. Otherwise, request a private channel without posting exploits, credentials, or personal data in a public issue.

[Package security policy](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/SECURITY.md) · [Hub security model](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/SECURITY.md)

Audit host dependencies. Compatibility with older PHP or Laravel versions does not extend upstream security maintenance.
