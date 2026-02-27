"""
build_graph.py — Extract machine ontology from video + MasterTask chunks,
populate Cosmos DB Gremlin graph.

Phase 1 of v3 Graph RAG.

Reads chunks from the unified Azure AI Search index, sends them to gpt-5-mini
for structured extraction, then inserts vertices and edges into the
davenport-graph / machine-ontology graph in Cosmos DB.

Re-runnable: drops all existing vertices before rebuilding.

Run: python build_graph.py
"""

import os, json, sys, logging, time
from collections import defaultdict
from urllib.parse import unquote, quote
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI
import urllib.request

import graph_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

# ── Config ────────────────────────────────────────────────────────────────────
SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "https://srch-j6lw7vswhnnhw.search.windows.net")
AOAI_ENDPOINT   = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://aoai-j6lw7vswhnnhw.openai.azure.com")
AOAI_KEY        = os.environ.get("AOAI_KEY", "")
MODEL           = os.environ.get("AGENT_MODEL", "gpt-5-mini")
UNIFIED_INDEX   = "davenport-kb-unified"
API_VERSION     = "2025-11-01-Preview"

# ── Auth ──────────────────────────────────────────────────────────────────────
credential = DefaultAzureCredential()

def search_headers():
    token = credential.get_token("https://search.azure.com/.default").token
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── Azure OpenAI client ──────────────────────────────────────────────────────
openai_client = AzureOpenAI(
    azure_endpoint=AOAI_ENDPOINT,
    api_key=AOAI_KEY,
    api_version="2025-04-01-preview",
)


# ── Search helpers ────────────────────────────────────────────────────────────
def query_chunks(filter_expr, select="chunk_id,snippet,blob_url,snippet_parent_id"):
    """Read all docs matching a filter from the unified index (paginated)."""
    all_docs = []
    skip = 0
    page_size = 1000

    while True:
        # URL-encode the filter expression (spaces, quotes, etc.)
        encoded_filter = quote(filter_expr, safe="")
        params = f"&$filter={encoded_filter}&$top={page_size}&$skip={skip}&$select={select}&$count=true"
        url = f"{SEARCH_ENDPOINT}/indexes/{UNIFIED_INDEX}/docs?api-version={API_VERSION}{params}"
        req = urllib.request.Request(url, headers=search_headers())
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        batch = data.get("value", [])
        all_docs.extend(batch)

        if skip == 0:
            logger.info(f"  Total matching: {data.get('@odata.count', '?')}")

        if len(batch) < page_size:
            break
        skip += page_size

    return all_docs


def group_by_source(docs):
    """Group chunks by their blob_url (source document)."""
    groups = defaultdict(list)
    for doc in docs:
        blob_url = doc.get("blob_url", "unknown")
        # Use the filename as the group key
        filename = unquote(blob_url.split("/")[-1]).rsplit(".", 1)[0]
        groups[filename].append(doc)
    return dict(groups)


# ── LLM extraction ───────────────────────────────────────────────────────────

# Prompt for extracting machine ontology from video training transcripts
VIDEO_EXTRACTION_PROMPT = """You are extracting a machine ontology from a Davenport Model B screw machine training video.

Analyze the transcript segments below and extract structured knowledge about:
1. SYSTEMS — major machine subsystems described (e.g., "Spindle System", "Cross Working Tools")
2. COMPONENTS — specific parts, tools, mechanisms mentioned (e.g., "collet", "brake", "cam roll")
3. RELATIONSHIPS — how components connect, drive, or contain each other
4. SYMPTOMS — any problems, defects, or failures described
5. CAUSES — what leads to those problems
6. FIXES — adjustments, replacements, or procedures described

Return ONLY valid JSON in this exact format:
{
  "systems": [
    {"id": "snake_case_id", "name": "Display Name", "description": "Brief description"}
  ],
  "components": [
    {"id": "snake_case_id", "name": "Display Name", "description": "Brief desc", "system_id": "parent_system_id", "synonyms": ["alt name 1"]}
  ],
  "relationships": [
    {"from_id": "component_a", "to_id": "component_b", "type": "connects_to|drives|contains", "description": "how they interact"}
  ],
  "symptoms": [
    {"id": "snake_case_id", "name": "Display Name", "description": "What it looks like", "aliases": ["shop floor term"]}
  ],
  "causes": [
    {"id": "snake_case_id", "description": "What goes wrong", "symptom_id": "linked_symptom", "component_id": "involved_component", "category": "Tooling|Machine|Feeds & Speeds|Work Holding|Stock/Material", "priority": 1}
  ],
  "fixes": [
    {"id": "snake_case_id", "description": "What to do", "cause_id": "linked_cause"}
  ]
}

Rules:
- Use snake_case for all IDs (e.g., "spindle_system", "collet", "part_short")
- Keep IDs consistent — if collet is mentioned in multiple places, always use "collet"
- Priority 1 = most likely/first thing to check, higher numbers = less likely
- Only extract what's explicitly stated — don't invent relationships
- If no symptoms/causes/fixes are described, return empty arrays for those
"""

