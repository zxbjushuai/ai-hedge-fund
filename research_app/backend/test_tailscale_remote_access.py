"""Tailscale Serve helper plans and applies only the intended local mappings."""

from types import SimpleNamespace

import scripts.tailscale_remote_access as remote


def test_build_serve_commands_routes_api_paths_and_frontend():
    assert remote.build_serve_commands(backend_port=8000, frontend_port=5173) == [
        [
            "tailscale",
            "serve",
            "--bg",
            "--https=443",
            "--set-path=/dashboard",
            "http://127.0.0.1:8000/dashboard",
        ],
        [
            "tailscale",
            "serve",
            "--bg",
            "--https=443",
            "--set-path=/health",
            "http://127.0.0.1:8000/health",
        ],
        ["tailscale", "serve", "--bg", "--https=443", "http://127.0.0.1:5173"],
    ]


def test_apply_serve_runs_commands_without_a_shell():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    remote.apply_serve(runner=runner)

    assert [command for command, _ in calls] == remote.build_serve_commands()
    assert all(kwargs.get("check") is False for _, kwargs in calls)
    assert all(kwargs.get("shell") is not True for _, kwargs in calls)


def test_resolve_access_url_uses_the_tailnet_dns_name():
    status = {"Self": {"DNSName": "aihf-node.tailnet.ts.net.", "Online": True}}

    assert remote.resolve_access_url(status) == "https://aihf-node.tailnet.ts.net/"
