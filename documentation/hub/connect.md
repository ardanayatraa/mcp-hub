# Connect an application

Choose an app key, environment, source URL, and resource policy owner before creating the connection. Review identity or URL changes because these values are bound to credentials and references.

## Pair a Laravel application

1. Register the application or connector in the Hub with the correct source URL.
2. Create an enrollment code as an administrator with access to that application.
3. Run [pairing from Laravel](../laravel/connection.md).
4. Confirm that the Hub validates the source health and capability manifest.
5. Check the active status, grants, and associated client key.

Pairing issues read-only credentials. Replacement preserves restrictions and does not add write access.

## Permission management modes

| Mode | Configuration owner | Workflow |
|---|---|---|
| `source_managed` | Source application | Manifest follows application grants; refresh failures deny access |
| `http_contract` | Hub operator | Test connector, discover, review modules, test tools, publish |

A source-managed manifest must declare `managed_by: application`. An explicit `modules: []` revokes all generated source tools. Profiles and keys can still narrow access further.

## Non-Laravel sources

Implement health, manifest, and operation endpoints using the [connector contract](../reference/connector-contract.md). The service credential proves the Hub can contact the application; the assertion proves the user context. Endpoints and methods come from the manifest, never model arguments.

## Connection lifecycle

**Test** checks authentication and reachability. **Discover/sync** validates the contract. **Activate** enables the connector. **Pause** blocks calls while retaining metadata. **Revoke/archive** removes access within the action's scope.

Renewal preserves the installation identity. Replacement revokes the old installation's credentials and issues a single-use code for its successor. See the [enrollment API](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/CONNECTOR_ENROLLMENT.md) for expiry and recovery behavior.
