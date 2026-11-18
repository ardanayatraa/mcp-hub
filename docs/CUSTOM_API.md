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

## What the Hub does for you

- Sends no credentials when `auth_type` is `none`, and never sends the bearer token anywhere
  except to this `base_url`.
- Treats the data as not tied to a signed-in user, so no delegation or tenant filter applies.
  Use this only for APIs whose data is meant to be read by everyone who can use the connection.
- States the dataset metadata itself (time, scope, `partial` coverage when the API reports a
  larger `total` than it returned).
- Keeps all existing protections: SSRF guard and approved hosts, no redirects, response size
  and record limits, output schema validation, and the privacy scan on arguments.
