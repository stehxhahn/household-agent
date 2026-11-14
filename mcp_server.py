#!/usr/bin/env python3
"""MCP server exposing Techem (app.techem.dk) consumption data as tools."""

import datetime as dt
import os
import sys

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from techem import TechemClient

load_dotenv()

EMAIL = os.environ.get("TECHEM_EMAIL")
PASSWORD = os.environ.get("TECHEM_PASSWORD")
OBJECT_ID = os.environ.get("TECHEM_OBJECT_ID")

if not all([EMAIL, PASSWORD, OBJECT_ID]):
    print(
        "Missing TECHEM_EMAIL / TECHEM_PASSWORD / TECHEM_OBJECT_ID in .env",
        file=sys.stderr,
    )
    sys.exit(1)

KNOWN_QUANTITIES = ["hca", "hot-water-volume", "cold-water-volume"]

mcp = MCPServer("techem")
_client = TechemClient(EMAIL, PASSWORD, OBJECT_ID)


@mcp.tool()
def get_techem_usage(days: int = 30, quantities: list = None, resolution: str = "DAY") -> dict:
    """Fetch Techem utility consumption data (heating, hot water, cold water).

    Args:
        days: how many days back from today to fetch.
        quantities: which meters to include. Defaults to all three:
            "hca" (heating/radiator units), "hot-water-volume", "cold-water-volume".
        resolution: bucket size - "DAY", "WEEK", or "MONTH".
    """
    quantities = quantities or KNOWN_QUANTITIES
    period_end = dt.datetime.now()
    period_begin = period_end - dt.timedelta(days=days)

    data = _client.get_usage(period_begin, period_end, quantities, resolution)

    result = {}
    timestamps = data["timestamps"]
    for graph in data["graphs"]:
        consumption = graph.get("consumption") or {}
        quantity = (consumption.get("quantityDescriptor") or {}).get("quantity", graph.get("type", "unknown"))
        values = consumption.get("values") or []
        result[quantity] = dict(zip(timestamps, values))

    return result


if __name__ == "__main__":
    mcp.run()
