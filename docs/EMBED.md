# Embedded chat

Put an app's AI chat on any website with one line of HTML. Visitors sign in with their account
**in the app**, and the assistant reads only what the app lets that user see. It never changes data.

```html
<script src="https://YOUR-HUB/api/embed/v1/embed.js" data-widget="w_..." async></script>
```

## How it works

```
Website (any)                 MCP Hub                                   Your app (its own API)
─────────────                 ───────────────────────────────────       ──────────────────────
snippet → chat button   →     widget page (iframe, Hub origin)
                              1. sign-in form ───────────────────────→  POST /api/login → token
                              2. stores the token encrypted
                              3. chat turn: model + tools ───────────→  GET /api/... with
                                                                         Authorization: Bearer <user token>
```

- The widget runs in an iframe served by the Hub, so the host page's scripts cannot read the sign-in
  form or the session. The page may only be framed by the sites you list (CSP `frame-ancestors`).
- The Hub keeps each user's app token **encrypted**, plus the display name the app returns. Passwords
  are never stored. The widget holds only a random session id.
- Every call carries that user's own token, so the app's own permissions decide what comes back.
- Embedded chats are read-only, whoever is signed in. Rate and daily limits count per user.

## Set it up

1. **Connect the app as a Custom API** (Apps → Connect an app → Custom API) and list its read
   endpoints. Add `user_auth` so users sign in with their own account:

   ```json
   {
     "user_auth": { "login_path": "/api/login", "fields": ["email", "password"],
                    "token_path": "token", "me_path": "/api/me", "name_path": "name" },
     "resources": {
       "order": { "name": "My orders", "fields": { "order_number": "string", "status": "string", "total": "integer" },
                  "endpoints": [ { "name": "my_orders", "path": "/api/my/orders", "result_path": "data" } ] }
     }
   }
   ```

   The app needs an API that returns a bearer token from a login request (Laravel Sanctum
   `createToken`, for example) and read routes guarded by that token. `me_path` is optional and only
   supplies the name shown in the widget and to admins.

2. **Test and activate the app.** A protected endpoint answering 401 without a user counts as reachable.
3. **Turn the chat on** in the Chat tab. Its model, instructions, welcome message and suggestions are used.
4. **Embed tab:** turn it on, list the websites that may show it (`https://www.example.com`, one per line),
   pick a title and colour, and copy the snippet.

## Already signed in on the host page

Show the chat only on pages where the user is signed in, and let the host page sign them in to the chat:
its server creates a short-lived, read-only token for the signed-in user and puts it on the snippet.

```html
<script src="https://YOUR-HUB/api/embed/v1/embed.js" data-widget="w_..." data-token="USER-APP-TOKEN" async></script>
```

- The widget gets the token in the iframe's URL fragment, which no server ever receives. The Hub asks the
  app (`me_path`) whose token it is before using it, so only a token the app itself accepts opens a chat,
  and that chat can only read that user's data. `me_path` is required for this.
- If the user signs out of the host and another signs in, the new token replaces the old chat session.
- Without `data-token` the chat shows its own sign-in form, as before.
- Keep the token short-lived (hours), read-only, and revoke it when the user signs out of the host.

## Chat Agent

**Chat Agent** in the menu shows any embedded chat as its users see it:

- **A new visitor:** sign in with a test account, exactly like a user.
- **A signed-in user:** pick a name to see their view. This preview is read-only, lasts 30 minutes,
  needs an admin who may change the app, and is recorded in Activity as that admin.

## Security notes

- The sign-in endpoint is limited per visitor address; the app should rate-limit its own login too.
- **Change id** in the Embed tab stops an old snippet. **Sign out** (one user or everyone) revokes stored tokens.
- On a server whose front proxy adds `X-Frame-Options: DENY` to every response, give the widget page
  its own location so the backend's CSP applies, as in `infra/nginx.conf`:

  ```nginx
  location ~ ^/api/embed/v1/w/[^/]+$ {
      proxy_pass $backend;
      add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header Referrer-Policy "no-referrer" always;
  }
  ```
