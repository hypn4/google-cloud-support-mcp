"""Server assembly: lifespan, middleware, tag gating, explicit registration.

Registration is explicit rather than FastMCP's FileSystemProvider. This package
gets installed and run from an arbitrary path, so a runtime directory scan is
fragile where an import is not — and explicit calls keep import errors traceable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastmcp import FastMCP
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware

# Absolute rather than relative, unlike the rest of the package. The FastMCP CLI
# loads this file by path with `spec_from_file_location("server_module", ...)` —
# no parent package — so a relative import here raises `attempted relative import
# with no known parent package` and `fastmcp inspect`/`run`/`dev` cannot load the
# server at all. The modules pulled in below are imported as part of the real
# package, so their own relative imports keep working. See fastmcp.json.
from google_cloud_support_mcp.auth import CredentialProvider
from google_cloud_support_mcp.clients import SupportClients, build_clients
from google_cloud_support_mcp.redaction import RedactionMiddleware, install_log_redaction
from google_cloud_support_mcp.settings import Settings, get_settings

__all__ = ["build_server", "create_server"]


# The name this package is published under. It is a constant rather than a
# literal inside the lookup below because the two are coupled and the coupling
# fails quietly: if this drifts from `project.name` in pyproject.toml, the lookup
# raises PackageNotFoundError, gets caught, and every client is told the version
# is UNKNOWN_VERSION. Nothing crashes. A contract test asserts the pair still
# agree — see tests/contract/test_tool_inventory.py.
DISTRIBUTION_NAME = "google-cloud-support-mcp"

# Returned when the package is not installed, e.g. running straight from a
# source tree. Named so tests can distinguish "not installed" from "installed
# under a different name", which look identical from here.
UNKNOWN_VERSION = "0.0.0+unknown"


def _package_version() -> str:
    """Our version, not FastMCP's.

    Left unset, `serverInfo.version` reports the FastMCP library version, which
    tells a client nothing about which release of this server it is talking to.
    """
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


INSTRUCTIONS = """\
Read and act on Google Cloud Support cases across the projects and organizations
the user names.

Scopes are given per request, not configured in advance. When a user says "the
cases in my-billing-project", pass that scope on the call. If you do not know the
identifier, call list_scopes to find it — do not tell the user to set an
environment variable.

Scope: cases, comments, attachments, and problem classifications. Support event
subscriptions are not exposed.

Before anything is sent to Google Support — creating a case, commenting, changing
attributes, closing, or uploading — you will be asked to confirm the exact payload.
Declining changes nothing.

Escalation is disabled by default because it reaches Google's support organisation
directly; set GOOGLE_CLOUD_SUPPORT_MCP_ENABLE_ESCALATION=true to expose it. Setting
GOOGLE_CLOUD_SUPPORT_MCP_ENABLE_WRITES=false leaves only the read tools.

GOOGLE_CLOUD_SUPPORT_MCP_PARENTS is an optional default, used only when a request
names no scope at all. It is a convenience, not a prerequisite.
"""


def _lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, object]]:
        clients: SupportClients | None = None
        try:
            clients = build_clients(CredentialProvider(settings.quota_project))
            yield {"clients": clients, "settings": settings}
        finally:
            if clients is not None:
                await clients.aclose()

    return lifespan


def _apply_gating(mcp: FastMCP, settings: Settings) -> None:
    """Hide tool groups the operator turned off (FR-018).

    Escalation is off unless explicitly enabled; the remaining writes are on,
    gated by the confirmation step rather than by configuration.
    """
    disabled: set[str] = set()
    if not settings.enable_writes:
        disabled.add("write")
    if not settings.enable_escalation:
        disabled.add("escalation")
    if disabled:
        mcp.disable(tags=disabled)


def build_server(
    settings: Settings | None = None,
    *,
    clients: SupportClients | None = None,
) -> FastMCP:
    """Assemble the server.

    Passing `clients` injects a ready bundle and skips the lifespan entirely, so
    contract tests can run against mocks without touching credentials.
    """
    settings = settings or get_settings()
    install_log_redaction("google_cloud_support_mcp")

    mcp = FastMCP(
        name="google-cloud-support",
        version=_package_version(),
        instructions=INSTRUCTIONS,
        # Only ToolError text reaches a client, so anything that skips the error
        # mapping in errors.py leaks nothing.
        mask_error_details=True,
        lifespan=None if clients is not None else _lifespan(settings),
        middleware=[
            ErrorHandlingMiddleware(),
            # Before the logging middleware on purpose: what it would otherwise
            # record is customer support data (FR-022).
            RedactionMiddleware(),
            TimingMiddleware(),
            LoggingMiddleware(),
            RateLimitingMiddleware(max_requests_per_second=20),
        ],
    )

    from google_cloud_support_mcp.prompts import register_prompts
    from google_cloud_support_mcp.resources import register_resources
    from google_cloud_support_mcp.tools import register_all

    def get_clients() -> SupportClients:
        """Resolve the client bundle for the in-flight request.

        Injected clients win (that is how contract tests avoid credentials);
        otherwise the bundle comes from the lifespan context, which owns it for
        the life of the process rather than per call.
        """
        if clients is not None:
            return clients
        from fastmcp.server.dependencies import get_context

        lifespan_context = get_context().lifespan_context
        if isinstance(lifespan_context, dict) and "clients" in lifespan_context:
            return lifespan_context["clients"]
        raise RuntimeError(
            "Support clients are unavailable — the server lifespan did not start. "
            "Check that credentials resolve (gcloud auth application-default login)."
        )

    register_all(mcp, settings, get_clients)
    register_resources(mcp, settings, get_clients)
    register_prompts(mcp, settings)
    _apply_gating(mcp, settings)
    return mcp


def create_server() -> FastMCP:
    return build_server()
