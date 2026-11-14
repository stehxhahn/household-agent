# Techem dashboard notes

Context for working on `techem_dashboard.html` or extending `mcp_server.py` — written so a future session (Claude or otherwise) doesn't have to re-derive any of this.

## Setup

Dashboard: `techem_dashboard.html`, published as a Claude Artifact and committed to git. Data comes from the Techem MCP server (`mcp_server.py` / `techem.py`), which wraps Techem's resident GraphQL API (`techemadmin.dk/analytics/graphql`).

A single apartment in a multi-unit Danish building. The specific address is intentionally not in this repo — the Techem account identifier lives only in the gitignored `.env` (`TECHEM_OBJECT_ID`).

## Acconto

500 DKK/month heating, 250 DKK/month water, paid year-round. Settlement is **calendar-year** (Jan–Dec), not a rolling 12 months — this matters because Jan/Feb 2026 was by far the heaviest heating period and drives most of the year's over-acconto position. A dashboard that only looks at recent months will badly understate how far over acconto the year is running.

## Cost rates

Sourced from the real Q4 2025 Techem statements (two separate PDFs: "Koldtvandsudgifter" for water, "Varmeudgifter" for heat):

| Item | Rate | Billed to |
|---|---|---|
| Radiator heating | 1.624072 DKK / HCA unit | heating account |
| Hot-water heating energy | 113.316571 DKK / m³ | heating account (not water!) |
| Water supply | 55.835784 DKK / m³ | water account, applies to combined hot+cold volume |
| Fixed base fee + EED | 2,353.07 DKK / year | heating account, regardless of usage |

Hot water is billed twice: once for the energy to heat it (heating account) and once for the water itself (water account, same rate as cold). This is a real quirk of Danish district-heating billing, not a modeling choice.

## Bedroom radiator

One radiator's meter was replaced in mid-March 2026 (old/new serials are in Supabase's `radiator_adjustment` table, not this file). It sits in the most wind-exposed room and runs far hotter than the apartment's other 3 radiators (e.g. 384 units in January vs. 183–204 for the others). The administrator verbally agreed a 20% reduction on this radiator's billed units to compensate.

**This is not confirmed in any real bill yet.** The Q4 2025 bill predates the March swap so it can't confirm either way (checked directly — raw totals from that period don't cleanly match either a 0% or 20% reduction, consistent with the deal not applying yet). Per explicit instruction: **the dashboard's primary/headline numbers assume no reduction** (conservative — `RADIATOR_FACTOR_ACTIVE = 1.0` in the script). The 20%-discount scenario is shown only as a separate "if confirmed" comparison. Don't silently bake the 20% into headline numbers — re-verify against a real post-March-2026 bill first.

## Dashboard design preferences

Cost-minded user. Layout order: cost panels first, then heating (drives cost), then water (lowest priority) at the bottom. KPI deltas compare against acconto pace, not prior-period averages. Skip minor/non-actionable notices (e.g. "meters went flat for a few days" was explicitly removed — not useful).

## Per-radiator API technique (not yet in mcp_server.py)

`get_techem_usage` in `mcp_server.py` only exposes apartment-level totals. Techem's GraphQL schema has a `tenantTable` query with a `aggregationLevel` that goes one level deeper:

- `UNIT` — apartment total (same as the existing tool)
- `SOURCE` — **per-radiator/per-meter breakdown. Works for tenant-role logins.**
- `MPOINT` — individual meter serials/room names — **returns a "not-supported" error for tenant accounts**, apparently a deliberate permission restriction.

Minimal query (same login/JWT flow as `TechemClient` in `techem.py`):

```graphql
query TenantTable($table: TenantTableInput!) {
  tenantTable(table: $table) { rows { object { id } values } }
}
```
```json
{"table": {
  "objectId": "<TECHEM_OBJECT_ID>",
  "quantityDescriptors": [{"quantity": "hca"}],
  "periodBegin": "2026-01-01T00:00:00",
  "periodEnd": "2026-11-13T00:00:00",
  "aggregationLevel": "SOURCE"
}}
```

Each row's `object.id` is base64 of `p__<property>.u__<unit>.g__<group>`. The `g__<number>` suffix identifies one physical radiator consistently over time — including across a meter hardware swap: one source's readings stop and a new source's readings start the same month. That's how the bedroom radiator's meter replacement was identified, without ever seeing a serial number directly in the API response.

No `resolution` param on `tenantTable` (unlike `tenantGraph`) — to get a time series per radiator, loop the query over narrow date ranges (e.g. month by month).

If this is needed again, it's worth adding as a proper MCP tool (e.g. `get_techem_usage_by_radiator`) instead of re-deriving the query by hand.
