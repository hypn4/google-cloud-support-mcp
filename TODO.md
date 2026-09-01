# TODO

**Nothing here is unimplemented.** Every item below is code that exists and is covered by
mock-based contract tests. What is missing in each case is a run against the live API, and
each needs an environment the machine that wrote this did not have — a paid support plan, a
second Google account, or a person who has not read the docs.

If you have one of those, the items are small and self-contained. Each says what is unknown,
what would unblock it, and what to change once you know.

The design documents these came from are a local-only Spec Kit workspace and are not in this
repository. **This file is the authoritative list**; nothing below requires reading anything
you do not have.

---

## Blocked on a paid support plan

The Cloud Support API refuses writes without one:

```
FailedPrecondition: 400 You are not eligible to create a case with this channel.
```

Reads work fine, which is why the read half of the server is verified and the write half is
not. Any project on Standard, Enhanced or Premium unblocks both items below.

### Attachment upload: size limit and transfer form (001 · T081)

**Unknown.** Two things the official documentation does not state:

1. The maximum attachment size the API accepts. `MAX_UPLOAD_BYTES` defaults to 10 MB — a
   **placeholder, not a measured limit.** It may be higher or lower than the real one. It is
   enforced client-side before the confirmation prompt, so today it can reject an upload the
   server would have taken, or wave through one the server will refuse.
2. Whether the media Upload URI wants `?uploadType=multipart`. The `media.upload` reference
   documents the URI and the request body but never mentions `uploadType`, so what is
   implemented is an informed guess.

**What the code does now** — `src/google_cloud_support_mcp/media.py`,
`upload_attachment_file()`:

```
POST https://cloudsupport.googleapis.com/upload/v2/{case}/attachments?uploadType=multipart
  metadata = {"attachment": {"filename": ...}}   (application/json)
  file     = <bytes>                             (application/octet-stream)
```

The filename travels **in the body**, not as a query parameter. That part is confirmed against
the official reference; only the `uploadType` and the size ceiling are open.

**To verify:**

```bash
export GOOGLE_CLOUD_SUPPORT_MCP_IT_PARENT=projects/PROJECT_ID
export GOOGLE_CLOUD_SUPPORT_MCP_IT_ALLOW_WRITES=1
uv run pytest tests/integration/test_lifecycle_journey.py -v -m integration
```

That creates a `test_case=True` case, uploads a small file, lists, downloads and closes. If the
upload fails, read the raw HTTP status and body before changing anything — they tell you which
of the two unknowns bit.

If `uploadType=multipart` is rejected, try `?uploadType=media` (bytes only) before rewriting to
the two-step form, where you `POST https://cloudsupport.googleapis.com/v2/{parent}/attachments`
to create the `Attachment` first and then send the bytes.

For the size ceiling: upload at 1 MB, 10 MB, 50 MB and 100 MB, note where the server rejects,
and set `max_upload_bytes` in `src/google_cloud_support_mcp/settings.py` just under it.

**Then update:** `media.py` if the protocol differs, `settings.py` for the default, and add a
regression test to `tests/contract/test_lifecycle_and_media.py` for whatever the real protocol
turns out to be.

### Write walkthroughs against the live API (001 · T085)

**Unverified.** Two scenarios from the 001 quickstart: case creation with the
confirm / decline / approve round trip, and the attachment cycle. Everything else in that
document was walked live on 2026-09-01 — reads, fan-out partial failure, error classification,
log redaction, protocol eras — and the tool-surface check now runs on every CI push, so none
of that is owed.

**To verify:**

```bash
export GOOGLE_CLOUD_SUPPORT_MCP_PARENTS='["projects/PROJECT_ID"]'
uv run fastmcp inspect        # sanity: 14 tools by default
```

Then drive create → comment → attach → close through an MCP client.

**Two rules that do not relax:**

1. **Always pass `test_case: true` when creating.** Without it the case becomes a real ticket
   routed to a Google support engineer. `tests/integration/conftest.py` enforces this for the
   test suite; a manual walkthrough has no such net.
2. **Do not run escalation.** It reaches Google's support organisation whether or not the case
   is flagged as a test. Its behaviour is covered by
   `tests/contract/test_lifecycle_and_media.py::TestEscalateCase`.