# Prompt for extracting from MasterTask troubleshooting flowcharts
MASTERTASK_EXTRACTION_PROMPT = """You are extracting a troubleshooting diagnostic tree from a Davenport Model B screw machine troubleshooting flowchart.

The text below describes a flowchart with a symptom at the top and a series of yes/no diagnostic checks leading to fixes.

Extract the structured diagnostic tree:

Return ONLY valid JSON in this exact format:
{
  "symptoms": [
    {"id": "snake_case_id", "name": "Display Name", "description": "What the operator sees", "aliases": ["shop floor term"]}
  ],
  "causes": [
    {"id": "snake_case_id", "description": "What goes wrong (the yes/no check)", "symptom_id": "linked_symptom", "component_id": "involved_component", "category": "Tooling|Machine|Feeds & Speeds|Work Holding|Stock/Material", "priority": 1}
  ],
  "fixes": [
    {"id": "snake_case_id", "description": "What to do (the corrective action)", "cause_id": "linked_cause"}
  ],
  "components": [
    {"id": "snake_case_id", "name": "Display Name", "description": "Brief desc", "system_id": "", "synonyms": []}
  ]
}

Rules:
- Priority follows the flowchart order: first check = priority 1, second = 2, etc.
- The symptom is the title of the flowchart (the problem being diagnosed)
- Each yes/no check is a "cause" — the thing that could be wrong
- The corrective action for each check is the "fix"
- Extract any components mentioned (drill, collet, cam, etc.)
- Use snake_case IDs consistently
- Category tags: Tooling (tools/drills/holders), Machine (mechanical parts), Feeds & Speeds (rates/gears), Work Holding (collets/chucks/fingers), Stock/Material (bar stock)
"""


def extract_with_llm(chunks, prompt, source_name):
    """Send chunk text to gpt-5-mini for structured extraction."""
    # Build the content from chunks — just the snippet text, no [source: ...] prefix
    texts = []
    for chunk in chunks:
        snippet = chunk.get("snippet", "")
        # Strip the [source: URL] prefix
        if snippet.startswith("[source:"):
            snippet = snippet.split("\n", 1)[-1] if "\n" in snippet else snippet
        texts.append(snippet)

    combined = "\n\n---\n\n".join(texts)

    # Truncate if too long (gpt-5-mini has ~128k context, but we want fast responses)
    max_chars = 80000
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n\n[TRUNCATED]"

    logger.info(f"  Sending {len(texts)} chunks ({len(combined)} chars) for: {source_name}")

    try:
        response = openai_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Source: {source_name}\n\n{combined}"},
            ],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        logger.error(f"  LLM extraction failed for {source_name}: {e}")
        return {}


# ── Graph population ──────────────────────────────────────────────────────────

