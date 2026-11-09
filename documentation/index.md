---
hide:
  - toc
---
<div class="hero" markdown>
<p class="eyebrow">Developer documentation</p>

# Connect AI to your apps.<br>Keep your data under your control.

Build AI integrations that respect user permissions, tenant boundaries, and application business rules. MCP Hub manages connections and tools; the Laravel package enforces access within your application.

[Get started](start/quickstart.md){ .md-button .md-button--primary }
[Install Laravel 1.0](laravel/install.md){ .md-button }

<p class="meta">Laravel package 1.0.1 stable · Hub Python edition · Reviewed November 9, 2026</p>
</div>

## Choose your path

<div class="doc-cards" markdown>
<div class="doc-card" markdown>
<span class="label">For platform administrators</span>

## MCP Hub

Run the Hub, connect applications, configure client keys and tools, and manage model access in one place.

[Set up the Hub →](hub/local.md)
</div>
<div class="doc-card" markdown>
<span class="label">For application developers</span>

## Laravel MCP Hub

Install the Composer package, register reviewed resources, and apply your application's own user identity and permission rules.

[Integrate Laravel →](laravel/install.md)
</div>
</div>

## How the components work together

<div class="flow" role="img" aria-label="An AI client calls the Hub, which forwards a verified request to the Laravel application">
<div class="node"><strong>AI client</strong><small>MCP client or application chat</small></div>
<div class="arrow" aria-hidden="true">→</div>
<div class="node"><strong>MCP Hub</strong><small>Tools, keys, profiles, models, audit</small></div>
<div class="arrow" aria-hidden="true">→</div>
<div class="node"><strong>Laravel application</strong><small>Identity, policies, records, approval</small></div>
</div>

The Hub checks access on every call. The application rechecks the user and record scope before returning data or making changes. The model cannot establish user identity, tenant membership, source URLs, or transaction approval.

| Goal | Guide |
|---|---|
| Understand component responsibilities | [Concepts and architecture](start/concepts.md) |
| Connect your first application | [Laravel pairing](laravel/connection.md) |
| Expose a limited set of data | [Resources and permissions](laravel/resources.md) |
| Make changes with user approval | [CRUD proposals](laravel/commands.md) |
| Generate private reports | [CSV, XLSX, and PDF exports](laravel/exports.md) |
| Diagnose a failed connection | [Troubleshooting](help/troubleshooting.md) |

[Hub repository](https://github.com/ardanayatraa/mcp-hub) · [Laravel repository](https://github.com/ardanayatraa/laravel-mcp-hub) · [Composer package](https://packagist.org/packages/ardanayatraa/laravel-mcp-hub)
