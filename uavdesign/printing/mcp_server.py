"""Local stdio MCP interface. No cloud service and no physical print controls."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .project import DEFAULT_PROJECT, PrintProject


def create_server(root: Path, project_path: str = DEFAULT_PROJECT) -> MCPServer:
    # Load on every call so edited layout/preset settings take effect immediately.
    def current_project() -> PrintProject:
        return PrintProject(root, project_path)
    server = MCPServer(
        "UAV print project", version="0.1.0", log_level="WARNING",
        instructions=("Plan beds from the repository's own parts. Export 3MF and previews for the user's final check. "
                      "Geometry layouts are not sliced jobs. Use matching complete PrusaSlicer settings before slicing. "
                      "Check with the user before starting any physical print; this server exposes no start/upload commands. "
                      "Never request or return printer credentials in chat."),
    )
    read = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)

    @server.tool(annotations=read)
    def project_status() -> dict[str, Any]:
        """Check project, slicer/preset availability and printer configuration without disclosing credentials."""
        return current_project().status()

    @server.tool(annotations=read)
    def part_inventory() -> dict[str, Any]:
        """Verify source checksums and read all printable parts, materials, bounds and profile settings."""
        return current_project().inventory()

    @server.tool(annotations=write)
    def plan_prints() -> dict[str, Any]:
        """Arrange compatible parts on beds and export review HTML, SVGs, 3MFs, checksums and a ZIP."""
        project = current_project()
        result = project.export()
        plan = result.pop("plan")
        result.update({key: plan[key] for key in ("artifact_state", "part_count", "mass_estimate_g")})
        result["plate_count"] = len(plan["plates"])
        result["review_file"] = str(project.plan_dir() / "queue.html")
        result["plates"] = [{key: p[key] for key in ("id", "profile", "material", "mass_estimate_g")}
                            for p in plan["plates"]]
        return result

    @server.tool(annotations=read)
    def review_plate(plate_id: str) -> dict[str, Any]:
        """Read placement details and 3MF/preview filenames for a plate in the current verified plan."""
        project = current_project()
        plan = project.read_plan()
        for plate in plan["plates"]:
            if plate["id"] == plate_id:
                return {"state": "arranged_geometry", "directory": str(project.plan_dir()), "plate": plate}
        raise ValueError("Unknown plate identifier")

    @server.tool(annotations=read)
    def prepare_plate(plate_id: str) -> dict[str, Any]:
        """Check matching printer/filament/profile configuration and describe the slicer command; do not slice."""
        return current_project().slice(plate_id)

    @server.tool(annotations=write)
    def slice_plate(plate_id: str) -> dict[str, Any]:
        """Slice a verified planned plate using the configured complete INI and save G-code for review only."""
        return current_project().slice(plate_id, execute=True)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    def printer_status() -> dict[str, Any]:
        """Read local PrusaLink capability/status/storage/job data; never upload or start a print."""
        return current_project().printer_status()

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    args = parser.parse_args()
    create_server(args.root, args.project).run(transport="stdio")


if __name__ == "__main__":
    main()
