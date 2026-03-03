# Graph Analysis Tutorial — Cosmos DB Data Explorer

How to analyze the Davenport machine ontology and usage patterns using the Azure portal.

## Setup

1. Open [Azure Portal](https://portal.azure.com)
2. Navigate to: **Resource Group** `rg-gent-foundry-eus2` → **Cosmos DB** `cosmos-gent-gremlin`
3. Click **Data Explorer** in the left sidebar
4. Select database `davenport-graph` → graph `machine-ontology`
5. You'll see a query box at the top — paste Gremlin queries there and click **Execute**

Results render as an interactive graph. You can:
- **Drag nodes** to rearrange the layout
- **Click a node** to see its properties (name, type, hit_count, description)
- **Scroll** to zoom in/out
- **Switch to JSON view** (tab at top) to see raw data

---

## Key Queries

### 1. Most-asked-about nodes (what are machinists asking?)

```gremlin
g.V().has('hit_count', gt(0)).order().by('hit_count', desc).limit(15)
```

Shows the top 15 nodes by usage. High hit_count = frequently relevant to user questions.
Look at the `type` property — are these mostly symptoms? Causes? Components?

**Action:** If a node has high hits, make sure its connected causes/fixes are complete in the graph.

### 2. Unused symptoms (what's in the graph but never asked about?)

```gremlin
g.V().hasLabel('symptom').has('hit_count', 0)
```

Symptoms with zero hits. Either:
- Nobody has that problem (good)
- The classifier doesn't recognize how users describe it (needs aliases)

**Action:** Check if users ask about these symptoms using different words. Add `aliases` property if needed.

### 3. Visualize a specific symptom's neighborhood

```gremlin
g.V('part_short').bothE().bothV().path()
```

Shows the 1-hop neighborhood around "Part is short" — all connected causes, components, and fixes. This is what the app's Layer 2 traversal finds.

Replace `'part_short'` with any vertex ID. Common ones:
- `part_short` — Part is short
- `spindle_vibration` — Spindle vibration
- `rough_finish` — Rough surface finish

### 4. Full 2-hop traversal (matches what the app does)

```gremlin
g.V('part_short').repeat(both().simplePath()).times(2).path()
```

Shows the full 2-hop neighborhood — exactly what the sidebar graph displays per query.

**Action:** If important nodes are missing from the 2-hop traversal, you may need to add edges to connect them.

### 5. Most common root causes

```gremlin
g.V().hasLabel('cause').order().by('hit_count', desc).limit(10)
```

Top 10 causes by frequency. These are the problems machinists encounter most.

**Action:** Make sure these causes have complete `fixed_by` edges to fix vertices.

### 6. Orphan nodes (disconnected from the graph)

```gremlin
g.V().not(bothE()).valueMap('name', 'type')
```

Nodes with no edges — they'll never appear in a traversal. Either connect them or remove them.

### 7. Causes without fixes (incomplete troubleshooting paths)

```gremlin
g.V().hasLabel('cause').not(outE('fixed_by')).valueMap('name')
```

Cause vertices that don't have a `fixed_by` edge to any fix. Users will get "here's the problem" but no solution.

**Action:** Add fix vertices and `fixed_by` edges for each.

### 8. Graph overview — counts by type

```gremlin
g.V().groupCount().by(label)
```

Returns something like:
```json
{"symptom": 45, "cause": 120, "component": 85, "fix": 150, "system": 8}
```

Quick health check on graph completeness.

### 9. Relationship distribution

```gremlin
g.E().groupCount().by(label)
```

Shows how many edges of each type: `caused_by`, `fixed_by`, `involves`, `contains`, `connects_to`.

**Action:** If `fixed_by` is low relative to `caused_by`, the graph has diagnosis paths but not enough fix paths.

---

## When to Use What

| Question | Tool |
|----------|------|
| Which nodes are most/least used? | Cosmos DB (queries above) |
| Is the graph structurally complete? | Cosmos DB (orphans, missing fixes) |
| How is usage trending over time? | Power BI (`graph-nodes` table, group by date) |
| Which node types appear most per query? | Power BI (`graph-nodes` table, group by node_type) |
| What's the avg traversal size? | Power BI (`conversations` table, `graph_node_count` field) |

---

## Graph Maintenance Checklist

Run monthly or after adding new content to the knowledge base:

- [ ] Run query 6 (orphans) — connect or remove disconnected nodes
- [ ] Run query 7 (causes without fixes) — add missing fix paths
- [ ] Run query 2 (unused symptoms) — check if aliases are needed
- [ ] Run query 1 (top hits) — verify top nodes have complete neighborhoods
- [ ] Run query 8 (type counts) — check overall graph balance
