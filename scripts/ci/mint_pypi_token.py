#!/usr/bin/env python3
"""Exchange the GitHub Actions OIDC token for a short-lived PyPI API token.

This is the PyPI Trusted Publisher handshake that pypa/gh-action-pypi-publish
performs internally. It is done here directly because that action runs as a
Docker container pulled from ghcr.io, which an egress-locked release runner
cannot reach. The only host this talks to is the package index itself, plus the
Actions token service that issues the OIDC token.

Uses nothing outside the standard library, so it needs no package index to run.

Usage:
    mint_pypi_token.py https://test.pypi.org

Requires, from the Actions runner (present when the job has id-token: write):
    ACTIONS_ID_TOKEN_REQUEST_URL
    ACTIONS_ID_TOKEN_REQUEST_TOKEN

Prints the minted token on stdout. Everything else goes to stderr, so the
caller can capture stdout directly.
"""

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 30


def log(message: str) -> None:
    print(message, file=sys.stderr)


def get_json(request: urllib.request.Request, what: str) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        # The index returns a JSON body describing the failure; surface it,
        # because "which claim did not match" is the whole diagnostic.
        detail = error.read().decode("utf-8", "replace").strip()
        log(f"{what} failed: HTTP {error.code} {error.reason}")
        if detail:
            log(f"  response: {detail}")
        raise SystemExit(1)
    except urllib.error.URLError as error:
        log(f"{what} failed: could not reach {request.full_url} ({error.reason})")
        log(
            "  On an egress-locked runner this usually means the host is not allowlisted."
        )
        raise SystemExit(1)

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        log(f"{what} returned a non-JSON response:")
        log(f"  {body[:500]!r}")
        raise SystemExit(1)


def main(argv: list) -> int:
    if len(argv) != 2:
        log(f"usage: {os.path.basename(argv[0])} <index-base-url>")
        return 2
    index_base = argv[1].rstrip("/")

    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not request_url or not request_token:
        log("ACTIONS_ID_TOKEN_REQUEST_URL / _TOKEN are not set.")
        log("Add 'permissions: id-token: write' to the job.")
        return 1

    # Ask the index which audience it expects rather than hardcoding it, so the
    # same code works against PyPI ("pypi") and TestPyPI ("testpypi").
    audience = get_json(
        urllib.request.Request(f"{index_base}/_/oidc/audience"),
        f"Fetching the OIDC audience from {index_base}",
    ).get("audience")
    if not audience:
        log(f"{index_base} did not report an OIDC audience.")
        return 1
    log(f"Index expects OIDC audience '{audience}'.")

    # The identity in this token describes the workflow (repository, workflow
    # filename, environment, ref), not the machine, which is why this works
    # unchanged on a self-hosted runner.
    oidc_token = get_json(
        urllib.request.Request(
            f"{request_url}&audience={audience}",
            headers={"Authorization": f"bearer {request_token}"},
        ),
        "Requesting the GitHub OIDC token",
    ).get("value")
    if not oidc_token:
        log("GitHub returned no OIDC token value.")
        return 1
    log("Got a GitHub OIDC token.")

    payload = json.dumps({"token": oidc_token}).encode("utf-8")
    minted = get_json(
        urllib.request.Request(
            f"{index_base}/_/oidc/mint-token",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        ),
        "Exchanging the OIDC token for a PyPI token",
    )
    token = minted.get("token")
    if not token:
        # A 200 with no token should not happen, but fail loudly rather than
        # hand an empty password to twine.
        log(f"The index returned no token: {json.dumps(minted)}")
        return 1

    log("Minted a project-scoped PyPI token.")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
