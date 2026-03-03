"""
graph_helper.py — Query-time graph functions for the Function App (V3 Graph RAG).

Slim version of graph_client.py containing only what's needed at request time:
connection, world model (Layer 1), generic traversal (Layer 2), and usage tracking.
Build-time CRUD functions live in the parent directory's graph_client.py.

Layer 2 architecture: ONE generic traversal, TWO outputs.
  classify_graph_nodes() → 1-3 starting vertex IDs (any type)
  traverse_neighborhood() → walk 1-2 hops outward → collect nodes + edges
  build_graph_context() → serialize as text for agent prompt
  build_graph_viz() → serialize as vis.js nodes/edges for sidebar
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
    """Build a lean structural summary of the Davenport machine from the graph.

    Layer 1 of V3 Graph RAG — orientation only, not a catalog.
    Just tells the LLM what systems exist so it knows the machine's structure.
    Component details and relationships come from Layer 2 traversal when relevant.

    Returns a formatted string (~50-80 tokens) or empty string if graph is empty.
    """
    systems = query_all_systems(client)
    if not systems:
        return ""

    system_names = sorted(s["name"] for s in systems if s.get("name"))
    return (
        "DAVENPORT MODEL B SYSTEMS "
        "(search knowledge base for component details and procedures): "
        + ", ".join(system_names) + "."
    )


# ---------------------------------------------------------------------------
# Layer 2: Generic graph traversal (one traversal → agent context + sidebar)
# ---------------------------------------------------------------------------

def traverse_neighborhood(client, vertex_ids, max_hops=2):
    """Walk outward from starting vertices, collecting all nodes and edges.

    This is the core of Layer 2 — one generic traversal that works for any
    vertex type (symptom, component, system, etc.). The graph structure
    determines what's relevant, not our routing code.

    Each node includes a 'hop' field: 0 = starting node, 1 = direct neighbor, etc.
    Agent context uses all hops; sidebar viz can filter to fewer hops.

    Returns (nodes_dict, edges_list):
      nodes_dict: {id → {id, name, type, description, hop, ...}}
      edges_list: [{from_id, to_id, label, priority}]
    """
    seen_nodes = {}      # id → node dict
    seen_edge_keys = set()  # "from|to|label" dedup keys
    edges = []
    frontier = set(vertex_ids)

    for hop in range(max_hops):
        next_frontier = set()
        for vid in frontier:
            # Fetch vertex details if we haven't seen this node yet
            if vid not in seen_nodes:
                try:
                    raw = client.submit("g.V(vid).valueMap(true)", {"vid": vid}).all().result()
                    if raw:
                        v = raw[0]
                        seen_nodes[vid] = {
                            "id": vid,
                            "name": _first(v.get("name", [vid])),
                            "type": _first(v.get("type", [""])),
                            "description": _first(v.get("description", [""])),
                            "category": _first(v.get("category", [""])),
                            "aliases": _parse_json_list(v.get("aliases", ["[]"])),
                            "hop": hop,  # distance from starting nodes
                        }
                    else:
                        continue  # vertex doesn't exist — skip
                except Exception as e:
                    logger.warning(f"traverse_neighborhood vertex fetch failed for {vid}: {e}")
                    continue

            # Fetch all outgoing edges
            try:
                out_raw = client.submit(
                    "g.V(vid).outE()"
                    ".project('label','to_id','priority')"
                    ".by(label)"
                    ".by(inV().id())"
                    ".by(coalesce(values('priority'), constant(0)))",
                    {"vid": vid},
                ).all().result()
                for r in out_raw:
                    to_id = r.get("to_id", "")
                    label = r.get("label", "")
                    edge_key = f"{vid}|{to_id}|{label}"
                    if edge_key not in seen_edge_keys:
                        seen_edge_keys.add(edge_key)
                        edges.append({
                            "from_id": vid,
                            "to_id": to_id,
                            "label": label,
                            "priority": r.get("priority", 0) or None,
                        })
                    if to_id not in seen_nodes:
                        next_frontier.add(to_id)
            except Exception as e:
                logger.warning(f"traverse_neighborhood outE failed for {vid}: {e}")

            # Fetch all incoming edges
            try:
                in_raw = client.submit(
                    "g.V(vid).inE()"
                    ".project('label','from_id','priority')"
                    ".by(label)"
                    ".by(outV().id())"
                    ".by(coalesce(values('priority'), constant(0)))",
                    {"vid": vid},
                ).all().result()
                for r in in_raw:
                    from_id = r.get("from_id", "")
                    label = r.get("label", "")
                    edge_key = f"{from_id}|{vid}|{label}"
                    if edge_key not in seen_edge_keys:
                        seen_edge_keys.add(edge_key)
                        edges.append({
                            "from_id": from_id,
                            "to_id": vid,
                            "label": label,
                            "priority": r.get("priority", 0) or None,
                        })
                    if from_id not in seen_nodes:
                        next_frontier.add(from_id)
            except Exception as e:
                logger.warning(f"traverse_neighborhood inE failed for {vid}: {e}")

        # Next hop starts from newly discovered nodes only
        frontier = next_frontier - set(seen_nodes.keys())
        if not frontier:
            break  # no new nodes to explore

    # Fetch details for frontier nodes discovered on the last hop
    # (we found their IDs via edges but haven't fetched their properties)
    for vid in frontier | (next_frontier if max_hops > 0 else set()):
        if vid not in seen_nodes:
            try:
                raw = client.submit("g.V(vid).valueMap(true)", {"vid": vid}).all().result()
                if raw:
                    v = raw[0]
                    seen_nodes[vid] = {
                        "id": vid,
                        "name": _first(v.get("name", [vid])),
                        "type": _first(v.get("type", [""])),
                        "description": _first(v.get("description", [""])),
                        "category": _first(v.get("category", [""])),
                        "aliases": _parse_json_list(v.get("aliases", ["[]"])),
                        "hop": max_hops,  # outermost hop
                    }
            except Exception:
                pass

    logger.info(f"traverse_neighborhood: {len(vertex_ids)} starting → {len(seen_nodes)} nodes, {len(edges)} edges")
    return seen_nodes, edges


def build_graph_context(nodes, edges, starting_ids):
    """Serialize traversal results as text for the agent prompt.

    Organizes the graph neighborhood into a readable format:
    1. Starting nodes with descriptions
    2. Direct relationships (what connects to what)
    3. Diagnostic chains (symptom→cause→fix) if present

    Works for ANY vertex type — the graph structure determines the format.
    """
    if not nodes:
        return ""

    lines = ["GRAPH CONTEXT (machine knowledge relevant to this question):"]

    # Starting nodes first — these are what the classifier identified as relevant
    for sid in starting_ids:
        node = nodes.get(sid)
        if not node:
            continue
        ntype = node.get("type", "")
        name = node.get("name", sid)
        desc = node.get("description", "")
        type_label = f"[{ntype}] " if ntype else ""
        lines.append(f"  {type_label}{name}" + (f" — {desc}" if desc else ""))

    # Build adjacency for readable relationship output
    # Group edges by type for organized presentation
    caused_by = []   # symptom → cause (diagnostic)
    fixed_by = []    # cause → fix
    involves = []    # cause → component
    structural = []  # contains, connects_to, drives

    for e in edges:
        label = e.get("label", "")
        from_node = nodes.get(e["from_id"], {})
        to_node = nodes.get(e["to_id"], {})
        from_name = from_node.get("name", e["from_id"])
        to_name = to_node.get("name", e["to_id"])

        if label == "caused_by":
            priority = e.get("priority")
            category = to_node.get("category", "")
            cat_text = f"[{category}] " if category else ""
            to_desc = to_node.get("description", "")
            caused_by.append((priority or 99, f"{cat_text}{to_desc or to_name}", e["to_id"]))
        elif label == "fixed_by":
            fix_desc = to_node.get("description", to_name)
            fixed_by.append((e["from_id"], fix_desc))
        elif label == "involves":
            involves.append((e["from_id"], to_name))
        else:
            verb = {"contains": "contains", "connects_to": "connects to", "drives": "drives"}.get(label, label)
            structural.append(f"{from_name} {verb} {to_name}")

    # Diagnostic chain: causes sorted by priority with fixes
    if caused_by:
        # Build fix lookup: cause_id → fix description
        fix_map = {cause_id: desc for cause_id, desc in fixed_by}
        comp_map = {cause_id: comp for cause_id, comp in involves}

        lines.append("")
        lines.append("DIAGNOSTIC CAUSES (in priority order):")
        caused_by.sort(key=lambda x: x[0])
        for i, (priority, desc, cause_id) in enumerate(caused_by, 1):
            comp = comp_map.get(cause_id, "")
            comp_text = f" (component: {comp})" if comp else ""
            fix = fix_map.get(cause_id, "")
            fix_text = f" — Fix: {fix}" if fix else ""
            lines.append(f"  {i}. {desc}{comp_text}{fix_text}")

    # Structural relationships
    if structural:
        lines.append("")
        lines.append("STRUCTURAL RELATIONSHIPS:")
        for rel in structural[:15]:  # cap to keep context reasonable
            lines.append(f"  - {rel}")

    lines.append("")
    lines.append("Use this graph context to guide your search. "
                  "Include information from this context even if search results don't mention it directly.")

    return "\n".join(lines)


MAX_VIZ_NEIGHBORS = 4  # max child nodes per starting node in the sidebar graph


def build_graph_viz(nodes, edges, starting_ids, max_viz_hops=1):
    """Serialize traversal results as vis.js nodes/edges for the sidebar.

    Filters to nodes within max_viz_hops AND caps children per starting
    node at MAX_VIZ_NEIGHBORS so the sidebar stays clean and focused.
    Agent context (build_graph_context) still uses the full traversal.
    """
    if not nodes or len(nodes) < 2:
        return None

    # Always include starting nodes (hop 0)
    viz_node_ids = set(sid for sid in starting_ids if sid in nodes)

    # Build edge lookup: which nodes connect directly to each starting node
    # Cap neighbors per starting node to keep the graph manageable
    neighbor_count = {sid: 0 for sid in starting_ids}
    for nid, node in nodes.items():
        if nid in viz_node_ids:
            continue  # already included as starting node
        if node.get("hop", 0) > max_viz_hops:
            continue  # beyond hop limit

        # Find which starting node this neighbor connects to
        parent_sid = None
        for e in edges:
            if e["to_id"] == nid and e["from_id"] in viz_node_ids:
                parent_sid = e["from_id"]
                break
            if e["from_id"] == nid and e["to_id"] in viz_node_ids:
                parent_sid = e["to_id"]
                break

        if parent_sid:
            if neighbor_count.get(parent_sid, 0) < MAX_VIZ_NEIGHBORS:
                viz_node_ids.add(nid)
                neighbor_count[parent_sid] = neighbor_count.get(parent_sid, 0) + 1
            # Skip if this starting node already has enough neighbors
        else:
            # Not directly connected to a starting node — include if within hop limit
            viz_node_ids.add(nid)

    # Build viz node list
    viz_nodes = []
    for nid in viz_node_ids:
        node = nodes[nid]
        viz_node = {
            "id": nid,
            "name": node.get("name", nid),
            "type": node.get("type", ""),
            "description": node.get("description", ""),
        }
        if node.get("category"):
            viz_node["category"] = node["category"]
        viz_nodes.append(viz_node)

    # Only include edges where both endpoints are in the filtered set
    viz_edges = [
        {
            "from_id": e["from_id"],
            "to_id": e["to_id"],
            "label": e["label"],
            "priority": e.get("priority"),
        }
        for e in edges
        if e["from_id"] in viz_node_ids and e["to_id"] in viz_node_ids
    ]

    # Log type breakdown for debugging — helps verify symptom/cause/fix types arrive in viz
    type_counts = {}
    for vn in viz_nodes:
        t = vn.get("type", "(none)")
        type_counts[t] = type_counts.get(t, 0) + 1
    logger.info(f"build_graph_viz: {len(nodes)} total → {len(viz_nodes)} viz nodes "
                f"(max {max_viz_hops} hops, {MAX_VIZ_NEIGHBORS} neighbors/start), "
                f"types: {type_counts}")

    return {
        "queried_ids": list(starting_ids),
        "nodes": viz_nodes,
        "edges": viz_edges,
    }


def query_all_vertices_for_classifier(client):
    """Return all classifiable vertices (symptoms, components, systems) for the LLM classifier.

    These are the valid starting points for graph traversal. Causes and fixes
    are intermediate nodes reached by traversal, not by classification.
    """
    results = []

    for vertex_type in ["symptom", "component", "system"]:
        try:
            raw = client.submit(
                "g.V().has('type', vtype).valueMap(true)", {"vtype": vertex_type}
            ).all().result()
            for v in raw:
                entry = {
                    "id": _first(v.get("id")),
                    "name": _first(v.get("name", [""])),
                    "type": vertex_type,
                    "description": _first(v.get("description", [""])),
                }
                if vertex_type == "symptom":
                    entry["aliases"] = _parse_json_list(v.get("aliases", ["[]"]))
                results.append(entry)
        except Exception as e:
            logger.warning(f"query_all_vertices_for_classifier failed for {vertex_type}: {e}")

    return results


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