def populate_graph(client, extractions, chunk_ids_by_source):
    """
    Insert all extracted vertices and edges into Cosmos DB.
    Deduplicates by vertex ID — if the same component appears in multiple sources,
    we keep the first occurrence (later phases can merge).
    """
    seen_vertices = set()
    edge_count = 0
    vertex_count = 0

    for source_name, data in extractions.items():
        chunk_ids = chunk_ids_by_source.get(source_name, [])
        logger.info(f"Populating from: {source_name}")

        # -- Systems --
        for system in data.get("systems", []):
            sid = system["id"]
            if sid not in seen_vertices:
                graph_client.add_vertex(client, "system", sid, {
                    "name": system.get("name", sid),
                    "description": system.get("description", ""),
                    "source": "video_transcript",
                    "verified": False,
                    "chunk_ids": json.dumps(chunk_ids[:5]),  # link back to source chunks
                })
                seen_vertices.add(sid)
                vertex_count += 1

        # -- Components --
        for comp in data.get("components", []):
            cid = comp["id"]
            if cid not in seen_vertices:
                graph_client.add_vertex(client, "component", cid, {
                    "name": comp.get("name", cid),
                    "description": comp.get("description", ""),
                    "synonyms": json.dumps(comp.get("synonyms", [])),
                    "category": comp.get("category", ""),
                    "source": "video_transcript",
                    "verified": False,
                    "chunk_ids": json.dumps(chunk_ids[:5]),
                })
                seen_vertices.add(cid)
                vertex_count += 1

            # Edge: system --contains--> component
            system_id = comp.get("system_id", "")
            if system_id and system_id in seen_vertices:
                try:
                    graph_client.add_edge(client, "contains", system_id, cid)
                    edge_count += 1
                except Exception as e:
                    logger.warning(f"  Edge failed: {system_id} --contains--> {cid}: {e}")

        # -- Relationships (drives, connects_to) --
        for rel in data.get("relationships", []):
            from_id = rel.get("from_id", "")
            to_id = rel.get("to_id", "")
            rel_type = rel.get("type", "connects_to")
            if from_id in seen_vertices and to_id in seen_vertices:
                try:
                    graph_client.add_edge(client, rel_type, from_id, to_id, {
                        "description": rel.get("description", ""),
                    })
                    edge_count += 1
                except Exception as e:
                    logger.warning(f"  Edge failed: {from_id} --{rel_type}--> {to_id}: {e}")

        # -- Symptoms --
        for symptom in data.get("symptoms", []):
            sid = symptom["id"]
            if sid not in seen_vertices:
                graph_client.add_vertex(client, "symptom", sid, {
                    "name": symptom.get("name", sid),
                    "description": symptom.get("description", ""),
                    "aliases": json.dumps(symptom.get("aliases", [])),
                    "source": source_name,
                    "verified": False,
                    "chunk_ids": json.dumps(chunk_ids[:5]),
                })
                seen_vertices.add(sid)
                vertex_count += 1

        # -- Causes --
        for cause in data.get("causes", []):
            cid = cause["id"]
            if cid not in seen_vertices:
                graph_client.add_vertex(client, "cause", cid, {
                    "description": cause.get("description", ""),
                    "category": cause.get("category", ""),
                    "source": source_name,
                    "verified": False,
                    "chunk_ids": json.dumps(chunk_ids[:5]),
                })
                seen_vertices.add(cid)
                vertex_count += 1

            # Edge: symptom --caused_by--> cause (with priority)
            symptom_id = cause.get("symptom_id", "")
            if symptom_id and symptom_id in seen_vertices:
                try:
                    graph_client.add_edge(client, "caused_by", symptom_id, cid, {
                        "priority": cause.get("priority", 99),
                    })
                    edge_count += 1
                except Exception as e:
                    logger.warning(f"  Edge failed: {symptom_id} --caused_by--> {cid}: {e}")

            # Edge: cause --involves--> component
            comp_id = cause.get("component_id", "")
            if comp_id and comp_id in seen_vertices:
                try:
                    graph_client.add_edge(client, "involves", cid, comp_id, {
                        "category": cause.get("category", ""),
                    })
                    edge_count += 1
                except Exception as e:
                    logger.warning(f"  Edge failed: {cid} --involves--> {comp_id}: {e}")

        # -- Fixes --
        for fix in data.get("fixes", []):
            fid = fix["id"]
            if fid not in seen_vertices:
                graph_client.add_vertex(client, "fix", fid, {
                    "description": fix.get("description", ""),
                    "source": source_name,
                    "verified": False,
                    "chunk_ids": json.dumps(chunk_ids[:5]),
                })
                seen_vertices.add(fid)
                vertex_count += 1

            # Edge: cause --fixed_by--> fix
            cause_id = fix.get("cause_id", "")
            if cause_id and cause_id in seen_vertices:
                try:
                    graph_client.add_edge(client, "fixed_by", cause_id, fid)
                    edge_count += 1
                except Exception as e:
                    logger.warning(f"  Edge failed: {cause_id} --fixed_by--> {fid}: {e}")

    return vertex_count, edge_count


# ── Dave's expert knowledge (manual entries for known gaps) ────────────────────

