# google-cloud-support-mcp

An MCP server for Google Cloud Support. Read and act on support cases across
every project and organization you have access to, without leaving the
conversation.

> **This is not an official Google product.** It is an independent project, not
> affiliated with, endorsed by, or supported by Google. It talks to the public
> [Cloud Support API](https://cloud.google.com/support/docs/reference/rest) using
> your own credentials. Google Cloud and Google are trademarks of Google LLC.

## What it covers

Fifteen tools over the Cloud Support API v2 — cases, comments, attachments, and
problem classifications, plus scope discovery. Fourteen are exposed by default;
`escalate_case` stays hidden until you turn it on, so `fastmcp inspect` reporting
14 is correct, not a missing tool:

| Group | Tools |
|-------|-------|
| Scopes | `list_scopes` |
| Cases (read) | `search_cases`, `get_case` |
| Cases (write) | `create_case`, `update_case`, `close_case`, `escalate_case` |
| Classifications | `search_case_classifications` |
| Comments | `list_comments`, `get_comment`, `add_comment` |
| Attachments | `list_attachments`, `get_attachment`, `download_attachment`, `upload_attachment` |

Plus a `case://{parent_type}/{parent_id}/{case_id}` resource template and two
prompts (`triage_open_cases`, `draft_case_from_incident`).

Scopes are named in the conversation, not configured in advance. "List the open
cases in my-billing-project" works with nothing set up; `list_scopes` turns a name
you know into the identifier the API wants, which matters most for organizations —
they are addressed by a number nobody remembers.

**Not covered**, deliberately:

- **`SupportEventSubscriptionService`** (7 RPCs) — push delivery and
  subscription CRUD alike.
- **`v2beta`**, including `FeedService.ShowFeed`. The one thing v2beta looked
  like it offered — cross-organization search — turned out not to exist: its
  query grammar's `OR` combines values within a field, never scope identifiers.

## Prerequisites

1. Python 3.14+ and [uv](https://docs.astral.sh/uv/)
2. A **paid support plan** (Standard, Enhanced, or Premium) on the target
   project or organization. The Cloud Support API is unavailable without one,
   and that failure is reported separately from a permissions failure.
3. IAM: `roles/cloudsupport.techSupportViewer` to read,
   `roles/cloudsupport.techSupportEditor` to write. Organization-level scopes
   also need `resourcemanager.organizations.get`.
4. **For `list_scopes` only** — the Cloud Resource Manager API enabled, plus
   `resourcemanager.projects.get` and, to see organizations,
   `resourcemanager.organizations.get`. Nothing else needs it, and holding one
   permission and not the other is fine: the class you cannot read is reported
   and the other still answers.

   ```bash
   gcloud services enable cloudresourcemanager.googleapis.com --project=PROJECT_ID
   ```

5. API enabled and credentials resolved:

   ```bash
   gcloud services enable cloudsupport.googleapis.com --project=PROJECT_ID
   gcloud auth application-default login
   gcloud auth application-default set-quota-project PROJECT_ID
   ```

## Install and run

Nothing to clone or install — `uvx` fetches the published package and runs it.

**Register it with an MCP client (recommended).** This is how you actually use
the server: run by hand it just sits on stdio waiting for a client to speak to
it.

Claude Code:

```bash
claude mcp add google-cloud-support -- uvx google-cloud-support-mcp
```

Or, for any client that takes JSON:

```json
{
  "mcpServers": {
    "google-cloud-support": {
      "command": "uvx",
      "args": ["google-cloud-support-mcp"]
    }
  }
}
```

That is the whole configuration. **No environment variables are required** —
scopes are named in the conversation, not set up in advance, and everything in
[Configuration](#configuration) is optional.

To check it starts before registering, run `uvx google-cloud-support-mcp`; it
will wait on stdio, which is what a working server does. Pin a release with
`uvx google-cloud-support-mcp@0.2.1` if you would rather not track the latest.

### From a clone

```bash
uv sync
uv run google-cloud-support-mcp        # stdio
uv run fastmcp inspect                 # tool surface, without starting a session
```

`fastmcp.json` points the FastMCP CLI at `server.py:create_server`, so `inspect`,
`run` and `dev` all work with no arguments.

```json
{
  "mcpServers": {
    "google-cloud-support": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/google-cloud-support-mcp", "google-cloud-support-mcp"]
    }
  }
}
```

## Examples

Registered and authenticated, you can just ask. No scope needs configuring first.

### Catching up

> "Which support cases are open in my-billing-project?"

> "Show me case 12345678 and what Google last said on it."

> "Anything touched in the last three days across my-billing-project and organizations/123456789?"

`search_cases` narrows by state, priority or time and queries every scope you
name at once; `list_comments` marks each message with `author_side`, so you can
see who said what. "Touched" is deliberate — see the note below.

### When you only know a scope by name

> "What is the org id for Acme? List its P1 and P2 cases."

`list_scopes` turns the name into the number nobody remembers, then
`search_cases` uses it. This is the one thing here that needs the Cloud Resource
Manager API from [Prerequisites](#prerequisites) step 4.

### Anything that reaches Google

> "Reply on case 12345678 that we rotated the key."

> "Open a P3 case about slow Cloud SQL reads in my-billing-project."

You are shown the exact payload first, and nothing is sent until you approve it.
Opening a case needs a problem classification, so `search_case_classifications`
runs first to find a valid id.

One thing to know: `updated_after` filters on **update time** — *touched* since
then, not *opened* since then. A case opened months ago and commented on
yesterday matches. The v2 query grammar has no `create_time` filter at all.

## Configuration

All variables take the `GOOGLE_CLOUD_SUPPORT_MCP_` prefix. None are required;
set one by adding an `env` block to the client entry above, or by exporting it
into the server's environment.

| Variable | Default | What it does |
|----------|---------|--------------|
| `PARENTS` | `[]` | **Optional default.** Used only when a request names no scope. You can name a project or organization in the conversation instead — `list_scopes` finds the identifier. Validated at start-up. |
| `QUOTA_PROJECT` | — | Billing/quota project. Organization-level calls with user credentials generally need this. |
| `ENABLE_WRITES` | `true` | `false` leaves only the nine read tools. |
| `ENABLE_ESCALATION` | **`false`** | Escalation is hidden unless you turn it on. See below. |
| `DOWNLOAD_DIR` | system temp | Where `download_attachment` writes files. |
| `MAX_UPLOAD_BYTES` | `10000000` | Client-side check before an upload is offered. |
| `DEFAULT_PAGE_SIZE` | `20` | Kept small so list results do not swamp the conversation. |
| `FANOUT_CONCURRENCY` | `5` | Parallel scopes per query; lower it if you hit rate limits. |

## Two things worth knowing

**Nothing reaches Google without your confirmation.** Every outward-facing action
shows you the exact payload and waits. Declining sends nothing. The approved
payload is sealed by the framework between rounds, so what executes is
byte-for-byte what you were shown — a `confirm: true` parameter could not do
this, because the model would be the one filling it in.

**Escalation is off by default.** It is delivered to Google's support
organisation and a person acts on it. Set `GOOGLE_CLOUD_SUPPORT_MCP_ENABLE_ESCALATION=true`
to expose the tool; it still requires a written justification and your
confirmation.

## Cross-organization queries

`search_cases` queries every configured scope in parallel and merges the results.
A scope that fails does not fail the call — it appears in `scopes_failed` with
what to do about it, so one organization's permission error never hides another
organization's cases. Pagination uses a composite cursor that carries a token per
scope; changing `parents` mid-pagination is rejected rather than silently skewing
the results.

## Known limitations

**Attachment upload limits are unverified.** `MAX_UPLOAD_BYTES` defaults to 10 MB, which is a
placeholder rather than a measured ceiling — the API does not document one, and no live upload
has been run against a project with a paid support plan. The limit may be higher or lower than
the real one, and the transfer form is an informed reading of the media reference rather than
a confirmed protocol.

**A mistyped scope reports the wrong thing.** Name a project that does not exist and the answer
says the service is temporarily unreachable and suggests retrying. Retrying will not help: the
upstream API returns a bare HTTP 500 for a nonexistent project, and a 500 carries nothing that
separates a typo from a real outage — so reclassifying it would mislabel genuine outages
instead. The scope still appears in `scopes_failed` rather than silently returning "no cases".

[TODO.md](./TODO.md) has the full list and what would unblock each item.

## Development

```bash
uv run pytest                  # unit + contract; integration is deselected
uv run ruff check . && uv run ruff format --check .
uv run fastmcp inspect         # the server must load through the FastMCP CLI
```
