"""
graph_helper.py — Query-time graph functions for the Function App (V3 Graph RAG).

Slim version of graph_client.py containing only what's needed at request time:
connection, symptom queries, context building, and usage tracking.
Build-time CRUD functions live in the parent directory's graph_client.py.
"""

import os, json, logging
from datetime import datetime, timezone
import nest_asyncio
nest_asyncio.apply()  # gremlinpython runs its own event loop; Azure Functions already has one
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
# World model (Layer 1 — always-present structural summary)
# ---------------------------------------------------------------------------

# Cap per system to keep the world model compact (~400-600 tokens total)
MAX_COMPONENTS_PER_SYSTEM = 6


def query_all_systems(client):
    """Return all system vertices — used for building the world model."""
    try:
        raw = client.submit("g.V().has('type', 'system').valueMap(true)").all().result()
    except Exception as e:
        logger.warning(f"query_all_systems failed: {e}")
        return []

    return [
        {
            "id": _first(v.get("id")),
            "name": _first(v.get("name", [""])),
            "description": _first(v.get("description", [""])),
        }
        for v in raw
    ]


def query_components(client, system_id):
    """List all components belonging to a system, via 'contains' edges."""
    try:
        raw = client.submit(
            "g.V(system_id).out('contains').valueMap(true)",
            {"system_id": system_id},
        ).all().result()
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


def query_key_relationships(client):
    """Return connects_to and drives edges for the world model's relationship section.

    Returns a list of (from_name, edge_type, to_name, description) tuples.
    Capped to avoid overwhelming the summary.
    """
    try:
        # Get connects_to and drives edges with vertex names
        raw = client.submit(
            "g.E().hasLabel('connects_to','drives')"
            ".project('from_name','label','to_name','desc')"
            ".by(outV().values('name'))"
            ".by(label)"
            ".by(inV().values('name'))"
            ".by(coalesce(values('description'), constant('')))"
        ).all().result()
    except Exception as e:
        logger.warning(f"query_key_relationships failed: {e}")
        return []

    return [
        {
            "from_name": r.get("from_name", ""),
            "label": r.get("label", ""),
            "to_name": r.get("to_name", ""),
            "description": r.get("desc", ""),
        }
        for r in raw
    ]


def build_world_model(client):
    """Build a compact structural summary of the Davenport machine from the graph.

    This is Layer 1 of the V3 Graph RAG — orientation, not encyclopedia.
    Tells the LLM what systems exist, their key components, and how they connect.
    Explicitly signals "search for details" to avoid the LLM treating this as complete.

    Returns a formatted string (~400-600 tokens) or empty string if graph is empty.
    """
    systems = query_all_systems(client)
    if not systems:
        return ""

    lines = [
        "DAVENPORT MODEL B — MACHINE OVERVIEW "
        "(structural summary — search knowledge base for details):",
        "",
        "Systems and key components:",
    ]

    for sys in sorted(systems, key=lambda s: s["name"]):
        components = query_components(client, sys["id"])
        comp_names = [c["name"] for c in components if c["name"]]

        # Cap component list and signal there's more
        if len(comp_names) > MAX_COMPONENTS_PER_SYSTEM:
            shown = ", ".join(comp_names[:MAX_COMPONENTS_PER_SYSTEM])
            lines.append(f"  {sys['name']}: {shown}, ... ({len(comp_names)} total)")
        elif comp_names:
            lines.append(f"  {sys['name']}: {', '.join(comp_names)}")
        else:
            lines.append(f"  {sys['name']}")

    # Add key mechanical relationships (connects_to, drives)
    relationships = query_key_relationships(client)
    if relationships:
        lines.append("")
        lines.append("Key mechanical relationships:")
        # Show a representative sample — cap at ~10 to keep it compact
        shown_rels = relationships[:10]
        for r in shown_rels:
            desc = f" — {r['description']}" if r["description"] else ""
            verb = "drives" if r["label"] == "drives" else "connects to"
            lines.append(f"  - {r['from_name']} {verb} {r['to_name']}{desc}")
        if len(relationships) > 10:
            lines.append(f"  ... and {len(relationships) - 10} more relationships")

    lines.append("")
    lines.append(
        "NOTE: This is a structural overview only. Each system has additional "
        "components and detailed procedures in the knowledge base. Always search "
        "for specifics."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph context builder (Layer 2 — conditional diagnostic checklist)
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
# Graph visualization (sidebar diagnostic tree for the frontend)
# ---------------------------------------------------------------------------

def build_graph_viz(client, symptom_id):
    """Build a vis.js-ready node/edge structure for a matched symptom.

    Reuses query_causes() which already traverses symptom → causes → components/fixes.
    Returns a dict with nodes, edges, and symptom_name for the frontend, or None if empty.
    """
    # Get symptom vertex details
    try:
        sym_raw = client.submit(
            "g.V(sid).valueMap(true)", {"sid": symptom_id}
        ).all().result()
    except Exception as e:
        logger.warning(f"build_graph_viz symptom lookup failed for {symptom_id}: {e}")
        return None

    if not sym_raw:
        return None

    symptom_name = _first(sym_raw[0].get("name", [symptom_id]))
    symptom_desc = _first(sym_raw[0].get("description", [""]))

    # Reuse the existing cause traversal (already handles all the Cosmos DB quirks)
    causes = query_causes(client, symptom_id)
    if not causes:
        return None

    nodes = []
    edges = []
    seen_components = set()  # deduplicate component nodes

    # Symptom node (root of the tree)
    nodes.append({
        "id": symptom_id,
        "name": symptom_name,
        "description": symptom_desc,
        "type": "symptom",
    })

    for c in causes:
        # Cause node
        nodes.append({
            "id": c["cause_id"],
            "name": c["cause_desc"][:60] + ("..." if len(c["cause_desc"]) > 60 else ""),
            "description": c["cause_desc"],
            "type": "cause",
            "category": c["category"],
            "fix_desc": c["fix_desc"],
        })

        # Edge: symptom → cause (with priority label)
        edges.append({
            "from_id": symptom_id,
            "to_id": c["cause_id"],
            "label": f"P{c['priority']}" if c["priority"] else "",
            "priority": c["priority"],
        })

        # Component node (deduplicated — multiple causes can involve same component)
        if c["component_id"] and c["component_id"] not in seen_components:
            seen_components.add(c["component_id"])
            nodes.append({
                "id": c["component_id"],
                "name": c["component_name"] or c["component_id"],
                "description": "",
                "type": "component",
            })

        # Edge: cause → component
        if c["component_id"]:
            edges.append({
                "from_id": c["cause_id"],
                "to_id": c["component_id"],
                "label": "",
                "priority": None,
            })

    return {
        "symptom_name": symptom_name,
        "nodes": nodes,
        "edges": edges,
    }


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
