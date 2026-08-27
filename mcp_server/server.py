from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "GC_Bridge_4.settings")

import django

django.setup()

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount

from microtech.services.mcp_operations import MicrotechMcpOperationsService


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
RECOVERY_ACTION = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
DESTRUCTIVE_ACTION = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


class BearerTokenApp:
    """Minimal network-internal bearer-token guard for the entire mounted MCP application."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            authorization = headers.get(b"authorization", b"").decode("latin-1")
            expected = f"Bearer {self.token}"
            if not hmac.compare_digest(authorization, expected):
                response = PlainTextResponse(
                    "Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be configured before the MCP server starts.")
    return value


def _csv_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _transport_security() -> TransportSecuritySettings:
    return TransportSecuritySettings(
        allowed_hosts=_csv_env("MCP_ALLOWED_HOSTS", "10.0.0.165,10.0.0.165:*"),
        allowed_origins=_csv_env("MCP_ALLOWED_ORIGINS", ""),
    )


def _make_bridge_server() -> MCPServer:
    server = MCPServer(
        "GC-Bridge Operations",
        description="Diagnose und kontrollierte Recovery für GC-Bridge-Queues und Bestell-Workflows.",
        instructions=(
            "Beginne immer mit get_bridge_diagnosis oder einer gezielten Diagnose. "
            "Recovery-Tools benötigen die exakt angegebene Bestätigung und dürfen erst nach der Diagnose verwendet werden."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def get_bridge_diagnosis(stale_after_minutes: int = 15, limit: int = 20) -> dict[str, Any]:
        """Inspect local GraphQL jobs, order workflows, Celery workers and remote worker state without changing data."""
        return MicrotechMcpOperationsService().bridge_diagnosis(
            stale_after_minutes=stale_after_minutes,
            limit=limit,
        )

    @server.tool(annotations=READ_ONLY)
    def get_job_diagnosis(job_id: int) -> dict[str, Any]:
        """Inspect one local job, its error, linked order workflow and its current remote GraphQL status."""
        return MicrotechMcpOperationsService().job_diagnosis(job_id=job_id)

    @server.tool(annotations=READ_ONLY)
    def get_order_workflow_diagnosis(workflow_id: int) -> dict[str, Any]:
        """Inspect one order-sync workflow, including its step log and current remote job state."""
        return MicrotechMcpOperationsService().workflow_diagnosis(workflow_id=workflow_id)

    @server.tool(annotations=RECOVERY_ACTION)
    def poll_job_now(job_id: int, confirmation: str) -> dict[str, Any]:
        """Force one poll of an active job. Use confirmation='POLL'; success can trigger its existing continuation."""
        return MicrotechMcpOperationsService().poll_job_now(job_id=job_id, confirmation=confirmation)

    @server.tool(annotations=RECOVERY_ACTION)
    def reconcile_order_workflows(confirmation: str) -> dict[str, Any]:
        """Mark orphaned/failed workflows consistently using existing recovery logic. Use confirmation='ABGLEICH'."""
        return MicrotechMcpOperationsService().reconcile_order_workflows(confirmation=confirmation)

    @server.tool(annotations=DESTRUCTIVE_ACTION)
    def resume_order_workflow(workflow_id: int, confirmation: str) -> dict[str, Any]:
        """Resume only a definitively failed workflow. It can submit a remote write. Use confirmation='FORTSETZEN'."""
        return MicrotechMcpOperationsService().resume_order_workflow(
            workflow_id=workflow_id,
            confirmation=confirmation,
        )

    @server.tool(annotations=DESTRUCTIVE_ACTION)
    def abort_order_workflow(workflow_id: int, reason: str, confirmation: str) -> dict[str, Any]:
        """Abort a workflow locally only when remote status is unavailable. It does not cancel remote work. Use confirmation='WORKFLOW ABBRECHEN'."""
        return MicrotechMcpOperationsService().abort_order_workflow(
            workflow_id=workflow_id,
            reason=reason,
            confirmation=confirmation,
        )

    @server.tool(annotations=DESTRUCTIVE_ACTION)
    def restart_order_workflow(workflow_id: int, confirmation: str) -> dict[str, Any]:
        """Restart from scratch only after the old remote job is confirmed unavailable. Use confirmation='NEUSTARTEN'."""
        return MicrotechMcpOperationsService().restart_order_workflow(
            workflow_id=workflow_id,
            confirmation=confirmation,
        )

    @server.tool(annotations=DESTRUCTIVE_ACTION)
    def cancel_microtech_job(job_id: int, confirmation: str) -> dict[str, Any]:
        """Cancel a job remotely and delete its local record. Use confirmation='JOB ABBRECHEN'."""
        return MicrotechMcpOperationsService().cancel_job(job_id=job_id, confirmation=confirmation)

    @server.tool(annotations=RECOVERY_ACTION)
    def start_microtech_worker(confirmation: str) -> dict[str, Any]:
        """Queue the audited start operation for a stopped remote Microtech worker. Use confirmation='WORKER STARTEN'."""
        return MicrotechMcpOperationsService().start_microtech_worker(confirmation=confirmation)

    return server


def _make_graphql_server() -> MCPServer:
    server = MCPServer(
        "Microtech GraphQL Read Access",
        description="Lesezugriff auf Microtech-Kunden, Produkte und Vorgänge über die vorhandene GraphQL-Job-Queue.",
        instructions=(
            "get_graphql_status ist rein lesend. Die drei fetch-Tools starten jeweils einen temporären "
            "Read-Job in GraphQL, ändern aber keine Geschäftsobjekte."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def get_graphql_status() -> dict[str, Any]:
        """Read GraphQL liveness, Microtech worker state and backup mode without changing them."""
        return MicrotechMcpOperationsService().graphql_status()

    @server.tool(annotations=RECOVERY_ACTION)
    def fetch_customer(customer_number: str, timeout_seconds: int = 45) -> dict[str, Any]:
        """Fetch one customer. This queues a temporary read job but does not change customer data."""
        return MicrotechMcpOperationsService().fetch_customer(
            customer_number=customer_number,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=RECOVERY_ACTION)
    def fetch_product(erp_number: str, timeout_seconds: int = 45) -> dict[str, Any]:
        """Fetch one product. This queues a temporary read job but does not change product data."""
        return MicrotechMcpOperationsService().fetch_product(
            erp_number=erp_number,
            timeout_seconds=timeout_seconds,
        )

    @server.tool(annotations=RECOVERY_ACTION)
    def fetch_order(beleg_nr: str, timeout_seconds: int = 45) -> dict[str, Any]:
        """Fetch one Microtech Vorgang. This queues a temporary read job but does not change order data."""
        return MicrotechMcpOperationsService().fetch_order(
            beleg_nr=beleg_nr,
            timeout_seconds=timeout_seconds,
        )

    return server


def create_app() -> Starlette:
    token = _required_env("MCP_OPERATIONS_TOKEN")
    bridge = _make_bridge_server()
    graphql = _make_graphql_server()
    security = _transport_security()
    bridge_app = BearerTokenApp(bridge.streamable_http_app(transport_security=security), token)
    graphql_app = BearerTokenApp(graphql.streamable_http_app(transport_security=security), token)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(bridge.session_manager.run())
            await stack.enter_async_context(graphql.session_manager.run())
            yield

    return Starlette(
        routes=[
            Mount("/bridge", app=bridge_app),
            Mount("/graphql", app=graphql_app),
        ],
        lifespan=lifespan,
    )


app = create_app()
