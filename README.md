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

### Releasing

Two workflows live in `.github/workflows/`. `ci.yml` lints and tests every push
and pull request. `release.yml` fires **only on a tag you push yourself** —
nothing publishes from an ordinary push to `main`.

```bash
git tag v0.1.1
git push origin v0.1.1
```

That is the whole release. **The version is derived from the tag** — `pyproject.toml`
declares `dynamic = ["version"]` and hatchling reads git, so there is no version
string anywhere to bump or to drift out of sync. A build off a tag is `0.1.1`; a
build one commit later is `0.1.1.post1.dev0+abc1234`, which PyPI refuses, so an
accidental release from the wrong commit cannot reach the index.

The pipeline runs lint and tests, builds the sdist and wheel, asserts the built
version really is the tag (a checkout that cannot see the tag would quietly
produce `0.0.0`), checks the wheel actually exposes the `google-cloud-support-mcp`
console script (otherwise `uvx` would break for everyone), publishes to PyPI, and
creates a GitHub release with the artifacts attached.

#### When a release fails

Every step fails loudly. Most of them also stop the steps after them — a failed
PyPI upload means no GitHub release is created, so a tag never points at
something that was not published.

Changelog generation is the one exception, and it is deferred rather than
swallowed. git-cliff crashes instead of degrading when the GitHub API is
unreachable, and by that point PyPI has already published; stopping there would
strand the package with no release pointing at it. So the release is created
with GitHub's generic notes and **the job then fails on purpose**. The run goes
red, an annotation says exactly what was substituted, and nothing is lost. Edit
the release body by hand, or fix the cause and re-run the job.

Fix the cause, then re-run the **same** tag — there is no need to burn a version
number:

- **Actions tab → the failed run → "Re-run failed jobs"** picks up from the job
  that failed and reuses the artifacts already built.
- **Actions tab → Release → "Run workflow"** takes an existing tag as input and
  runs the whole pipeline against it. Use this when the run is too old to re-run,
  or when you fixed something outside the repository — a missing PyPI publisher,
  say.

Retrying an upload is safe. `uv publish --check-url` checks the index first, so a
run that uploaded the sdist and then died before the wheel will skip the sdist
rather than fail on a duplicate. Re-running the release job likewise refreshes
the attached files instead of erroring on them.

The one thing a retry cannot fix is a version already published to PyPI with
different contents — PyPI does not allow overwriting a file. That needs a new
tag.

**One-time setup before the first tag.** PyPI publishing uses Trusted Publishing,
so no API token is stored anywhere — but it will not work until you register the
publisher. On <https://pypi.org/manage/account/publishing/>, add a pending
publisher with:

| Field | Value |
|-------|-------|
| PyPI project name | `google-cloud-support-mcp` |
| Owner | your GitHub user or org |
| Repository name | this repository |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

The environment name matters: the `pypi` job declares `environment: pypi`, and
PyPI checks it. Creating that environment in the repository settings also lets
you require a manual approval before anything is published.

Integration tests are double-gated on purpose:

```bash
export GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT=projects/my-test-project   # read-only tests
export GOOGLE_CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1                    # also the writing ones
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
