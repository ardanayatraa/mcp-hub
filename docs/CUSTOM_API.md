# Custom API connections

Connect any HTTP API without changing it. You list the resources and read endpoints; the Hub
builds the same reviewed contract an application would publish, so field privacy, tool
switches, client-key scopes, rate limits and audit apply as usual. Version 1 is **read-only
(GET)**. Other methods are rejected when the list is saved.

## Connect

1. `POST /api/admin/v1/connectors` with `"connector_type": "custom_api"`, a `base_url`, and
   `"auth_type": "none"` (public API) or `"bearer"` plus a `secret`.
2. `PUT /api/admin/v1/connectors/{id}/custom-api` with the endpoint list below. Saving
   validates the list and builds the data sources and tools immediately.
3. `POST .../test` calls the first saved endpoint that needs no input, then `POST .../activate`.

Editing the list later (same `PUT`) updates the tools. Nothing is redeployed.

## Endpoint list

```json
{
  "resources": {
    "product": {
      "name": "Products",
      "alias": ["produk", "menu"],
      "fields": {
        "id": "integer",
        "title": "string",
        "price": "number",
        "description": { "type": "string", "maxLength": 1000 },
        "discount": "number?"
      },
      "endpoints": [
        { "name": "cari_produk", "path": "/products/search", "params": { "q": "string", "limit": "integer" },
          "required": ["q"], "result_path": "products" },
        { "name": "detail_produk", "path": "/products/{id}" }
      ]
    }
  }
}
```

- **Resource key and endpoint `name`**: lowercase words, digits, underscores. The tool is
  named `<app_key>__<resource>__<name>`, for example `dummy__product__cari_produk`.
- **`fields`** is the allowlist: only these fields reach the AI, whatever else the API returns.
  Types are `string`, `integer`, `number`, `boolean`; add `?` to allow `null`. Strings are capped
  at 200 characters unless `maxLength` (up to 2000) is set. Sensitive names (email, password,
  token and similar) are blocked by the Hub's field policy even when listed.
- **`params`** become the tool's arguments. `{id}` in the path is added as a required argument.
  List a param in `required` to make it mandatory.
- **`result_path`** is where the records sit in the response (`products`, or `data.items`).
  Leave it out when the response itself is the record or the list. A single object becomes one row.
- **`alias`** words are added to the tool description so AI and chat can map everyday words to the resource.

## The editor, headers and the test request

The **Endpoints** tab opens in **Simple** mode: one card per endpoint. Type a name and the address, click
**Send**, and the fields found in the answer appear as chips to tick (sensitive-looking ones are locked). Parameters,
headers and where the records sit are under *More options*. **Advanced** groups several endpoints under one resource
with shared fields, and **JSON** edits the saved list directly. Per endpoint you set the path, where the
records sit, parameters (type, required, a test value) and fixed headers. **Send** calls the API as this
connection and shows the status, the time, the records it found and the fields with their types; one click
fills in the result path and the fields. Sensitive-looking fields are listed but never offered to AI, and
the sample is masked.

- **Headers** on an endpoint are fixed and not secret (for example `Accept-Language`). Names the Hub controls
  (`Authorization`, `Cookie`, `Host`, `X-Hub-*` and similar) are refused.
- **API key:** when connecting, choose *API key in a header* and name the header (`X-API-Key`); the key is stored
  encrypted with the connection and sent on every call. *Bearer token* and *nothing* are the other choices.
- Only reading (GET) is supported.

## Data per user (`user_auth`)

Add `user_auth` when each user should see only their own data. Two ways, no login API needed for the first:

```json
"user_auth": {}                                    // the page hands over the token its user already has
"user_auth": { "login_path": "/api/login", "fields": ["email", "password"], "token_path": "token" }
```

Either way every call carries the user's own bearer token instead of the connection's, and the API decides what
each user sees. Such a connection never calls the app without a signed-in user. `me_path` / `name_path` are optional
in both. See [Embedded chat](EMBED.md).

## What the Hub does for you

- Sends no credentials when `auth_type` is `none`, and never sends the bearer token anywhere
  except to this `base_url`.
- Treats the data as not tied to a signed-in user, so no delegation or tenant filter applies.
  Use this only for APIs whose data is meant to be read by everyone who can use the connection.
- States the dataset metadata itself (time, scope, `partial` coverage when the API reports a
  larger `total` than it returned).
- Keeps all existing protections: SSRF guard and approved hosts, no redirects, response size
  and record limits, output schema validation, and the privacy scan on arguments.
