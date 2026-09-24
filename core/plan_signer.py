"""HMAC-signed capability tokens for destructive MCP calls.

The MCP client is untrusted: a self-asserted ``confirmed: true`` boolean is
worthless as confirmation. Instead the operator mints a capability token
offline with a shared secret (``ALIX_MCP_HMAC_KEY``) and the client presents
it per call::

    python3 -m core.plan_signer --tools delete_file,write_file --ttl 3600

The token binds a tool scope + expiry timestamp; the server verifies the
HMAC with a constant-time comparison before executing anything destructive.
Signing proves *who approved* (holder of the key), not intent -- it pairs
with the Policy layer, which still validates every argument.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
import time

VERSION = "v1"
KEY_ENV = "ALIX_MCP_HMAC_KEY"


def _key(provided: str | None = None) -> str:
    key = provided or os.environ.get(KEY_ENV, "")
    if not key:
        raise RuntimeError(
            f"{KEY_ENV} is not set. Generate one:\n"
            '  python3 -c "import secrets; print(secrets.token_hex(32))"\n'
            f"then export {KEY_ENV}=<value> in the MCP server environment."
        )
    return key


def _scope(tools) -> str:
    names = sorted({t.strip() for t in tools if t and t.strip()})
    if not names:
        raise ValueError("tool scope must not be empty")
    return ",".join(names)


def mint(tools, ttl_s: int = 3600, key: str | None = None) -> str:
    """Mint a capability token for ``tools`` valid for ``ttl_s`` seconds."""
    secret = _key(key)
    scope = _scope(tools)
    expiry = int(time.time()) + int(ttl_s)
    msg = f"{VERSION}\n{scope}\n{expiry}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"{VERSION}.{scope}.{expiry}.{sig}"


def verify_token(token: str, tool: str, key: str | None = None) -> bool:
    """True iff the token is well-formed, unexpired, covers ``tool`` and
    the HMAC verifies under the shared secret (constant-time compare)."""
    try:
        ver, scope, expiry_s, sig = token.split(".", 3)
    except (ValueError, AttributeError):
        return False
    if ver != VERSION or not expiry_s.isdigit():
        return False
    if int(expiry_s) < int(time.time()):
        return False
    if tool not in scope.split(","):
        return False
    try:
        secret = _key(key)
    except RuntimeError:
        return False
    msg = f"{ver}\n{scope}\n{expiry_s}".encode()
    expect = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expect, sig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Mint an HMAC capability token for MCP destructive tools."
    )
    ap.add_argument("--tools", required=True,
                    help="comma-separated tool names, e.g. delete_file,write_file")
    ap.add_argument("--ttl", type=int, default=3600,
                    help="validity in seconds (default 3600)")
    a = ap.parse_args(argv)
    try:
        print(mint(a.tools.split(","), a.ttl))
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