---

## Blocked on a second, less-privileged account

### Partial scope visibility (002 · T036)

**Unverified.** `list_scopes` is built to return what it could read and report what it could
not: a caller holding `resourcemanager.projects.get` but not `resourcemanager.organizations.get`
should get their projects plus a stated reason for the missing organizations, rather than an
error. Three contract tests cover the logic with mocks. What is unverified is that the path is
actually taken in a real account — and that the results a restricted account sees are a subset
of what a privileged one sees, which is the only direct demonstration that enumeration never
exceeds the caller's own grants.

A mock cannot show this. It returns whatever it is told.

**Unblocked by** one service account with `roles/browser` and no organization access:

```bash
gcloud iam service-accounts create scope-test --project=PROJECT_ID
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member=serviceAccount:scope-test@PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/browser
```

Point ADC at that account, call `list_scopes`, and check that projects come back, that
`scopes_failed` names `organizations` with an actionable reason, and that the result is a
subset of what your own account returns. Then repeat with
`cloudresourcemanager.googleapis.com` disabled and confirm the failure reads as
`api_not_enabled` rather than as a permission problem — telling someone to ask for a role they
already have wastes their time.

---

## Blocked on a person

### First-run time to a successful query (001 · T083)

**Unmeasured.** The 001 spec sets a target: someone new reaches their first successful
`search_cases` within ten minutes, reading nothing but the README. It cannot be measured by
anyone who has already read the README.

**To measure.** Give someone who has not seen this project the repository, the README's
Prerequisites and Install sections, and a project with a paid support plan. Start a timer at
`clone`, stop it at the first `search_cases` that returns without a `scopes_failed` entry. Do
not answer questions during the run — write each one down instead, because each is a README
gap.

**The likely failure point has moved.** This item was written when an unset
`GOOGLE_CLOUD_SUPPORT_MCP_PARENTS` was the usual first stumble. That is no longer true:
`PARENTS` is now an optional default, scopes are named per request, and `list_scopes` finds
identifiers. The stumble to watch for now is more likely the Cloud Resource Manager API not
being enabled, or ADC quota-project setup. Watch where they actually stall rather than where
this note guesses.

---

## Verified API behaviour — do not re-derive

Each row cost a live call to learn and would have passed a mock test either way. Where the
code and this table disagree, the code wins — the location column is where to look.

| Behaviour | Where it lives |
|---|---|
| `search_case_classifications`' `query` is a **filter expression**, not free text. `display_name:"*Compute Engine*"` matches; bare keywords fail | `tools/classifications.py`, `build_classification_query()` |
| No support plan surfaces as **`FailedPrecondition` 400**, not 403 | `errors.py`, `_PLAN_SIGNATURES` |
| A **third** cause of 403: the API was never enabled on the project | `errors.py`, `ErrorKind.API_NOT_ENABLED` |
| Google returns a bare **500 for a project that does not exist** — not `NOT_FOUND`. gRPC and HTTP must classify it identically, and a 500 carries nothing that separates a typo from a real outage, so the "retryable" wording it produces is wrong for a typo and is not fixable from here | `errors.py`, `_GRPC_MAP` |
| There is no lookup-by-id RPC for classifications, so `create_case` validates by membership in the full catalogue (~2,878 entries, six pages, about three seconds), cached once per process | `tools/classifications.py`, `classification_catalog()` |
| Resource Manager's `SearchProjects` filters by **prefix only** (`name:how*`); `SearchOrganizations` cannot filter by display name at all, only by `domain` or `directoryCustomerId`. Hence an empty query and local matching for both, so one argument does not mean two things | `tools/scopes.py`, `_matches()` |
| `Project.name` is `projects/{project_number}`. The value a person recognises is `project_id` | `serializers.py`, `to_scope_ref()` |
| Neither `SearchProjectsRequest` nor `SearchOrganizationsRequest` documents a maximum `page_size`, and both may return fewer than asked — so a paging bound must count scopes, not pages | `tools/scopes.py`, `_SCOPE_SEARCH_LIMIT` |