def add_expert_knowledge(client):
    """
    Add Dave's expert knowledge that isn't in any document.
    These are the "10th answer" entries — things only an experienced
    machinist would know.
    """
    logger.info("Adding Dave's expert knowledge...")

    expert_entries = [
        # Symptom: part is short — the #1 question
        {
            "symptom": {"id": "part_short", "name": "Part is short", "description": "Finished part is shorter than specified dimension", "aliases": ["bar feeding short", "short parts", "part not to length"]},
            "causes": [
                {"id": "cutoff_ring_on_bar", "description": "Cutoff tool leaves a ring/step on the bar end that prevents the next part from seating fully in the collet", "component_id": "cutoff_tool", "category": "Tooling", "priority": 1},
                {"id": "feed_finger_tension_low", "description": "Feed finger spring tension too low — bar not pushed firmly against positive stop", "component_id": "feed_fingers", "category": "Work Holding", "priority": 2},
                {"id": "collet_wear", "description": "Collet bore scored or worn — bar slipping during machining", "component_id": "collet", "category": "Work Holding", "priority": 3},
                {"id": "positive_stop_worn", "description": "Positive stop face worn or out of adjustment", "component_id": "positive_stop", "category": "Machine", "priority": 4},
                {"id": "bar_stock_bent", "description": "Bar stock not straight — feeds inconsistently", "component_id": "bar_stock", "category": "Stock/Material", "priority": 5},
            ],
            "fixes": [
                {"id": "fix_cutoff_ring", "description": "Adjust cutoff depth so tool clears center, or resharpen cutoff tool", "cause_id": "cutoff_ring_on_bar"},
                {"id": "fix_feed_tension", "description": "Adjust feed finger spring pressure — should push bar firmly but not score it", "cause_id": "feed_finger_tension_low"},
                {"id": "fix_collet_wear", "description": "Check collet bore for scoring, replace if worn beyond tolerance", "cause_id": "collet_wear"},
                {"id": "fix_positive_stop", "description": "Inspect positive stop face, readjust or replace", "cause_id": "positive_stop_worn"},
                {"id": "fix_bent_bar", "description": "Check bar straightness, reject bars that are bent or bowed", "cause_id": "bar_stock_bent"},
            ],
            "components": [
                {"id": "cutoff_tool", "name": "Cutoff Tool", "description": "Circular blade (T blade) that parts the finished piece from bar stock"},
                {"id": "feed_fingers", "name": "Feed Fingers", "description": "Spring-loaded fingers that push bar stock forward to the positive stop"},
                {"id": "collet", "name": "Collet", "description": "Split sleeve that grips bar stock in the work spindle"},
                {"id": "positive_stop", "name": "Positive Stop", "description": "Fixed stop that determines part length — bar is pushed against it by feed mechanism"},
                {"id": "bar_stock", "name": "Bar Stock", "description": "Raw material rod fed through the spindle"},
            ],
        },
        # Symptom: burr on cutoff
        {
            "symptom": {"id": "burr_on_cutoff", "name": "Burr on cutoff", "description": "Burr or rough finish where the cutoff tool separated the part", "aliases": ["dirty cutoff", "tit on cutoff", "nib on part"]},
            "causes": [
                {"id": "cutoff_tool_dull", "description": "Cutoff tool is dull or chipped", "component_id": "cutoff_tool", "category": "Tooling", "priority": 1},
                {"id": "cutoff_grind_wrong", "description": "Cutoff tool ground at wrong angle — needs proper rake and clearance", "component_id": "cutoff_tool", "category": "Tooling", "priority": 2},
                {"id": "cutoff_speed_wrong", "description": "Spindle RPM too fast or too slow for the material and cutoff width", "component_id": "spindle", "category": "Feeds & Speeds", "priority": 3},
                {"id": "coolant_insufficient", "description": "Not enough coolant at the cutoff point", "component_id": "coolant_system", "category": "Machine", "priority": 4},
            ],
            "fixes": [
                {"id": "fix_sharpen_cutoff", "description": "Resharpen cutoff tool with correct rake angle", "cause_id": "cutoff_tool_dull"},
                {"id": "fix_regrind_angle", "description": "Regrind cutoff tool to proper angle per material spec", "cause_id": "cutoff_grind_wrong"},
                {"id": "fix_cutoff_speed", "description": "Adjust spindle speed — check gear selection for material", "cause_id": "cutoff_speed_wrong"},
                {"id": "fix_coolant_cutoff", "description": "Redirect coolant nozzle to cutoff point, check flow rate", "cause_id": "coolant_insufficient"},
            ],
            "components": [
                {"id": "spindle", "name": "Work Spindle", "description": "Rotating spindle that holds the bar stock via collet"},
                {"id": "coolant_system", "name": "Coolant System", "description": "Pump and nozzles delivering cutting fluid to tools"},
            ],
        },
        # Symptom: machine jumping / index skipping
        {
            "symptom": {"id": "machine_jumping", "name": "Machine jumping", "description": "Machine skips or jolts during index — spindle carrier doesn't seat properly", "aliases": ["index skipping", "machine is jumping", "rough index"]},
            "causes": [
                {"id": "brake_loose", "description": "Brake band loose — spindle carrier overshoots during index", "component_id": "brake", "category": "Machine", "priority": 1},
                {"id": "brake_worn", "description": "Brake lining worn — not enough stopping force", "component_id": "brake", "category": "Machine", "priority": 2},
                {"id": "index_pin_worn", "description": "Index lock pin or bushing worn — carrier not locking in position", "component_id": "index_pin", "category": "Machine", "priority": 3},
            ],
            "fixes": [
                {"id": "fix_tighten_brake", "description": "Adjust brake band tension — should stop carrier smoothly without bouncing", "cause_id": "brake_loose"},
                {"id": "fix_replace_brake", "description": "Replace brake lining when worn beyond adjustment range", "cause_id": "brake_worn"},
                {"id": "fix_index_pin", "description": "Inspect index pin and bushing, replace if worn", "cause_id": "index_pin_worn"},
            ],
            "components": [
                {"id": "brake", "name": "Brake", "description": "Band brake that stops spindle carrier rotation at each index position"},
                {"id": "index_pin", "name": "Index Lock Pin", "description": "Pin that locks the spindle carrier in position after indexing"},
            ],
        },
    ]

    vertex_count = 0
    edge_count = 0

    for entry in expert_entries:
        # Add symptom
        s = entry["symptom"]
        graph_client.add_vertex(client, "symptom", s["id"], {
            "name": s["name"],
            "description": s["description"],
            "aliases": json.dumps(s.get("aliases", [])),
            "source": "dave_expert",
            "verified": True,  # Dave's knowledge is pre-verified
        })
        vertex_count += 1

        # Add components
        for comp in entry.get("components", []):
            try:
                graph_client.add_vertex(client, "component", comp["id"], {
                    "name": comp["name"],
                    "description": comp["description"],
                    "source": "dave_expert",
                    "verified": True,
                })
                vertex_count += 1
            except Exception:
                pass  # May already exist from LLM extraction — that's fine

        # Add causes with edges
        for cause in entry["causes"]:
            graph_client.add_vertex(client, "cause", cause["id"], {
                "description": cause["description"],
                "category": cause["category"],
                "source": "dave_expert",
                "verified": True,
            })
            vertex_count += 1

            # symptom --caused_by--> cause
            try:
                graph_client.add_edge(client, "caused_by", s["id"], cause["id"], {
                    "priority": cause["priority"],
                })
                edge_count += 1
            except Exception as e:
                logger.warning(f"  Expert edge failed: {s['id']} --caused_by--> {cause['id']}: {e}")

            # cause --involves--> component
            if cause.get("component_id"):
                try:
                    graph_client.add_edge(client, "involves", cause["id"], cause["component_id"], {
                        "category": cause["category"],
                    })
                    edge_count += 1
                except Exception as e:
                    logger.warning(f"  Expert edge failed: {cause['id']} --involves--> {cause['component_id']}: {e}")

        # Add fixes with edges
        for fix in entry["fixes"]:
            graph_client.add_vertex(client, "fix", fix["id"], {
                "description": fix["description"],
                "source": "dave_expert",
                "verified": True,
            })
            vertex_count += 1

            # cause --fixed_by--> fix
            try:
                graph_client.add_edge(client, "fixed_by", fix["cause_id"], fix["id"])
                edge_count += 1
            except Exception as e:
                logger.warning(f"  Expert edge failed: {fix['cause_id']} --fixed_by--> {fix['id']}: {e}")

    logger.info(f"  Expert knowledge: {vertex_count} vertices, {edge_count} edges")
    return vertex_count, edge_count


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Building Davenport machine ontology graph")
    print("=" * 60)

    # Connect to Cosmos DB
    print("\nConnecting to Cosmos DB Gremlin...")
    client = graph_client.get_client()

    # Clear existing graph (re-runnable)
    print("Clearing existing graph...")
    graph_client.drop_all(client)
    time.sleep(2)  # Let Cosmos DB settle after drop

    # ── Step 1: Read chunks from unified index ────────────────────────────────
    print("\n--- Step 1: Reading chunks from unified index ---")

    print("\nReading video training chunks...")
    video_chunks = query_chunks("source_type eq 'video'")
    print(f"  Got {len(video_chunks)} video chunks")

    print("\nReading troubleshooting (MasterTask) chunks...")
    troubleshoot_chunks = query_chunks("category eq 'troubleshooting'")
    print(f"  Got {len(troubleshoot_chunks)} troubleshooting chunks")

    # ── Step 2: Group chunks by source document ───────────────────────────────
    print("\n--- Step 2: Grouping chunks by source ---")

    video_groups = group_by_source(video_chunks)
    troubleshoot_groups = group_by_source(troubleshoot_chunks)

    print(f"  Video sources: {len(video_groups)}")
    for name, chunks in video_groups.items():
        print(f"    {name}: {len(chunks)} chunks")

    print(f"  Troubleshooting sources: {len(troubleshoot_groups)}")
    for name, chunks in troubleshoot_groups.items():
        print(f"    {name}: {len(chunks)} chunks")

    # Build chunk_id lookup by source name (for linking graph nodes back to chunks)
    chunk_ids_by_source = {}
    for name, chunks in {**video_groups, **troubleshoot_groups}.items():
        chunk_ids_by_source[name] = [c.get("chunk_id", "") for c in chunks]

    # ── Step 3: LLM extraction ────────────────────────────────────────────────
    print("\n--- Step 3: Extracting ontology with LLM ---")
    extractions = {}

    # Process video sources
    for name, chunks in video_groups.items():
        print(f"\nProcessing video: {name}")
        result = extract_with_llm(chunks, VIDEO_EXTRACTION_PROMPT, name)
        if result:
            extractions[name] = result
            # Print summary
            for key in ["systems", "components", "relationships", "symptoms", "causes", "fixes"]:
                count = len(result.get(key, []))
                if count > 0:
                    print(f"    {key}: {count}")
        time.sleep(1)  # Rate limiting

    # Process troubleshooting sources
    for name, chunks in troubleshoot_groups.items():
        print(f"\nProcessing MasterTask: {name}")
        result = extract_with_llm(chunks, MASTERTASK_EXTRACTION_PROMPT, name)
        if result:
            extractions[name] = result
            for key in ["symptoms", "causes", "fixes", "components"]:
                count = len(result.get(key, []))
                if count > 0:
                    print(f"    {key}: {count}")
        time.sleep(1)

    # Save raw extractions to JSON for debugging/review
    with open("graph_extractions.json", "w", encoding="utf-8") as f:
        json.dump(extractions, f, indent=2, ensure_ascii=False)
    print(f"\nSaved raw extractions to graph_extractions.json")

    # ── Step 4: Populate graph ────────────────────────────────────────────────
    print("\n--- Step 4: Populating Cosmos DB graph ---")

    v_count, e_count = populate_graph(client, extractions, chunk_ids_by_source)
    print(f"\nLLM extraction: {v_count} vertices, {e_count} edges")

    # ── Step 5: Add Dave's expert knowledge ───────────────────────────────────
    print("\n--- Step 5: Adding expert knowledge ---")
    ev_count, ee_count = add_expert_knowledge(client)

    # ── Step 6: Verify ────────────────────────────────────────────────────────
    print("\n--- Step 6: Verification ---")
    time.sleep(2)  # Let Cosmos DB catch up

    stats = graph_client.get_stats(client)
    print(f"\nGraph statistics:")
    print(f"  Total vertices: {stats.get('total_vertices', '?')}")
    print(f"  Total edges:    {stats.get('total_edges', '?')}")
    print(f"  Vertices by type: {json.dumps(stats.get('vertices', {}), indent=4)}")
    print(f"  Edges by label:   {json.dumps(stats.get('edges', {}), indent=4)}")

    # Test a sample traversal
    print("\n--- Sample traversal: causes for 'part_short' ---")
    context = graph_client.get_graph_context(client, "part_short")
    if context:
        print(context)
    else:
        print("  (No results — symptom 'part_short' may not exist yet)")

    client.close()

    print("\n" + "=" * 60)
    total_v = v_count + ev_count
    total_e = e_count + ee_count
    print(f"DONE — {total_v} vertices, {total_e} edges inserted")
    print(f"Graph ready for query-time integration (Phase 2)")
    print("=" * 60)


if __name__ == "__main__":
    main()
