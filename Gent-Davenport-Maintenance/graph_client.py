"""
graph_client.py — Cosmos DB Gremlin connection helper for Davenport machine ontology.

Provides CRUD operations on graph vertices/edges and query-time traversal
for the v3 Graph RAG system.  Reusable across build_graph.py (population)
and function_app.py (query-time context).
"""

import os, json, logging
from datetime import datetime, timezone
from gremlin_python.driver import client as gremlin_client, serializer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_client():
    """Create and return a Gremlin client connected to Cosmos DB."""
    endpoint = os.environ["COSMOS_GREMLIN_ENDPOINT"]
    key = os.environ["COSMOS_GREMLIN_KEY"]
    database = os.environ["COSMOS_GREMLIN_DATABASE"]
    graph = os.environ["COSMOS_GREMLIN_GRAPH"]

    return gremlin_client.Client(
        url=endpoint,
        traversal_source="g",
        # Cosmos DB expects this exact format for the username
        username=f"/dbs/{database}/colls/{graph}",
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


# ---------------------------------------------------------------------------
# Vertex CRUD
# ---------------------------------------------------------------------------

def add_vertex(client, vertex_type, vertex_id, properties=None):
    """
    Add a vertex (upsert pattern — drops existing vertex with same id first).

    Args:
        client:      Gremlin client
        vertex_type: label (system, component, symptom, cause, fix)
        vertex_id:   unique string id
        properties:  dict of key-value pairs to set on the vertex
    """
    properties = properties or {}

    # Build the Gremlin query — Cosmos DB requires partition key as a property
    # Our partition key is /type, so we set .property('type', vertex_type)
    query = (
        "g.V(vertex_id).fold().coalesce("
        "  unfold(),"
        "  addV(label).property('id', vertex_id).property('type', vertex_type)"
        ")"
    )
    bindings = {
        "vertex_id": vertex_id,
        "label": vertex_type,
        "vertex_type": vertex_type,
    }

    # Add each property
    for key, value in properties.items():
        # Arrays get stored as comma-separated strings (Cosmos Gremlin limitation)
        if isinstance(value, list):
            value = json.dumps(value)
        query += f".property('{key}', {key}_val)"
        bindings[f"{key}_val"] = value

    # Always set tracking fields
    query += ".property('hit_count', 0).property('last_accessed', '')"

    result = client.submit(query, bindings).all().result()
    logger.info(f"add_vertex: {vertex_type}/{vertex_id}")
    return result


def add_edge(client, edge_label, from_id, to_id, properties=None):
    """
    Add an edge between two existing vertices.

    Args:
        client:     Gremlin client
        edge_label: relationship type (contains, caused_by, involves, fixed_by, etc.)
        from_id:    source vertex id
        to_id:      target vertex id
        properties: dict of key-value pairs on the edge
    """
    properties = properties or {}

    # Cosmos DB Gremlin: edges need both vertices to exist
    query = (
        "g.V(from_id).as('a')"
        ".V(to_id).as('b')"
        ".addE(edge_label).from('a').to('b')"
    )
    bindings = {
        "from_id": from_id,
        "to_id": to_id,
        "edge_label": edge_label,
    }

    for key, value in properties.items():
        query += f".property('{key}', {key}_val)"
        bindings[f"{key}_val"] = value

    result = client.submit(query, bindings).all().result()
    logger.info(f"add_edge: {from_id} --[{edge_label}]--> {to_id}")
    return result


def drop_all(client):
    """Remove all vertices and edges — use for rebuilding the graph from scratch."""
    result = client.submit("g.V().drop()").all().result()
    logger.info("drop_all: cleared graph")
    return result


# ---------------------------------------------------------------------------
# Query-time traversals (used by function_app.py at request time)
# ---------------------------------------------------------------------------

def query_causes(client, symptom_id):
    """
    Traverse from a symptom to its causes, ordered by priority.
    Uses simple separate queries (Cosmos DB Gremlin doesn't support complex coalesce/select).
    Returns list of dicts: [{cause_id, cause_desc, priority, category, component_id, component_name, fix_id, fix_desc}, ...]
    """
    # Step 1: Get causes with priority from caused_by edges
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

        # Step 2: Get cause vertex details
        cause_data = {}
        try:
            cv = client.submit(
                "g.V(cid).valueMap(true)", {"cid": cause_id}
            ).all().result()
            if cv:
                cause_data = cv[0]
        except Exception:
            pass

        # Step 3: Get component via involves edge
        comp_id = ""
        comp_name = ""
        try:
            comp_raw = client.submit(
                "g.V(cid).out('involves').valueMap(true)", {"cid": cause_id}
            ).all().result()
            if comp_raw:
                comp_id = _first(comp_raw[0].get("id", [""]))
                comp_name = _first(comp_raw[0].get("name", [""]))
        except Exception:
            pass

        # Step 4: Get fix via fixed_by edge
        fix_id = ""
        fix_desc = ""
        try:
            fix_raw = client.submit(
                "g.V(cid).out('fixed_by').valueMap(true)", {"cid": cause_id}
            ).all().result()
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


def query_components(client, system_id):
    """List all components belonging to a system, via 'contains' edges."""
    query = (
        "g.V(system_id).out('contains').valueMap(true)"
    )
    try:
        raw = client.submit(query, {"system_id": system_id}).all().result()
    except Exception as e:
        logger.warning(f"query_components failed for {system_id}: {e}")
        return []

    return [
        {
            "id": _first(v.get("id")),
            "name": _first(v.get("name", [""])),
            "description": _first(v.get("description", [""])),
        }
        for v in raw
    ]


def query_all_symptoms(client):
    """Return all symptom vertices — used for symptom classification matching."""
    query = "g.V().has('type', 'symptom').valueMap(true)"
    try:
        raw = client.submit(query).all().result()
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
# Graph context builder (main entry point for query-time enrichment)
# ---------------------------------------------------------------------------

def get_graph_context(client, symptom_id):
    """
    Build a formatted context string for a matched symptom.
    This gets injected into the agent's input to guide its search and answer.

    Returns a string like:
        KNOWN CAUSES for "Part is short" (in priority order):
        1. [Tooling] Cutoff ring on bar end — Fix: Adjust cutoff depth or resharpen
        2. [Work Holding] Feed finger tension low — Fix: Adjust spring pressure
        ...
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
# Usage tracking (called after response is sent, non-blocking)
# ---------------------------------------------------------------------------

def increment_hit_count(client, vertex_ids):
    """
    Increment hit_count and update last_accessed on a list of vertex IDs.
    Called asynchronously after a response — should never block the user.
    """
    now = datetime.now(timezone.utc).isoformat()
    for vid in vertex_ids:
        try:
            # Read current hit_count, then increment
            query = (
                "g.V(vid)"
                ".property('hit_count', g.V(vid).values('hit_count').math('_ + 1'))"
                ".property('last_accessed', now)"
            )
            # Simpler approach that works with Cosmos DB Gremlin
            query = (
                "g.V(vid).property('last_accessed', now)"
            )
            client.submit(query, {"vid": vid, "now": now}).all().result()

            # Separate query for incrementing — Cosmos DB doesn't support inline math
            count_raw = client.submit(
                "g.V(vid).values('hit_count')", {"vid": vid}
            ).all().result()
            current = count_raw[0] if count_raw else 0
            client.submit(
                "g.V(vid).property('hit_count', new_count)",
                {"vid": vid, "new_count": current + 1},
            ).all().result()

            logger.debug(f"increment_hit_count: {vid} -> {current + 1}")
        except Exception as e:
            # Never let analytics tracking break the user flow
            logger.warning(f"increment_hit_count failed for {vid}: {e}")


# ---------------------------------------------------------------------------
# Graph statistics (for admin dashboard / verification)
# ---------------------------------------------------------------------------

def get_stats(client):
    """Return vertex/edge counts by type/label for admin display."""
    stats = {}

    # Vertex counts by type
    try:
        raw = client.submit(
            "g.V().groupCount().by('type')"
        ).all().result()
        stats["vertices"] = raw[0] if raw else {}
    except Exception as e:
        stats["vertices"] = {"error": str(e)}

    # Edge counts by label
    try:
        raw = client.submit(
            "g.E().groupCount().by(label)"
        ).all().result()
        stats["edges"] = raw[0] if raw else {}
    except Exception as e:
        stats["edges"] = {"error": str(e)}

    # Total counts
    try:
        v_count = client.submit("g.V().count()").all().result()
        e_count = client.submit("g.E().count()").all().result()
        stats["total_vertices"] = v_count[0] if v_count else 0
        stats["total_edges"] = e_count[0] if e_count else 0
    except Exception as e:
        stats["totals_error"] = str(e)

    return stats


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


# ---------------------------------------------------------------------------
# Quick test — run directly to verify connection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    print("Connecting to Cosmos DB Gremlin...")
    c = get_client()

    print("Running test query: g.V().count()")
    result = c.submit("g.V().count()").all().result()
    print(f"Vertex count: {result}")

    print("\nGraph stats:")
    stats = get_stats(c)
    print(json.dumps(stats, indent=2, default=str))

    c.close()
    print("\nConnection test passed!")
