"""Command-line access to the same bounded project operations as the MCP server."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
from urllib.parse import urlsplit

from .project import DEFAULT_PROJECT, PrintProject


def configure_mcp(root: Path, project: str) -> dict:
    """Register only this project's server, preserving any unrelated settings."""
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ValueError("Create .venv and install '.[printer]' before configuring MCP")
    target = root / ".codex" / "config.toml"
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Codex configuration path escapes the repository")
    current = target.read_text() if target.exists() else ""
    parsed = tomllib.loads(current)
    if "uav_print" in parsed.get("mcp_servers", {}):
        return {"state": "already_configured", "path": str(target)}
    # JSON strings are valid TOML basic strings; no shell command is constructed.
    q = json.dumps
    block = f'''\n[mcp_servers.uav_print]
command = {q(str(python))}
args = ["-m", "uavdesign.printing.mcp_server", "--root", {q(str(root))}, "--project", {q(project)}]
cwd = {q(str(root))}
env_vars = ["PRUSALINK_URL", "PRUSALINK_USERNAME", "PRUSALINK_PASSWORD"]
startup_timeout_sec = 30
tool_timeout_sec = 420
enabled = true
'''
    text = current.rstrip() + "\n" + block
    tomllib.loads(text)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return {"state": "configured", "path": str(target),
            "next_step": "Reload the trusted repository in Codex to load uav_print"}


def configure_printer(root: Path, url: str, *, url_only: bool = False) -> dict:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or parsed.path not in {"", "/"} or
            parsed.query or parsed.fragment):
        raise ValueError("Use a printer base URL without credentials, path or query")
    target = root / ".local" / "printing" / "connection.json"
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Local connection path must remain inside the repository")
    config = {"url": url.rstrip("/")}
    if not url_only:
        if not sys.stdin.isatty():
            raise ValueError("Run configure-printer in a local terminal for hidden password entry")
        config["username"] = input("PrusaLink username: ").strip()
        config["password"] = getpass.getpass("PrusaLink password (hidden): ")
        if not config["username"] or not config["password"]:
            raise ValueError("Both username and password are required")
    elif target.exists():
        previous = json.loads(target.read_text())
        if previous.get("url") == config["url"]:
            config.update({k: previous[k] for k in ("username", "password") if k in previous})
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".connection-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(config, stream, indent=2)
            stream.write("\n")
        os.chmod(temp, 0o600)
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)
    return {"state": "configured" if not url_only else "url_saved", "path": str(target),
            "credentials_saved": bool(config.get("password"))}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan and review survey-wing print beds; never start a physical print")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "inventory", "plan", "printer-status", "configure-mcp"):
        sub.add_parser(name)
    configure = sub.add_parser("configure-printer")
    configure.add_argument("--url", required=True)
    configure.add_argument("--url-only", action="store_true", help="Save hostname without prompting for credentials")
    for name in ("prepare", "slice"):
        plate = sub.add_parser(name)
        plate.add_argument("plate_id", help="e.g. plate_001")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.command == "configure-mcp":
            result = configure_mcp(root, args.project)
        elif args.command == "configure-printer":
            result = configure_printer(root, args.url, url_only=args.url_only)
        else:
            project = PrintProject(root, args.project)
            if args.command == "plan":
                result = project.export()
                result["plan"] = {key: result["plan"][key] for key in
                                  ("artifact_state", "part_count", "mass_estimate_g")}
            elif args.command in {"prepare", "slice"}:
                result = project.slice(args.plate_id, execute=args.command == "slice")
            else:
                result = {"status": project.status, "inventory": project.inventory,
                          "printer-status": project.printer_status}[args.command]()
        print(json.dumps(result, indent=2))
        return 0 if result.get("state") not in {"blocked", "unavailable"} else 2
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(json.dumps({"state": "error", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
