# Deferred verification

**Feature**: `001-gcp-support-mcp` | **Written**: 2026-09-01 | **Status**: 82/85 tasks done

Three tasks from [tasks.md](./tasks.md) could not be completed and are **not**
design gaps — the code for all three is written and covered by mock-based
contract tests. What is missing is verification against a live API, and that
needs something this machine did not have.

This file is meant to be self-contained: you should be able to finish these
without reading the conversation that produced them.

---

## The one blocker behind two of them

`projects/kktae-demo` — the project used for live verification — **has no paid
support plan.** Reading works; creating a case does not:

```
FailedPrecondition: 400 You are not eligible to create a case with this channel.
```

The Cloud Support API needs Standard, Enhanced, or Premium Support. Every write
path is therefore unverified against the real service.

**To unblock**: use a project (or organization) that already has a paid support
plan, and enable the API on it:

```bash
gcloud services enable cloudsupport.googleapis.com --project=PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project PROJECT_ID
```

Then set the scope for everything below:

```bash
export CLOUD_SUPPORT_MCP_PARENTS='["projects/PROJECT_ID"]'
```

---

## T081 — attachment upload size limit and `uploadType`

**What is unknown.** Two things the official documentation does not state:

1. The maximum attachment size the API accepts. `MAX_UPLOAD_BYTES` currently
   defaults to 10 MB, chosen as a placeholder, and is enforced client-side
   *before* the confirmation prompt.
2. Whether the media Upload URI wants `?uploadType=multipart`. The reference for
   `media.upload` documents the URI and the request body but never mentions
   `uploadType`, so the current implementation is an informed guess.

**What the code already does** — `src/cloud_support_mcp/media.py`,
`upload_attachment_file()`:

```
POST https://cloudsupport.googleapis.com/upload/v2/{case}/attachments?uploadType=multipart
  multipart body: metadata = {"attachment": {"filename": ...}}  (application/json)
                  file     = <bytes>                            (application/octet-stream)
```

The filename travels **in the request body**, not as a query parameter. An
earlier summary claimed otherwise; the official `media/upload` reference is
explicit and the body form is what is implemented.

**How to verify.**

```bash
export CLOUD_SUPPORT_MCP_IT_PARENT=projects/PROJECT_ID
export CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1
uv run pytest tests/integration/test_lifecycle_journey.py -v -m integration
```

That test creates a `test_case=True` case, uploads a small file, lists, downloads,
and closes. If the upload fails, read the raw HTTP response before changing
anything — the status and body tell you which of the two unknowns bit.

**Fallback if `uploadType=multipart` is rejected.** The reference documents a
second URI for metadata-only requests:

```
POST https://cloudsupport.googleapis.com/v2/{parent}/attachments
```

Create the `Attachment` there first, then send the bytes to the Upload URI. Try
`?uploadType=media` (bytes only, filename in a query parameter) before rewriting
to the two-step form.

**To find the size limit**: upload files at 1 MB, 10 MB, 50 MB, 100 MB and note
where the server rejects. Then set `max_upload_bytes` in
`src/cloud_support_mcp/settings.py` just under it.

**Files to update when resolved**
- `src/cloud_support_mcp/media.py` — the upload call, if the protocol differs
- `src/cloud_support_mcp/settings.py` — `max_upload_bytes` default
- `specs/001-gcp-support-mcp/research.md` — R-002 and open items 3 and 4
- `tests/contract/test_lifecycle_and_media.py` — add a regression test for
  whatever the real protocol turns out to be

---

## T083 — SC-008: first-run experience under ten minutes

**What is unknown.** SC-008 says a newcomer reaches their first successful
`search_cases` within ten minutes, reading nothing but the README. Nobody has
measured it, and it cannot be measured by the person who wrote the README.

**How to verify.** Give someone who has not seen this project:

- the repository
- the README's Prerequisites and Install sections
- a project with a paid support plan and their own Google account

Start a timer at "clone" and stop it at the first `search_cases` that returns
without a `scopes_failed` entry. Do not answer questions during the run — write
down every question instead, because each one is a README gap.

**Where it usually goes wrong.** The most likely failure is `PARENTS` being
unset. The tool's message names the variable and shows the JSON shape, which is
the part worth watching:

```
No scopes are configured. Set CLOUD_SUPPORT_MCP_PARENTS to a JSON list
such as ["projects/my-project","organizations/123456789"], or pass `parents`
on this call.
```

The three errors most likely to stall a newcomer are all classified and each
names its own fix — API not enabled, no support plan, missing IAM role. Whether
those messages actually land is exactly what this measurement tests.

**Files to update when resolved**
- `README.md` — every question the tester asked out loud
- `src/cloud_support_mcp/errors.py` — any guidance text that did not land
- `specs/001-gcp-support-mcp/quickstart.md` — V9's result

---

## T085 — quickstart V4 and V5 against the live API

**What is unverified.** The write scenarios in
[quickstart.md](./quickstart.md): case creation with the confirm/decline/approve
round trip (V4) and the attachment cycle (V5).

**Already verified live on 2026-09-01** — do not redo these:

| Scenario | Result |
|----------|--------|
| V1 tool surface | 13 / 14 / 8 tools, annotations correct |
| V2 read journey | `search_cases` succeeded |
| V3 fan-out partial failure | mixed reachable and unreachable scopes → call **succeeded**, failure isolated to `scopes_failed` |
| V6 error guidance | `api_not_enabled`, `support_plan_required`, `unavailable` each classified correctly against the real service |
| V7 log redaction | sentinel strings absent from 36 lines of DEBUG output |
| V8 protocol eras | contract test |

**How to verify the rest.**

```bash
export CLOUD_SUPPORT_MCP_PARENTS='["projects/PROJECT_ID"]'
uv run fastmcp inspect src/cloud_support_mcp/server.py   # V1 again, sanity
# then walk V4 steps 1-7 and V5 in quickstart.md through an MCP client
```

**Two rules that do not relax.**

1. **Always pass `test_case: true` when creating.** Without it the case becomes a
   real ticket routed to a Google support engineer. A guard in
   `tests/integration/conftest.py` enforces this for the test suite, but a manual
   walkthrough has no such net.
2. **Do not run escalation.** It reaches Google's support organisation regardless
   of whether the case is flagged as a test. Its behaviour is covered by
   `tests/contract/test_lifecycle_and_media.py::TestEscalateCase`.

**Files to update when resolved**
- `specs/001-gcp-support-mcp/quickstart.md` — the Done Criteria checklist
- `specs/001-gcp-support-mcp/tasks.md` — mark T081, T083, T085

---

## Do not re-derive these

Four things were learned from the live run that mock tests had passed straight
through. They are implemented and regression-tested; the detail is in
[research.md](./research.md) R-007 and R-010.

| Finding | Where it lives |
|---------|----------------|
| `search_case_classifications` `query` is a **filter expression**, not free text — `display_name:"*Compute Engine*"` | `tools/classifications.py`, `build_classification_query()` |
| No support plan surfaces as **`FailedPrecondition` 400**, not 403 | `errors.py`, `_PLAN_SIGNATURES` |
| A **third** cause of 403: the API was never enabled on the project | `errors.py`, `ErrorKind.API_NOT_ENABLED` |
| Google returns **500** for a nonexistent project; gRPC and HTTP must classify it identically | `errors.py`, `_GRPC_MAP` |

There is no lookup-by-id RPC for classifications, so `create_case` validates by
membership in the full catalogue (~2,878 entries, six pages, about three seconds),
cached once per process in `tools/classifications.py`.
