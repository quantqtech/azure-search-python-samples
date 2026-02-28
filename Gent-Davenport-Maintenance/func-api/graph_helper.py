"""
graph_helper.py — Query-time graph functions for the Function App (V3 Graph RAG).

Slim version of graph_client.py containing only what's needed at request time:
connection, world model building, component graph visualization, and usage tracking.
Build-time CRUD functions live in the parent directory's graph_client.py.
"""

import os, logging
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


def query_component_by_name(client, component_name):
    """Find a component vertex by fuzzy name match. Returns (id, name, description) or None.

    Searches for exact case-insensitive match first, then substring containment.
    """
    try:
        # Get all component vertices — small graph, simpler than Gremlin text predicates
        raw = client.submit("g.V().has('type', 'component').valueMap(true)").all().result()
    except Exception as e:
        logger.warning(f"query_component_by_name failed: {e}")
        return None

    name_lower = component_name.lower()

    # Pass 1: exact match (case-insensitive)
    for v in raw:
        vid = _first(v.get("id"))
        vname = _first(v.get("name", [""]))
        if vname.lower() == name_lower:
            return {"id": vid, "name": vname, "description": _first(v.get("description", [""]))}

    # Pass 2: component name contains the search term or vice versa
    for v in raw:
        vid = _first(v.get("id"))
        vname = _first(v.get("name", [""]))
        if name_lower in vname.lower() or vname.lower() in name_lower:
            return {"id": vid, "name": vname, "description": _first(v.get("description", [""]))}

    return None


def query_all_components(client):
    """Return all component vertices — used for component classification matching."""
    try:
        raw = client.submit("g.V().has('type', 'component').valueMap(true)").all().result()
    except Exception as e:
        logger.warning(f"query_all_components failed: {e}")
        return []

    return [
        {
            "id": _first(v.get("id")),
            "name": _first(v.get("name", [""])),
            "description": _first(v.get("description", [""])),
        }
        for v in raw
    ]


