"""Print the role matrix for the demo.

Every seeded account is signed in and every dataset is queried once, so the
output shows exactly how much of each dataset each attribute set can decrypt.
This doubles as the smoke test for the whole role-based flow.

Usage::

    cd backend
    .venv/bin/python scripts/role_matrix_check.py                         # in-process
    .venv/bin/python scripts/role_matrix_check.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SLUG_WIDTH = 24
ACCOUNT_WIDTH = 26


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Query a running server instead of the in-process test client. Include the API "
            "prefix, for example http://127.0.0.1:8000/api or http://127.0.0.1:5173/api "
            "to check the Vite dev proxy."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with ExitStack() as stack:
        if args.base_url:
            import httpx

            client = stack.enter_context(httpx.Client(base_url=args.base_url, timeout=30))
            print(f"Checking {args.base_url}\n")
            prefix = ""
        else:
            from fastapi.testclient import TestClient

            from app.main import app

            client = stack.enter_context(TestClient(app))
            print("Checking the in-process application\n")
            prefix = "/api"

        health = client.get(f"{prefix}/health").json()
        print(
            f"crypto backend: {health['crypto_backend']} "
            f"(real encryption: {health['encrypted']})\n"
        )

        datasets = client.get(
            f"{prefix}/datasets", headers=_auth(client, "admin@demo.local", prefix)[1]
        ).json()["datasets"]
        slugs = [dataset["slug"] for dataset in datasets]

        header = f"{'account':<{ACCOUNT_WIDTH}} {'attribute set':<42} " + " ".join(
            f"{slug[:SLUG_WIDTH]:>{SLUG_WIDTH}}" for slug in slugs
        )
        print(header)
        print("-" * len(header))

        for account in client.get(f"{prefix}/catalog/demo-accounts").json()["accounts"]:
            token, headers = _auth(client, account["email"], prefix)
            if token is None:
                print(
                    f"{account['email']:<{ACCOUNT_WIDTH}} "
                    f"{'refused at sign-in (' + account['status'] + ')':<42}"
                )
                continue
            cells = []
            for slug in slugs:
                dataset_id = next(item["id"] for item in datasets if item["slug"] == slug)
                body = client.post(
                    f"{prefix}/query",
                    headers=headers,
                    json={"dataset_id": dataset_id, "limit": 1},
                ).json()
                totals = body["totals"]
                cells.append(f"{totals['granted']}>{totals['denied']:<5}"[:SLUG_WIDTH].rjust(SLUG_WIDTH))
            print(
                f"{account['email']:<{ACCOUNT_WIDTH}} "
                f"{', '.join(account['attributes'])[:42]:<42} "
                + " ".join(cells)
            )

        print("\ngranted>denied per dataset. Attribute sets decide record-level access;")
        print("roles only guard /api/audit and /api/admin/*.")
        print("\nTry the live change: PATCH /api/admin/users/<id> to add dept:radiology to")
        print("dr.okafor@demo.local, then re-run this script.")
    return 0


def _auth(client, email: str, prefix: str):
    """Sign in, returning ``(token, headers)`` or ``(None, None)`` if refused."""

    response = client.post(
        f"{prefix}/auth/login", json={"email": email, "password": "demo1234"}
    )
    if response.status_code != 200:
        return None, None
    token = response.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


if __name__ == "__main__":
    raise SystemExit(main())
