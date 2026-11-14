#!/usr/bin/env python3
"""CLI for pulling consumption data from the Techem resident portal (app.techem.dk).

Reverse-engineered from the app's GraphQL API (techemadmin.dk/analytics/graphql).
Credentials and your objectId (unit identifier) go in a local .env file - see .env.example.
"""

import argparse
import datetime as dt
import json
import os
import sys

import requests
from dotenv import load_dotenv

GRAPHQL_URL = "https://techemadmin.dk/analytics/graphql"

# The endpoint sits behind a WAF that rejects requests lacking browser-like headers.
COMMON_HEADERS = {
    "Accept": "application/graphql-response+json, application/json",
    "Content-Type": "application/json",
    "Origin": "https://app.techem.dk",
    "Referer": "https://app.techem.dk/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/27.2 Safari/605.1.15"
    ),
}

LOGIN_QUERY = """
mutation nucleolusLogin($credentials: CredentialsInput!) {
  loginWithEmailAndPassword(credentials: $credentials) {
    ok {
      token
      refreshToken
    }
  }
}
"""

TENANT_GRAPH_QUERY = """
query TenantGraph($graph: TenantGraphInput!) {
  tenantGraph(graph: $graph) {
    timestamps
    graphs {
      type
      consumption {
        quantityDescriptor {
          quantity
        }
        values
      }
    }
  }
}
"""


class TechemClient:
    def __init__(self, email: str, password: str, object_id: str):
        self.email = email
        self.password = password
        self.object_id = object_id
        self._session = requests.Session()
        self._token = None

    def login(self) -> str:
        resp = self._session.post(
            GRAPHQL_URL,
            json={
                "query": LOGIN_QUERY,
                "variables": {
                    "credentials": {
                        "username": self.email,
                        "password": self.password,
                        "targetResource": "tenant",
                    }
                },
                "operationName": "nucleolusLogin",
            },
            headers=COMMON_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"Login failed: {payload['errors']}")
        result = payload["data"]["loginWithEmailAndPassword"].get("ok")
        if not result:
            raise RuntimeError(f"Login rejected: {payload['data']['loginWithEmailAndPassword']}")
        self._token = result["token"]
        return self._token

    def _post_graph_query(self, variables: dict) -> requests.Response:
        return self._session.post(
            GRAPHQL_URL,
            json={
                "query": TENANT_GRAPH_QUERY,
                "variables": variables,
                "operationName": "TenantGraph",
            },
            headers={**COMMON_HEADERS, "Authorization": f"JWT {self._token}"},
            timeout=15,
        )

    def get_usage(
        self,
        period_begin: dt.datetime,
        period_end: dt.datetime,
        quantities: list,
        resolution: str = "DAY",
    ) -> dict:
        if not self._token:
            self.login()

        series = [
            {"quantityDescriptor": {"quantity": q, "normalized": False}}
            for q in quantities
        ]
        variables = {
            "graph": {
                "periodBegin": period_begin.strftime("%Y-%m-%dT%H:%M:%S"),
                "periodEnd": period_end.strftime("%Y-%m-%dT%H:%M:%S"),
                "resolution": resolution,
                "consumption": {"series": series},
                "objectId": self.object_id,
            }
        }

        resp = self._post_graph_query(variables)
        if resp.status_code == 401:
            # tokens are short-lived (~5 min) - re-login and retry once
            self.login()
            resp = self._post_graph_query(variables)

        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"Query failed: {payload['errors']}")
        return payload["data"]["tenantGraph"]


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch consumption data from Techem's resident portal.")
    parser.add_argument("--days", type=int, default=30, help="Number of days back to fetch (default: 30)")
    parser.add_argument(
        "--quantity",
        action="append",
        dest="quantities",
        help=(
            "Quantity to fetch (repeatable). Default: hca, hot-water-volume, cold-water-volume "
            "(heating/radiator units, hot water, cold water)."
        ),
    )
    parser.add_argument(
        "--resolution", default="DAY", choices=["DAY", "WEEK", "MONTH"], help="Bucket resolution"
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a table")
    return parser.parse_args()


def main():
    load_dotenv()
    email = os.environ.get("TECHEM_EMAIL")
    password = os.environ.get("TECHEM_PASSWORD")
    object_id = os.environ.get("TECHEM_OBJECT_ID")

    missing = [
        name
        for name, val in [
            ("TECHEM_EMAIL", email),
            ("TECHEM_PASSWORD", password),
            ("TECHEM_OBJECT_ID", object_id),
        ]
        if not val
    ]
    if missing:
        print(
            f"Missing required env vars: {', '.join(missing)}. Copy .env.example to .env and fill them in.",
            file=sys.stderr,
        )
        sys.exit(1)

    args = parse_args()
    quantities = args.quantities or ["hca", "hot-water-volume", "cold-water-volume"]

    period_end = dt.datetime.now()
    period_begin = period_end - dt.timedelta(days=args.days)

    client = TechemClient(email, password, object_id)
    try:
        data = client.get_usage(period_begin, period_end, quantities, args.resolution)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, indent=2))
        return

    timestamps = data["timestamps"]
    for graph in data["graphs"]:
        consumption = graph.get("consumption") or {}
        quantity = (consumption.get("quantityDescriptor") or {}).get("quantity", graph.get("type", "unknown"))
        values = consumption.get("values") or []
        print(f"\n=== {quantity} ({graph.get('type')}) ===")
        for ts, val in zip(timestamps, values):
            print(f"{ts}\t{val}")


if __name__ == "__main__":
    main()
