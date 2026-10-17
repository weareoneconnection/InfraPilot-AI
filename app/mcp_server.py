"""MCP server (official MCP Python SDK v2): field events as tools for agents.

An agent (for example a GlobalInfra specialist or a drone/inspection robot
controller) can report an observation, read an event, list the board and the
dashboard, and look up precedents. Approval, dispatch, task completion,
re-inspection and closure stay with named humans in the field console.
"""
from __future__ import annotations

from mcp.server import MCPServer

from .service import FieldPilot

EXPOSED = ["report_observation", "get_event", "list_events", "field_dashboard", "list_assets"]


def build_server(pilot: FieldPilot) -> MCPServer:
    server = MCPServer("InfraPilot AI", version="2.0.0",
                       instructions="Field events with risk, SLA, evidence-backed plans and independent re-inspection.")

    @server.tool()
    def report_observation(description: str, reporter: str = "agent:inspection", asset_id: str = "",
                           lat: float | None = None, lon: float | None = None) -> dict:
        """Report a site observation. Risk is fused (never lowered), the asset located and a plan proposed for human approval."""
        e = pilot.report(description=description, reporter=reporter, asset_id=asset_id or None, lat=lat, lon=lon)
        return {k: e[k] for k in ("id", "asset_id", "asset_method", "final_risk", "stop_work", "status", "response_due", "close_due", "findings", "tasks")}

    @server.tool()
    def get_event(event_id: str) -> dict:
        """Full event: risk fusion, findings with evidence, tasks, photos, receipts, audit and precedents."""
        return pilot.event(event_id)

    @server.tool()
    def list_events(limit: int = 20) -> list[dict]:
        """Recent events with risk, status, stop-work and overdue flags."""
        return pilot.board(min(max(limit, 1), 100))

    @server.tool()
    def field_dashboard() -> dict:
        """SLA compliance, first-pass verification rate, active stop-work, overdue events and hotspots."""
        return pilot.dashboard()

    @server.tool()
    def list_assets() -> list[dict]:
        """Registered assets with coordinates and geofences."""
        return list(pilot.assets.values())

    return server


if __name__ == "__main__":
    import argparse

    from .llm import from_env
    from .store import Store

    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8111)
    args = parser.parse_args()
    server = build_server(FieldPilot(Store(), model=from_env()))
    server.run(transport="streamable-http", port=args.port) if args.transport == "streamable-http" else server.run()
