# google-cloud-support-mcp

An MCP server for Google Cloud Support. Read and act on support cases across
every project and organization you have access to, without leaving the
conversation.

## What it covers

Fourteen tools over the Cloud Support API v2 — cases, comments, attachments, and
problem classifications:

| Group | Tools |
|-------|-------|
| Cases (read) | `search_cases`, `get_case` |
| Cases (write) | `create_case`, `update_case`, `close_case`, `escalate_case` |
| Classifications | `search_case_classifications` |
| Comments | `list_comments`, `get_comment`, `add_comment` |
| Attachments | `list_attachments`, `get_attachment`, `download_attachment`, `upload_attachment` |

Plus a `case://{parent_type}/{parent_id}/{case_id}` resource template and two
prompts (`triage_open_cases`, `draft_case_from_incident`).

**Not covered**, deliberately:

- **`SupportEventSubscriptionService`** (7 RPCs) is out of scope — push delivery
  and subscription CRUD alike. See `specs/001-gcp-support-mcp/spec.md`
  Clarifications, 2026-09-01.
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
4. API enabled and credentials resolved:

   ```bash
   gcloud services enable cloudsupport.googleapis.com --project=PROJECT_ID
   gcloud auth application-default login
   gcloud auth application-default set-quota-project PROJECT_ID
   ```

## Install and run

Nothing to clone or install — `uvx` fetches the published package and runs it:

```bash
uvx google-cloud-support-mcp
```

Register it with an MCP client:

```json
{
  "mcpServers": {
    "google-cloud-support": {
      "command": "uvx",
      "args": ["google-cloud-support-mcp"],
      "env": {
        "GOOGLE_CLOUD_SUPPORT_MCP_PARENTS": "[\"projects/my-project\",\"organizations/123456789\"]",
        "GOOGLE_CLOUD_SUPPORT_MCP_QUOTA_PROJECT": "my-project"
      }
    }
  }
}
```

Pin a release with `uvx google-cloud-support-mcp@0.1.0` if you would rather not track
the latest.

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
      "args": ["run", "--directory", "/path/to/google-cloud-support-mcp", "google-cloud-support-mcp"],
      "env": {
        "GOOGLE_CLOUD_SUPPORT_MCP_PARENTS": "[\"projects/my-project\",\"organizations/123456789\"]",
        "GOOGLE_CLOUD_SUPPORT_MCP_QUOTA_PROJECT": "my-project"
      }
    }
  }
}
```

## Configuration

All variables take the `GOOGLE_CLOUD_SUPPORT_MCP_` prefix.

| Variable | Default | What it does |
|----------|---------|--------------|
| `PARENTS` | `[]` | Scopes to query, as a JSON list of `projects/{id}` / `organizations/{id}`. Validated at start-up. |
| `QUOTA_PROJECT` | — | Billing/quota project. Organization-level calls with user credentials generally need this. |
| `ENABLE_WRITES` | `true` | `false` leaves only the eight read tools. |
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

## Development

```bash
uv run pytest                  # unit + contract; integration is deselected
uv run ruff check . && uv run ruff format --check .
```

