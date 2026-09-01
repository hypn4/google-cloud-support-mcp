# cloud-support-mcp

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

```bash
uv sync
uv run cloud-support-mcp        # stdio
```

Register it with an MCP client:

```json
{
  "mcpServers": {
    "cloud-support": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/cloud-support-mcp", "cloud-support-mcp"],
      "env": {
        "CLOUD_SUPPORT_MCP_PARENTS": "[\"projects/my-project\",\"organizations/123456789\"]",
        "CLOUD_SUPPORT_MCP_QUOTA_PROJECT": "my-project"
      }
    }
  }
}
```

## Configuration

All variables take the `CLOUD_SUPPORT_MCP_` prefix.

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
organisation and a person acts on it. Set `CLOUD_SUPPORT_MCP_ENABLE_ESCALATION=true`
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

Integration tests are double-gated on purpose:

```bash
export CLOUD_SUPPORT_MCP_IT_PARENT=projects/my-test-project   # read-only tests
export CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1                    # also the writing ones
```

Writing tests always pass `test_case=True`, which keeps the case out of a support
engineer's queue, and a guard in `tests/integration/conftest.py` refuses any
`CreateCase` without that flag. Escalation is never exercised against the live
API.

### Not yet verified against the live API

Three checks need a project with a **paid support plan**, which the verification
project did not have. The code is written and covered by mock-based contract
tests; only the live confirmation is outstanding:

- attachment upload size limit and the media `uploadType` (T081)
- first-run time-to-first-query measurement (T083)
- the write walkthroughs, quickstart V4 and V5 (T085)

`specs/001-gcp-support-mcp/deferred.md` says what is blocked, what was already
confirmed live on 2026-09-01, and which files to touch when you finish each one.
Read it before picking any of them up — several non-obvious API behaviours are
recorded there and are easy to re-derive by accident.

Design documents live in `specs/001-gcp-support-mcp/`; project principles are in
`.specify/memory/constitution.md`.