def build_component_graph_viz(client, component_id):
    """Build a vis.js-ready node/edge structure centered on a component.

    World model only — shows the component's structural context:
    - Parent system (via reverse 'contains' edge)
    - Sibling components (other components under same parent system)
    - Connected components (via 'connects_to' and 'drives' edges, both directions)

    NO symptoms or causes — those come from docs via RAG, not the graph.

    Returns a dict with nodes, edges, and component_name for the frontend, or None.
    """
    # Get component vertex details
    try:
        comp_raw = client.submit(
            "g.V(cid).valueMap(true)", {"cid": component_id}
        ).all().result()
    except Exception as e:
        logger.warning(f"build_component_graph_viz failed for {component_id}: {e}")
        return None

    if not comp_raw:
        return None

    comp_name = _first(comp_raw[0].get("name", [component_id]))
    comp_desc = _first(comp_raw[0].get("description", [""]))

    nodes = []
    edges = []
    seen_ids = {component_id}  # track added node IDs to deduplicate
    parent_system_ids = []  # track parent system IDs for sibling lookup

    # Root node: the component itself
    nodes.append({
        "id": component_id,
        "name": comp_name,
        "description": comp_desc,
        "type": "component",
    })

    # Parent system (component ← system via 'contains')
    try:
        sys_raw = client.submit(
            "g.V(cid).in('contains').valueMap(true)", {"cid": component_id}
        ).all().result()
        for s in sys_raw:
            sid = _first(s.get("id"))
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                parent_system_ids.append(sid)
                nodes.append({
                    "id": sid,
                    "name": _first(s.get("name", [""])),
                    "description": _first(s.get("description", [""])),
                    "type": "system",
                })
                edges.append({
                    "from_id": sid,
                    "to_id": component_id,
                    "label": "contains",
                    "priority": None,
                })
    except Exception:
        pass

    # Sibling components — other components under the same parent system
    for sid in parent_system_ids:
        try:
            sib_raw = client.submit(
                "g.V(sys_id).out('contains').has('type','component').valueMap(true)",
                {"sys_id": sid},
            ).all().result()
            for sib in sib_raw:
                sib_id = _first(sib.get("id"))
                if sib_id and sib_id not in seen_ids:
                    seen_ids.add(sib_id)
                    nodes.append({
                        "id": sib_id,
                        "name": _first(sib.get("name", [""])),
                        "description": _first(sib.get("description", [""])),
                        "type": "component",
                    })
                    edges.append({
                        "from_id": sid,
                        "to_id": sib_id,
                        "label": "contains",
                        "priority": None,
                    })
        except Exception:
            pass

    # Outgoing connections: component → other components via connects_to / drives
    try:
        out_raw = client.submit(
            "g.V(cid).outE('connects_to','drives')"
            ".project('label','to_id','to_name','to_desc','desc')"
            ".by(label)"
            ".by(inV().id())"
            ".by(inV().values('name'))"
            ".by(coalesce(inV().values('description'), constant('')))"
            ".by(coalesce(values('description'), constant('')))",
            {"cid": component_id},
        ).all().result()
        for r in out_raw:
            tid = r.get("to_id", "")
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                nodes.append({
                    "id": tid,
                    "name": r.get("to_name", ""),
                    "description": r.get("to_desc", ""),
                    "type": "component",
                })
            if tid:
                edges.append({
                    "from_id": component_id,
                    "to_id": tid,
                    "label": r.get("label", ""),
                    "priority": None,
                })
    except Exception:
        pass

    # Incoming connections: other components → this component via connects_to / drives
    try:
        in_raw = client.submit(
            "g.V(cid).inE('connects_to','drives')"
            ".project('label','from_id','from_name','from_desc')"
            ".by(label)"
            ".by(outV().id())"
            ".by(outV().values('name'))"
            ".by(coalesce(outV().values('description'), constant('')))",
            {"cid": component_id},
        ).all().result()
        for r in in_raw:
            fid = r.get("from_id", "")
            if fid and fid not in seen_ids:
                seen_ids.add(fid)
                nodes.append({
                    "id": fid,
                    "name": r.get("from_name", ""),
                    "description": r.get("from_desc", ""),
                    "type": "component",
                })
            if fid:
                edges.append({
                    "from_id": fid,
                    "to_id": component_id,
                    "label": r.get("label", ""),
                    "priority": None,
                })
    except Exception:
        pass

    # Only return if we found connections beyond the root node
    if len(nodes) < 2:
        return None

    return {
        "component_name": comp_name,
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Symptom traversal (Layer 2 — diagnostic context)
# ---------------------------------------------------------------------------

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


def query_causes(client, symptom_id):
    """Traverse symptom → causes (priority-ordered) → components + fixes.

    Uses separate queries because Cosmos DB Gremlin doesn't support
    complex coalesce/select in a single traversal.

    Returns: [{cause_id, cause_desc, priority, category, component_id, component_name, fix_id, fix_desc}]
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


def build_symptom_context(client, symptom_id):
    """Build diagnostic checklist for a matched symptom (Layer 2).

    Traverses symptom → causes (priority-ordered) → components + fixes.
    Returns a formatted string for injection into the agent prompt.
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


def build_component_context(client, component_id):
    """Build structural context for a matched component (Layer 2).

    Traverses 1-2 hops from the component: parent system, siblings,
    connected components. For non-diagnostic questions where knowing
    the component's neighborhood helps the agent search better.

    Returns a formatted string for injection into the agent prompt.
    """
    # Get component details
    try:
        comp_raw = client.submit("g.V(cid).valueMap(true)", {"cid": component_id}).all().result()
    except Exception as e:
        logger.warning(f"build_component_context failed for {component_id}: {e}")
        return ""

    if not comp_raw:
        return ""

    comp_name = _first(comp_raw[0].get("name", [component_id]))
    comp_desc = _first(comp_raw[0].get("description", [""]))

    lines = [f'COMPONENT CONTEXT for "{comp_name}":']
    if comp_desc:
        lines.append(f"  Description: {comp_desc}")

    # Parent system
    try:
        sys_raw = client.submit("g.V(cid).in('contains').valueMap(true)", {"cid": component_id}).all().result()
        if sys_raw:
            sys_name = _first(sys_raw[0].get("name", [""]))
            lines.append(f"  Part of system: {sys_name}")

            # Sibling components in same system
            sys_id = _first(sys_raw[0].get("id"))
            sib_raw = client.submit(
                "g.V(sys_id).out('contains').has('type','component').valueMap(true)",
                {"sys_id": sys_id},
            ).all().result()
            siblings = [_first(s.get("name", [""])) for s in sib_raw
                        if _first(s.get("id")) != component_id]
            if siblings:
                lines.append(f"  Sibling components: {', '.join(siblings[:8])}")
    except Exception:
        pass

    # Connected components (outgoing)
    connections = []
    try:
        out_raw = client.submit(
            "g.V(cid).outE('connects_to','drives')"
            ".project('label','to_name','desc')"
            ".by(label).by(inV().values('name'))"
            ".by(coalesce(values('description'), constant('')))",
            {"cid": component_id},
        ).all().result()
        for r in out_raw:
            verb = "drives" if r.get("label") == "drives" else "connects to"
            desc = f" ({r['desc']})" if r.get("desc") else ""
            connections.append(f"{comp_name} {verb} {r.get('to_name', '?')}{desc}")
    except Exception:
        pass

    # Connected components (incoming)
    try:
        in_raw = client.submit(
            "g.V(cid).inE('connects_to','drives')"
            ".project('label','from_name','desc')"
            ".by(label).by(outV().values('name'))"
            ".by(coalesce(values('description'), constant('')))",
            {"cid": component_id},
        ).all().result()
        for r in in_raw:
            verb = "drives" if r.get("label") == "drives" else "connects to"
            desc = f" ({r['desc']})" if r.get("desc") else ""
            connections.append(f"{r.get('from_name', '?')} {verb} {comp_name}{desc}")
    except Exception:
        pass

    if connections:
        lines.append("  Connections:")
        for c in connections:
            lines.append(f"    - {c}")

    lines.append("")
    lines.append("Use this structural context to guide your search. "
                  "Related components and connections often share maintenance procedures.")

    # Only return if we have useful context beyond just the name
    if len(lines) <= 3:
        return ""

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
    """Parse a JSON-encoded list stored as a string property (Cosmos DB limitation)."""
    import json
    raw = _first(value)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return [raw] if raw else []
    return raw if isinstance(raw, list) else []
