// MCP Hub user guide: how admins set the Hub up and how people use it from an AI client.

import type { GuideMeta, GuideSection } from "@/docs/guide";

export const USER_GUIDE: GuideMeta = {
  badge: "User guide",
  title: "Using MCP Hub",
  summary: "Connect a business app once, decide what AI may see, and let AI clients answer questions, run reports and propose changes, while the app keeps its data and every request is checked.",
  meta: ["For Hub admins and AI client users", "Setup in about 15 minutes", "Updated October 2026"],
};

export const USER_SECTIONS: GuideSection[] = [
  {
    id: "overview",
    title: "How MCP Hub works",
    body: [
      "MCP Hub sits between AI clients and your business apps. An AI client asks through the Hub; the Hub checks the request and calls only the routes your app published; your app checks the user again and answers. The Hub never connects to the app's database and never stores its business records.",
    ],
    figure: "hub-flow",
    figureText: "An AI client calls the Hub with a client key (and a signed user token for a user's data). The Hub calls only the app's reviewed routes, with the app's bearer token. The app re-checks the user and keeps its data.",
    table: {
      head: ["In the Hub", "What it is"],
      rows: [
        ["App", "A connected application, such as a shop or a CRM, with the bearer token it issued for the Hub."],
        ["Data source", "One kind of record the app publishes, such as orders. Off until you allow it, with per-field visibility."],
        ["Tool", "Something an AI client can call: built-in tools that work on every data source, and tools you generate or create."],
        ["Skill", "A saved instruction, such as Weekly report, that AI clients show like a slash command."],
        ["Memory", "Off by default. When on, AI clients can remember preferences and notes for each signed-in user."],
        ["Chat", "Off by default. An AI chat window the app shows its users; the Hub runs the model with the app's tools."],
        ["Tool switch", "An on/off switch per tool and app. Off hides the tool from every client and the chat."],
        ["Client key", "Lets one AI client use one app's tools. Read access by default, write tools only when granted."],
      ],
    },
  },
  {
    id: "quick-start",
    title: "Quick start",
    body: ["The shortest path from nothing to an AI client answering a question. The step numbers match the sections below."],
    steps: [
      "Open **Apps → Connect app**, enter the app's name, key, base URL and bearer token, and save. The Hub tests the connection and reads the app's manifest. (Step 1)",
      "Allow the data sources AI may read, tick the tools AI clients may use, then activate the app. (Step 2)",
      "Open **Tools → Generate tools** to create the list, lookup and report tools in one go. (Step 3)",
      "Optional: tick ready-made skills on the app's **Skills** tab, and turn on memory on its **Memory** tab. (Steps 4 and 5)",
      "Create a client key on the app's **API keys** tab and copy it. It is shown once. (Step 6)",
      "Add the Hub to your AI client with that key and ask: \"What data can you use?\" (Step 7)",
    ],
  },
  {
    id: "connect",
    title: "Connect an app and store its bearer token",
    step: 1,
    body: [
      "The app must publish the Hub's small JSON contract: a health check, a capability manifest and the routes AI may use. For Laravel apps, the Laravel guide has every file. Then fill in the connect form:",
    ],
    table: {
      head: ["Field", "What to enter"],
      rows: [
        ["App name", "The name people know, for example Your App."],
        ["App key", "Lowercase id that matches `application` in the app's manifest, for example `your_app`. It cannot change later."],
        ["Base URL", "The app's address, for example `https://app.example.com`. The Hub calls only routes under it."],
        ["Environment", "Development, Test, Staging or Production. Production apps allow live tests only for public totals."],
        ["Bearer token", "The token the app issued for the Hub. The Hub sends it as `Authorization: Bearer <token>` on every call. Stored encrypted and never shown again."],
        ["Permission management", "Set up in Hub (you choose data sources and tools), or follow the app's own permissions automatically."],
        ["Advanced", "Manifest and health paths, timeout (100 to 30,000 ms), TLS check, and the user delegation secret. Leave the secret blank and the Hub generates one and shows it once."],
      ],
    },
    list: [
      "**Save and check** tests the connection, then syncs the manifest. A slow app shows a \"still waiting\" note, not a frozen screen.",
      "**Choose tools**, the wizard's last step, lists every tool by data source with a tick box. Reading tools are ticked; tools that create, update or delete start unticked, and where the app's API is read-only their boxes are greyed out with the reason. Unticked tools are switched off. Ticked write tools are tested with sample data (nothing is sent to the app) and published when you press **Activate app**.",
      "**API keys tab** on the app page is where the app's bearer token lives: see when it was last updated, paste a replacement (it is tested right away), change the delegation secret or test the saved token.",
      "**Edit** connection settings on the **Connection** tab. Changing the base URL or manifest path returns the app to setup, so test and sync again.",
      "**Pause** blocks every tool of the app at once. **Archive** revokes its bearer token and client keys. **Delete** removes it from the Hub after you type its key; audit history is kept.",
    ],
  },
  {
    id: "data",
    title: "Choose what AI may read",
    step: 2,
    body: [
      "Every data source starts off. On the app's **Data sources** tab, switch on Read for what AI may use. Create, Update and Delete appear only when the app published a route for them, and they work only through write tools and keys with write permission.",
      "Each field has a visibility level. Fields whose names look personal or secret (email, phone, password, token, ID numbers, `user_id`, `tenant_id` and similar) are always hidden and locked.",
    ],
    table: {
      head: ["Visibility", "What AI clients get"],
      rows: [
        ["Visible to AI", "The value can be returned, filtered, grouped and sorted."],
        ["Totals only", "Only sums and averages over groups of 3 or more records; the values themselves are never shown."],
        ["Hidden", "Never leaves the Hub. Fields the app did not list are hidden by default."],
      ],
    },
    after: [
      "You can make a field stricter than the app's own setting, or relax it back to that setting, never beyond.",
    ],
  },
  {
    id: "tools",
    title: "Give AI the tools",
    step: 3,
    body: [
      "Two built-in tools work on every allowed data source as soon as the app is active. Three memory tools appear when an app turns memory on. Custom tools give common questions a clear name and fixed settings.",
    ],
    table: {
      head: ["Tool", "What it does"],
      rows: [
        ["`list_data_sources`", "Lists the data sources the key may read, with field names and allowed operations. AI clients call it first."],
        ["`run_report`", "The main reporting tool: filters, up to 2 group-by fields, a day/week/month/year bucket and up to 6 metrics (count, sum, avg, min, max), with a one-line summary."],
        ["`recall_memory`, `save_memory`, `forget_memory`", "Per-user memory, when the app turned it on (step 5)."],
        ["Generated and custom tools", "Read records, saved reports, and create, update or delete requests on reviewed routes."],
      ],
    },
    list: [
      "**Generate tools** (Tools page) creates a tool for every route the app published on its allowed data sources: list and lookup tools, a summary report, and write requests. Read tools that pass a sample test are published; write tools stay drafts for you to review. Running it again adds only what is new.",
      "**New tool** builds one by hand from a template: Read records, Report, Create, Update or Delete.",
      "Every tool goes draft → test → live. A test runs the real pipeline on sample data (or live data in non-production apps) plus privacy checks. Editing a live tool takes it offline until it passes again.",
      "**All tools** (Tools page) lists every tool in one table: the Hub's own tools and each app's tools, with kind, status, calls in the last 7 days and the last test. Search, filter by app, kind or status, sort by any column and page through 10 to 100 rows at a time.",
      "**Capabilities** (Tools page) describes what this MCP can do right now: live tools by kind, reading, reports (filter operators, totals, time buckets and limits), create/update/delete with confirmation, skills, memory, AI chat, switches and safety limits, how AI clients connect, and what each app allows.",
      "**Report playground** previews `run_report` on an app without an AI client.",
      "**What the agent sees** shows the exact tools, inputs, skills and instructions an AI client gets for any app and client key.",
      "**Switches**: on the app's **Tools** tab every tool has an on/off switch, including the built-in and memory tools. Off hides the tool from every client key of that app and from the chat, refuses calls to it, and hides any skill that needs it. Use **All shown on / off** with the filters to switch many at once.",
    ],
  },
  {
    id: "skills",
    title: "Add skills",
    step: 4,
    body: [
      "A skill is a saved instruction that AI clients show like a slash command, for example `/periodic_report`. In MCP terms it is a prompt. Skills are text only: nothing runs on the Hub, and the AI uses tools the key may call anyway.",
    ],
    list: [
      "The app's **Skills** tab is a checklist: the five ready-made skills and the app's own. Tick one to offer it (a ready-made skill is added on the first tick), untick it to hide it. A box is greyed out when the skill needs a tool the app cannot offer, for example Personal briefing while memory is off.",
    ],
    steps: [
      "Open **Tools → Skills → New skill** (or **New skill** on the app's Skills tab) and pick the app.",
      "Start from a template (Data overview, Periodic report, Records needing attention, Explain a number or Personal briefing) or write your own.",
      "Write the instructions as the user's request. Use `{{name}}` where a value goes, and add an argument with that name (up to 5, each required or optional).",
      "Tick the tools the skill uses. A client key that cannot call all of them does not see the skill.",
      "Fill in sample values and press **Preview** to see the exact text the AI receives, then save.",
    ],
    files: [
      {
        path: "periodic-report-skill.txt",
        lang: "text",
        kind: "snippet",
        caption: "Example instructions with two arguments, source and period",
        code: "Prepare a report on {{source}} for {{period}}. Use run_report with a time_bucket on the main date field, the record count and the most relevant totals. Present a two-sentence summary, a small table of the main numbers and any notable changes. Say so if the data coverage is partial.",
      },
    ],
    after: [
      "Skills with personal data, credentials or text that tries to override the assistant's rules are refused. A skill whose tools are not live yet shows a warning and stays hidden from AI clients until they are.",
    ],
  },
  {
    id: "memory",
    title: "Turn on memory (optional)",
    step: 5,
    body: [
      "Memory lets AI clients remember preferences and short notes for each signed-in user, such as their language, currency or usual report period, and use them in later conversations. The model does not learn or retrain: it reads the saved notes at the start of a conversation.",
    ],
    steps: [
      "Open the app's **Memory** tab and switch memory on.",
      "Choose how long memories are kept (7, 30, 90, 180 or 365 days) and how many notes each user may keep (5 to 200; the oldest make room).",
      "If a client key is limited to selected tools, add `recall_memory`, `save_memory` and `forget_memory` to it on the **API keys** tab.",
    ],
    list: [
      "Memory belongs to the user named in the app's signed user token, never to a value the AI supplies. Each user sees only their own.",
      "It is encrypted in the Hub. Emails, phone numbers, ID numbers and credentials are refused.",
      "Admins see counts only (users, notes, preferences), never content. Backups never include memories.",
      "**Delete all memories** on the Memory tab removes everything users of that app saved; settings stay.",
    ],
  },
  {
    id: "app-chat",
    title: "Give the app its own AI chat (optional)",
    body: [
      "Instead of, or as well as, connecting AI clients, an app can show its users a chat window. The Hub runs the model with the app's tools, rules and switches; the app passes the signed-in user and shows the answers. Conversations stay in the user's browser and are never stored in the Hub.",
    ],
    steps: [
      "Make sure there is a model under **AI providers** (super admins): paste the Claude key on the **Claude** card, or **Add provider**, pick a preset such as OpenAI, OpenRouter, Groq, Gemini or Ollama, paste the key, and the Hub tests it and loads its models. Keys are stored encrypted and work without a restart.",
      "Model names are never typed: the Chat tab loads each provider's model list by itself (Claude's from Anthropic) and keeps it for a few hours. Use **Refresh list** after a provider adds models.",
      "Open the app's **Chat** tab and switch the chat on. Choose the provider and model (Claude Opus 5.5 by default; with other providers pick a model that supports tool calling), the effort, tool steps per answer and messages per user per day.",
      "Write instructions in your users' words, a welcome message and up to six suggested questions. The Hub's safety rules always apply on top.",
      "Check it with **Try it** on the same tab (read-only, without a signed-in app user).",
      "In the app, build the chat window your way. The app's server calls the Hub's chat API with a client key and the signed-in user, and streams the answer to the page. The **Laravel guide** under Docs (Add an AI chat) has the server route and a small browser helper.",
      "If the app runs its own chat and only borrows the Hub's models (the model gateway), use **Model gateway access** on the same tab: **Choose models** to allow only the ones it needs (all are open while the list is empty), set **Tokens per month** as a budget, and watch this month's calls and tokens per model there.",
    ],
    after: [
      "Skills show up in the chat as `/` commands. Changes the assistant prepares appear as cards the user confirms. Each answer and every tool call it made are recorded in **Activity** under one trace.",
    ],
  },
  {
    id: "keys",
    title: "Create a client key",
    step: 6,
    body: [
      "A client key lets one AI client use one app's tools. Create it on the app's **API keys** tab (or under **Access**). The key starts with `hub_` and is shown once: copy it before you close the dialog.",
    ],
    table: {
      head: ["Setting", "Effect"],
      rows: [
        ["Name", "Who uses it, for example Support assistant. Shown in the activity log."],
        ["Expires after", "30, 90, 180 or 365 days."],
        ["Allow write tools", "Lets the key call published create, update and delete tools. The app still checks the user and may ask for confirmation."],
        ["Only selected tools", "Limits the key to the tools you tick. Built-in and memory tools must be ticked too. On a read-only key, tools that create, update or delete are greyed out; tick Allow write tools first."],
      ],
    },
    after: [
      "Revoking a key stops every client that uses it immediately. Archiving an app revokes all of its keys.",
    ],
  },
  {
    id: "clients",
    title: "Connect an AI client",
    step: 7,
    body: [
      "Any MCP client that speaks Streamable HTTP can connect to the Hub's endpoint with a client key. Replace `hub_your_client_key` with your key.",
      "Most business data belongs to a user, so its routes need a signed user token (`X-Hub-Delegation`) that only your app can create, and that expires within two minutes. Desktop clients are ideal for trying the Hub and for public totals; for real users, connect through your app's own assistant (see the Laravel guide).",
    ],
    files: [
      {
        path: "terminal",
        lang: "bash",
        kind: "snippet",
        caption: "Claude Code: add the Hub for your user",
        code: String.raw`claude mcp add --transport http mcp-hub https://hub.example.com/mcp --header "Authorization: Bearer hub_your_client_key"`,
      },
      {
        path: ".mcp.json",
        lang: "json",
        kind: "file",
        caption: "Claude Code: share the Hub with a project (keep the key out of Git)",
        code: String.raw`{
  "mcpServers": {
    "mcp-hub": {
      "type": "http",
      "url": "https://hub.example.com/mcp",
      "headers": { "Authorization": "Bearer hub_your_client_key" }
    }
  }
}`,
      },
      {
        path: "~/.cursor/mcp.json",
        lang: "json",
        kind: "file",
        caption: "Cursor",
        code: String.raw`{
  "mcpServers": {
    "mcp-hub": {
      "url": "https://hub.example.com/mcp",
      "headers": { "Authorization": "Bearer hub_your_client_key" }
    }
  }
}`,
      },
      {
        path: "claude_desktop_config.json",
        lang: "json",
        kind: "file",
        caption: "Claude Desktop: mcp-remote (needs Node.js) bridges the desktop app to the Hub",
        code: String.raw`{
  "mcpServers": {
    "mcp-hub": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://hub.example.com/mcp", "--header", "Authorization:${"$"}{HUB_AUTH}"],
      "env": { "HUB_AUTH": "Bearer hub_your_client_key" }
    }
  }
}`,
      },
    ],
    after: [
      "The Hub accepts browser requests only from origins listed in `ALLOWED_ORIGINS`, and only for host names listed in `ALLOWED_HOSTS`. Desktop and server clients send no origin and are not affected by the first setting.",
    ],
  },
  {
    id: "chat",
    title: "Using it in chat",
    body: ["Ask in plain words. The AI picks the tools; every call is checked again and logged."],
    table: {
      head: ["You ask", "What the AI does"],
      rows: [
        ["What data can you use?", "Calls `list_data_sources` and describes each source."],
        ["How many orders per status this month?", "Calls `run_report` with a filter on the date, grouped by status, with a count."],
        ["Show the revenue trend by week since July.", "Calls `run_report` with a weekly time bucket and a sum."],
        ["Run /periodic_report for orders, last 7 days.", "Uses the skill's instructions with your values filled in."],
        ["From now on, reply in Indonesian and use IDR.", "Saves two preferences with `save_memory` when memory is on, and follows them next time."],
        ["Create a project called Harbor Office.", "Calls a create tool. The app returns a proposal; nothing changes until you confirm it in the app."],
      ],
    },
    list: [
      "When an answer says the data is partial, not every record was read (for example, a page limit was reached). Ask for a narrower question.",
      "Personal data is never sent to the AI, and inputs that contain it are refused. Enter such data in the app's own forms.",
      "Ask the AI to forget something and it calls `forget_memory`: one note, one preference or everything.",
    ],
  },
  {
    id: "monitor",
    title: "Monitoring",
    body: ["Three places show how the Hub is used and whether apps are healthy."],
    list: [
      "**Overview**: active apps, live tools, tool calls and response time, a chart of calls and unsuccessful calls over 24 hours, 7 or 30 days, each app's allowed data sources and the most used tools.",
      "**Activity**: every tool call, skill use and configuration change, with who, which app, the result and a trace id. Filter by kind, app, result and period, or search a tool or trace id.",
      "**App → History**: recent connection checks with response times, and every contract version the app published.",
    ],
  },
  {
    id: "troubleshooting",
    title: "Troubleshooting",
    body: ["Error codes appear in AI answers, in the Activity log and on the app page."],
    table: {
      head: ["You see", "Usual cause", "Fix"],
      rows: [
        ["The application rejected the bearer token", "The token saved in the Hub differs from the app's, or the app reads another header", "Paste the current token on the app's API keys tab (it is tested right away), and check that the app reads `Authorization: Bearer`."],
        ["Answered, but not with {\"status\": \"ok\"}", "The health route returned HTML, a redirect or a 404", "Check the health path on the Connection tab and the app's route list."],
        ["The AI sees no tools", "The app is paused or in setup, the data source is off, or the key's tool list excludes them", "Open What the agent sees for that key; it shows what is missing."],
        ["`PERMISSION_DENIED` on a user's data", "No valid signed user token: missing, expired, or signed with another secret", "Call through your app's assistant; keep the delegation secret the same in the app and the Hub."],
        ["`MODULE_DISABLED`", "The data source, or memory, is turned off", "Allow the data source, or switch memory on for the app."],
        ["`PII_DETECTED`", "The question contained an email, phone number or ID", "Ask without it; enter personal data in the app."],
        ["`CONFLICT`: run a passing test", "The tool changed, or the app's contract changed", "Test the tool again and publish it."],
        ["A skill is missing in the client", "One of its tools is not live, or the key may not call it", "The skill card names the tools; publish them or add them to the key."],
        ["`UNAUTHENTICATED`", "The client key expired or was revoked", "Create a new key and update the client."],
        ["The Overview chart says it needs a newer API", "The Hub server runs older code than the admin page", "Restart the Hub server after upgrading."],
      ],
    },
  },
  {
    id: "security",
    title: "Security and privacy",
    body: ["What the Hub guarantees, in short:"],
    list: [
      "The app keeps its data. The Hub stores configuration, encrypted credentials, an audit log of metadata and, only when turned on, encrypted user memories.",
      "Every call is authorized from scratch: client key, app status, data source, operation, field policy and the app's contract. The app re-checks the user.",
      "The user comes from a token the app signs, never from what the AI sends. Arguments such as `user_id`, `tenant_id` or `role` are rejected.",
      "Write tools only send requests the app reviewed, never retry them, and usually return a proposal for the user to confirm.",
      "Admins sign in with a password and, in production, a one-time code. Roles limit each admin to their apps.",
    ],
  },
  {
    id: "reference",
    title: "Reference",
    body: ["The details AI client builders and admins look up most."],
    table: {
      head: ["Item", "Value"],
      rows: [
        ["MCP endpoint", "The Hub's address followed by `/mcp`, Streamable HTTP. The Overview page shows it with a copy button."],
        ["Required header", "`Authorization: Bearer hub_…`"],
        ["User token header", "`X-Hub-Delegation`, signed by the app, valid up to 150 seconds"],
        ["Custom tool names", "The tool key with dots as double underscores, for example `your_app__orders__list`; apps outside dev get an environment suffix"],
        ["Skills", "Served through `prompts/list` and `prompts/get`"],
        ["Roles", "Super admin (everything, users and backups), App admin (assigned apps, tools and keys), Auditor (read-only)"],
        ["Light or dark", "The sun or moon button at the top switches the look. The account menu also offers **System**, which follows your computer. The choice is kept in this browser."],
        ["Deeper docs", "In the repository: `docs/TOOLS.md`, `docs/API.md`, `docs/SECURITY.md`, `docs/CONNECTOR_CONTRACT.md`"],
      ],
    },
  },
];
