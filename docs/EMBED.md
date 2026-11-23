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
   pick a title and colour, and copy the snippet. The Setup list at the top of the tab shows what is still
   missing.
5. **What the chat may use** (Embed tab): every tool of the app by default, or only the endpoints you tick.
   Tools that change data are never offered. **Register or edit endpoints** opens the endpoint list right there,
   so a developer can add an endpoint and allow it for the chat without leaving the tab. A developer only needs a
   Hub account with the **App admin** role for that app (Access → Team).

## No login API: use the token the page already has

The simplest setup needs nothing new from the app. The page the chat sits on is already signed in, so it hands
the chat the token its user already has, and the app only has to accept that token on the read routes you listed.

In the endpoint list, tick *Each user signs in with their own account* and choose **The page hands over the token
its user already has**. That is `"user_auth": {}` in JSON. Then put the token on the snippet:

```html
<!-- a server-rendered page: print the signed-in user's token -->
<script src="https://YOUR-HUB/api/embed/v1/embed.js" data-widget="w_..." data-token="{{ $userToken }}" async></script>
```

```js
// a single-page app that already holds the user's token (and renews it)
HubChat.setToken(auth.token);                       // whenever it changes
HubChat.getToken = () => auth.refresh();            // optional: the chat asks when the app says it expired
```

- The token reaches the widget in the iframe's URL fragment, which no server ever receives. The Hub stores it
  encrypted and sends it as `Authorization: Bearer …` to the routes you registered, nothing else. The chat is
  read-only whoever is signed in.
- `me_path` is optional: with it the Hub asks the app whose token this is (and shows the name); without it a wrong
  token simply fails when the chat reads, and the chat asks the page for a new one. The same token is never retried.
- If the user signs out of the page and another signs in, the new token replaces the old chat session.
- If the app answers 401 to the user's token while chatting, that chat session ends at once and the page has to
  hand over a fresh token.
- Use a short-lived token. If the page has no token (a cookie-session site), have its server create a read-only
  one for the session, for example Laravel Sanctum `$user->createToken('chat', ['read'], now()->addHours(12))`,
  and revoke it on logout. That is one line, not a login API.
- Show the chat only on pages where the user is signed in.

## Or let the chat ask for email and password

Choose *The chat asks for email and password* and give the app's login path. The Hub posts the form, keeps the
token that comes back and uses it the same way. This suits an app whose login API already exists.

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
