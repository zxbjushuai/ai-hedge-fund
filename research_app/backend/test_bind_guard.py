"""The supported backend entrypoint must not expose an unauthenticated bind."""

import pytest

from research_app.backend.__main__ import validate_bind_host


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("127.0.0.2", "127.0.0.2"),
        ("::1", "::1"),
        ("[::1]", "::1"),
        ("localhost", "localhost"),
        ("LOCALHOST.", "localhost"),
    ],
)
def test_validate_bind_host_normalizes_loopback(host: str, expected: str):
    assert validate_bind_host(host) == expected


@pytest.mark.parametrize("host", ["0.0.0.0", "100.84.98.125", "192.168.1.10", "example.com", ""])
def test_validate_bind_host_rejects_non_loopback(host: str):
    with pytest.raises(ValueError, match="loopback"):
        validate_bind_host(host)
