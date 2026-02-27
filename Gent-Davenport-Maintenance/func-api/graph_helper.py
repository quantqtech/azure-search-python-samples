"""
graph_helper.py — Query-time graph functions for the Function App (V3 Graph RAG).

Slim version of graph_client.py containing only what's needed at request time:
connection, symptom queries, context building, and usage tracking.
Build-time CRUD functions live in the parent directory's graph_client.py.
"""

import os, json, logging
from datetime import datetime, timezone
from gremlin_python.driver import client as gremlin_client, serializer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_client():
    """Create and return a Gremlin client connected to Cosmos DB.
    Raises KeyError if COSMOS_GREMLIN_* env vars are missing.
    """
    endpoint = os.environ["COSMOS_GREMLIN_ENDPOINT"]
    key = os.environ["COSMOS_GREMLIN_KEY"]
    database = os.environ["COSMOS_GREMLIN_DATABASE"]
    graph = os.environ["COSMOS_GREMLIN_GRAPH"]

    return gremlin_client.Client(
        url=endpoint,
        traversal_source="g",
        username=f"/dbs/{database}/colls/{graph}",
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


# ---------------------------------------------------------------------------
# Query-time traversals
# ---------------------------------------------------------------------------

def query_causes(client, symptom_id):
    """
    Traverse from a symptom to its causes, ordered by priority.
    Uses simple separate queries (Cosmos DB Gremlin doesn't support complex coalesce/select).
    """
    try:
        raw = client.submit(
            "g.V(symptom_id).outE('caused_by').order().by('priority')"
            ".project('priority','cause_id')"
            ".by('priority')"
            ".by(inV().id())",
            {"symptom_id": symptom_id},
        ).all().result()
    except Exception as e:
        logger.warning(f"query_causes failed for {symptom_id}: {e}")
        return []

    if not raw:
        return []

    results = []
    for row in raw:
        cause_id = row.get("cause_id", "")
        priority = row.get("priority", 99)

        # Get cause vertex details
        cause_data = {}
        try:
            cv = client.submit("g.V(cid).valueMap(true)", {"cid": cause_id}).all().result()
            if cv:
                cause_data = cv[0]
        except Exception:
            pass

        # Get component via involves edge
        comp_id, comp_name = "", ""
        try:
            comp_raw = client.submit("g.V(cid).out('involves').valueMap(true)", {"cid": cause_id}).all().result()
            if comp_raw:
                comp_id = _first(comp_raw[0].get("id", [""]))
                comp_name = _first(comp_raw[0].get("name", [""]))
        except Exception:
            pass

        # Get fix via fixed_by edge
        fix_id, fix_desc = "", ""
        try:
            fix_raw = client.submit("g.V(cid).out('fixed_by').valueMap(true)", {"cid": cause_id}).all().result()
            if fix_raw:
                fix_id = _first(fix_raw[0].get("id", [""]))
                fix_desc = _first(fix_raw[0].get("description", [""]))
        except Exception:
            pass

        results.append({
            "cause_id": cause_id,
            "cause_desc": _first(cause_data.get("description", [""])),
            "priority": priority,
            "category": _first(cause_data.get("category", [""])),
            "component_id": comp_id,
            "component_name": comp_name,
            "fix_id": fix_id,
            "fix_desc": fix_desc,
        })

    return results


def query_all_symptoms(client):
    """Return all symptom vertices — used for symptom classification matching."""
    try:
        raw = client.submit("g.V().has('type', 'symptom').valueMap(true)").all().result()
    except Exception as e:
        logger.warning(f"query_all_symptoms failed: {e}")
        return []

    return [
        {
            "id": _first(v.get("id")),
            "name": _first(v.get("name", [""])),
            "description": _first(v.get("description", [""])),
            "aliases": _parse_json_list(v.get("aliases", ["[]"])),
        }
        for v in raw
    ]


# ---------------------------------------------------------------------------
# Graph context builder
# ---------------------------------------------------------------------------

def get_graph_context(client, symptom_id):
    """
    Build a formatted diagnostic checklist for a matched symptom.
    Injected into the agent's input to guide its search and answer.
    """
    causes = query_causes(client, symptom_id)
    if not causes:
        return ""

    lines = [f'KNOWN CAUSES for symptom "{symptom_id}" (in diagnostic priority order):']
    for i, c in enumerate(causes, 1):
        category = f"[{c['category']}] " if c["category"] else ""
        fix_text = f" — Fix: {c['fix_desc']}" if c["fix_desc"] else ""
        comp_text = f" (component: {c['component_name']})" if c["component_name"] else ""
        lines.append(f"  {i}. {category}{c['cause_desc']}{comp_text}{fix_text}")

    lines.append("")
    lines.append("Use this as a diagnostic checklist. Search for document evidence for each cause.")
    lines.append("Include causes from this list even if search results don't mention them directly.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Usage tracking (fire-and-forget after response)
# ---------------------------------------------------------------------------

def increment_hit_count(client, vertex_ids):
    """Increment hit_count and update last_accessed. Never blocks the user."""
    now = datetime.now(timezone.utc).isoformat()
    for vid in vertex_ids:
        try:
            # Update last_accessed
            client.submit("g.V(vid).property('last_accessed', now)", {"vid": vid, "now": now}).all().result()
            # Read + increment hit_count (Cosmos DB doesn't support inline math)
            count_raw = client.submit("g.V(vid).values('hit_count')", {"vid": vid}).all().result()
            current = count_raw[0] if count_raw else 0
            client.submit("g.V(vid).property('hit_count', new_count)", {"vid": vid, "new_count": current + 1}).all().result()
        except Exception as e:
            logger.warning(f"increment_hit_count failed for {vid}: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first(value):
    """Cosmos DB Gremlin returns property values as lists — grab the first element."""
    if isinstance(value, list) and value:
        return value[0]
    return value


def _parse_json_list(value):
    """Parse a JSON-encoded list stored as a string property."""
    raw = _first(value)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return [raw] if raw else []
    return raw if isinstance(raw, list) else []
