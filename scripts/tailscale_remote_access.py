#!/usr/bin/env python3
"""Plan or apply loopback-only Tailscale Serve mappings for the research app."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]


def build_serve_commands(
    backend_port: int = 8000,
    frontend_port: int = 5173,
) -> list[list[str]]:
    backend = f"http://127.0.0.1:{backend_port}"
    frontend = f"http://127.0.0.1:{frontend_port}"
    return [
        ["tailscale", "serve", "--bg", "--https=443", "--set-path=/dashboard", f"{backend}/dashboard"],
        ["tailscale", "serve", "--bg", "--https=443", "--set-path=/health", f"{backend}/health"],
        ["tailscale", "serve", "--bg", "--https=443", frontend],
    ]


def apply_serve(
    backend_port: int = 8000,
    frontend_port: int = 5173,
    runner: Runner | None = None,
) -> None:
    if runner is None:
        runner = subprocess.run
    for command in build_serve_commands(backend_port, frontend_port):
        result = runner(command, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise RuntimeError(f"Tailscale Serve failed: {' '.join(command)}: {detail}")


def load_tailscale_status(runner: Runner | None = None) -> dict:
    if runner is None:
        runner = subprocess.run
    result = runner(["tailscale", "status", "--json"], check=False, text=True, capture_output=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise RuntimeError(f"tailscale status failed: {detail}")
    return json.loads(result.stdout)


def resolve_access_url(status: dict) -> str:
    self_node = status.get("Self") or {}
    dns_name = str(self_node.get("DNSName") or "").rstrip(".")
    if not self_node.get("Online") or not dns_name:
        raise ValueError("Tailscale node is offline or has no MagicDNS name")
    return f"https://{dns_name}/"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expose ai-hedge-fund only inside a Tailscale tailnet")
    parser.add_argument("action", nargs="?", choices=("plan", "apply"), default="plan")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args(argv)

    commands = build_serve_commands(args.backend_port, args.frontend_port)
    if args.action == "plan":
        print("# Review these commands; run `apply` to execute them.")
        for command in commands:
            print(" ".join(command))
        return 0

    if shutil.which("tailscale") is None:
        parser.error("tailscale CLI is not installed")
    try:
        access_url = resolve_access_url(load_tailscale_status())
        apply_serve(args.backend_port, args.frontend_port)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Tailscale Serve is enabled at {access_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
