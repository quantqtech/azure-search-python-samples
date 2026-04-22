"""
Azure Function: Chat API endpoint for Davenport Assistant.
Connects to the agentic retrieval agent via Azure AI Projects SDK.
Includes streaming, feedback, and voice memo endpoints for production use.

All functions use the FastAPI extension types (Request/JSONResponse/StreamingResponse)
because Azure Functions requires all HTTP functions to use the same type system when
streaming is enabled (PYTHON_ENABLE_INIT_INDEXING=1 app setting required).
"""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azurefunctions.extensions.http.fastapi import Request, StreamingResponse, JSONResponse
import auth_helper

# Pipeline version — increment on each deploy to verify code is live
PIPELINE_VERSION = "2026-03-01-v11-context-logging"

# Storage config — env var with fallback to current deployment value
STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT", "stj6lw7vswhnnhw")
TRANSCRIPT_CONTAINER = "video-training"

# YouTube video mapping: transcript filename (without .md) -> YouTube video ID
YOUTUBE_VIDEO_MAP = {
    "Davenport Machine Model B - Basic Identification (part 1)": "Bgqf1gt0y10",
    "Davenport Machine Model B - Basic Identification (part 2)": "7NYKOGs6CDs",
    "Davenport Machine Model B - Cross Working Tools (part 1)": "rINsPjoNOlA",
    "Davenport Machine Model B - Cross Working Tools (part 2)": "fb0zCgmn55s",
    "Davenport Machine Model B - The Work Spindles": "lwnB7ysRsGs",
    "Davenport Machine Model B - Stocking": "22tb3sbqquM",
    "Davenport Machine Model B - End Working Tools": "NMeeZX7ie44",
    "Davenport Machine Model B - E2726 Size Toll Holder": "diMpiXFFPVo",
    "Davenport Machine Model B - Chuck and Feed Mechanism": "C8NLYDmM9jk",
    "Davenport Machine Model B - Preventive Maintenance": "RIxzlj3ANTY",
}

# Foundry project endpoint — env var with fallback to current deployment value
PROJECT_ENDPOINT = os.environ.get("PROJECT_ENDPOINT", "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw")

# Agent routing by reasoning level
AGENTS = {
    "fast": "davenport-fast",           # Minimal reasoning ~40s (MCP)
    "balanced": "davenport-balanced",   # Low reasoning ~55s (MCP)
    "thorough": "davenport-assistant",  # Medium reasoning ~2 min (MCP)
    "direct": "davenport-direct-v1",    # Unified index, direct search ~30s — no mode selector in new SWA
}
DEFAULT_AGENT = "davenport-direct-v1"

# Conversation history management — reset after N turns to keep token count bounded.
# At ~8k tokens/turn, 5 turns = ~40k input tokens. Reset creates a new Foundry
# conversation with a summary of what was discussed, keeping context but dropping verbatim history.
MAX_TURNS_BEFORE_RESET = 5

# Create function app
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Azure Table Storage config (feedback data)
TABLE_STORAGE_ENDPOINT = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"
BLOB_STORAGE_ENDPOINT = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"

# Cache clients for reuse across invocations
_project_client = None
_openai_client = None
_table_client = None
_blob_service_client = None
_gremlin_client = None     # V3 Graph RAG — Cosmos DB Gremlin
_vertex_cache = None       # V3 Graph RAG — cached vertex list for classification (all types)
_direct_openai_client = None  # Direct AOAI client for classification (bypasses Foundry project routing)
_world_model_cache = None     # V3 Layer 1 — cached machine structural summary


def get_clients():
    """Get or create Azure clients (cached for performance)."""
    global _project_client, _openai_client

    if _project_client is None:
        credential = DefaultAzureCredential()
        _project_client = AIProjectClient(
            endpoint=PROJECT_ENDPOINT,
            credential=credential
        )
        _openai_client = _project_client.get_openai_client()

    return _project_client, _openai_client


def get_table_client(table_name="feedback"):
    """Get or create Azure Table Storage client (cached per table name)."""
    global _table_client
    if _table_client is None:
        _table_client = {}
    if table_name not in _table_client:
        from azure.data.tables import TableServiceClient
        credential = DefaultAzureCredential()
        service = TableServiceClient(
            endpoint=TABLE_STORAGE_ENDPOINT,
            credential=credential
        )
        # Create table if it doesn't exist (idempotent)
        service.create_table_if_not_exists(table_name)
        _table_client[table_name] = service.get_table_client(table_name)
    return _table_client[table_name]


def get_blob_service_client():
    """Get or create Azure Blob Storage client (cached)."""
    global _blob_service_client
    if _blob_service_client is None:
        from azure.storage.blob import BlobServiceClient
        credential = DefaultAzureCredential()
        _blob_service_client = BlobServiceClient(
            account_url=BLOB_STORAGE_ENDPOINT,
            credential=credential
        )
    return _blob_service_client


def get_gremlin_client():
    """Lazy-init Gremlin client for V3 Graph RAG. Returns None if Cosmos DB config is missing."""
    global _gremlin_client
    if _gremlin_client is None:
        try:
            import graph_helper
            _gremlin_client = graph_helper.get_client()
            logging.info("Gremlin client connected to Cosmos DB")
        except Exception as e:
            logging.warning(f"Gremlin client unavailable (V3 graph disabled): {e}")
            _gremlin_client = "unavailable"  # sentinel — don't retry every request
    return None if _gremlin_client == "unavailable" else _gremlin_client


def get_direct_openai_client():
    """Direct AOAI client for classification calls.

    The Foundry project client routes through a project-scoped API that
    only supports agent operations (responses.create). Classification
    needs standard chat.completions, so we talk directly to the AOAI resource.
    """
    global _direct_openai_client
    if _direct_openai_client is None:
        from openai import AzureOpenAI
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        _direct_openai_client = AzureOpenAI(
            azure_endpoint=os.environ.get("AOAI_ENDPOINT", "https://aoai-j6lw7vswhnnhw.openai.azure.com"),
            api_version="2024-10-21",
            azure_ad_token=token.token,
        )
    return _direct_openai_client


def get_world_model():
    """Build and cache machine world model from graph (Layer 1).

    Returns a compact structural summary of the Davenport machine —
    systems, components, key relationships. Prepended to every query
    so the LLM has baseline machine knowledge. Empty string if unavailable.
    """
    global _world_model_cache
    if _world_model_cache is not None:
        return _world_model_cache
    try:
        import graph_helper
        gremlin = get_gremlin_client()
        if not gremlin:
            _world_model_cache = ""
            return ""
        _world_model_cache = graph_helper.build_world_model(gremlin)
        logging.info(f"World model cached: {len(_world_model_cache)} chars")
    except Exception as e:
        logging.warning(f"World model build failed (proceeding without): {e}")
        _world_model_cache = ""
    return _world_model_cache


def summarize_conversation(message_history):
    """Summarize conversation history into a compact context block.

    Called when turn count exceeds MAX_TURNS_BEFORE_RESET. Uses a fast LLM call
    to distill the conversation into ~150 tokens so the new Foundry conversation
    starts with context but without the full verbatim history.

    message_history: list of {message, response_summary} dicts from the frontend.
    Returns a string like "CONVERSATION SUMMARY:\n..."
    """
    if not message_history:
        return ""

    try:
        client = get_direct_openai_client()
        # Build a compact transcript for the summarizer
        transcript = "\n".join(
            f"Q: {m['message']}\nA: {m.get('response_summary', '(no summary)')}"
            for m in message_history
        )

        result = client.chat.completions.create(
            model="gpt-5-mini",  # needs intelligence to distill conversation context well
            messages=[
                {"role": "system", "content": (
                    "Summarize this Davenport screw machine support conversation in 2-3 sentences. "
                    "Focus on: what problem the user has, what was diagnosed, what fixes were discussed. "
                    "Be specific about machine components mentioned. Keep it under 100 words."
                )},
                {"role": "user", "content": transcript},
            ],
            max_tokens=200,
        )
        summary = result.choices[0].message.content.strip()
        logging.info(f"Conversation summary: {len(summary)} chars")
        return f"CONVERSATION SUMMARY (prior discussion):\n{summary}"
    except Exception as e:
        logging.warning(f"Summary generation failed: {e}")
        # Fallback: just list the user's questions
        questions = [m["message"] for m in message_history]
        return f"CONVERSATION SUMMARY (prior questions): {'; '.join(questions)}"


def classify_graph_nodes(message, recent_messages=None):
    """Find the 1-3 graph vertices most relevant to the user's question.

    recent_messages: list of prior user messages (last 2-3) for follow-up context.
    Helps the classifier connect "what about the collet?" to "part is short".

    Returns a list of vertex IDs (any type: symptom, component, system).
    The graph traversal walks outward from these starting points — the graph
    structure determines what context gets built, not routing categories.
    """
    global _vertex_cache

    gremlin = get_gremlin_client()
    if not gremlin:
        return []

    import graph_helper

    # Load all classifiable vertices once (refreshed on function app restart)
    if _vertex_cache is None:
        _vertex_cache = graph_helper.query_all_vertices_for_classifier(gremlin)
        logging.info(f"Loaded {len(_vertex_cache)} vertices for classification "
                     f"({sum(1 for v in _vertex_cache if v['type'] == 'symptom')} symptoms, "
                     f"{sum(1 for v in _vertex_cache if v['type'] == 'component')} components, "
                     f"{sum(1 for v in _vertex_cache if v['type'] == 'system')} systems)")

    if not _vertex_cache:
        return []

    # Build vertex list for the LLM — grouped by type for clarity
    vertex_lines = []
    for vtype in ["symptom", "component", "system"]:
        typed = [v for v in _vertex_cache if v["type"] == vtype]
        if typed:
            vertex_lines.append(f"\n{vtype.upper()}S:")
            for v in typed:
                line = f"- {v['id']}: {v['name']}"
                if v.get("description"):
                    line += f" — {v['description']}"
                if v.get("aliases"):
                    line += f" (aliases: {', '.join(v['aliases'])})"
                vertex_lines.append(line)

    vertex_text = "\n".join(vertex_lines)

    # Build conversation context for follow-up questions
    conversation_block = ""
    if recent_messages:
        prior = "\n".join(f"- {msg}" for msg in recent_messages[-3:])
        conversation_block = (
            f"\n\nCONVERSATION CONTEXT (recent user messages, oldest first):\n{prior}\n"
            f"Use this to resolve follow-up references like 'that', 'it', 'what about...'.\n"
        )

    try:
        resp = get_direct_openai_client().chat.completions.create(
            model="gpt-5-mini",  # 570-vertex prompt too heavy for nano — mini is faster here
            messages=[
                {"role": "system", "content": (
                    "You identify which graph vertices are most relevant to a Davenport Model B "
                    "screw machine question. The graph contains symptoms (problems), components "
                    "(machine parts), and systems (groups of components).\n\n"
                    f"Available vertices:{vertex_text}\n\n"
                    "Common aliases: 'stock reel'/'reel tension' → bar_stock, "
                    "'cam rolls' → tooling, 'T blade' → cutoff_tool, "
                    "'part is short'/'short part' → part_short, "
                    "'setup'/'changeover' → relates to multiple systems.\n\n"
                    f"{conversation_block}"
                    "Rules:\n"
                    "- Return 1-3 vertex IDs that best match the question\n"
                    "- Prefer symptoms when the user describes something WRONG\n"
                    "- Prefer components when the user asks about a specific part\n"
                    "- Prefer systems for broad/general questions\n"
                    "- Multiple IDs are fine (e.g., 'part short when cutting' → [\"part_short\", \"cutoff_tool\"])\n"
                    "- Return [] only if the question is completely unrelated to the machine\n\n"
                    'Return JSON: {"vertex_ids": ["id1", "id2"]}'
                )},
                {"role": "user", "content": f"CURRENT QUESTION: {message}"},
            ],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        vertex_ids = result.get("vertex_ids", [])

        # Validate — only return IDs that actually exist in the graph
        valid_ids = {v["id"] for v in _vertex_cache}
        vertex_ids = [vid for vid in vertex_ids if vid in valid_ids]

        if vertex_ids:
            names = [next((v["name"] for v in _vertex_cache if v["id"] == vid), vid) for vid in vertex_ids]
            logging.info(f"Graph nodes classified: {vertex_ids} ({names})")

        return vertex_ids

    except Exception as e:
        logging.warning(f"classify_graph_nodes failed: {e}")

    return []


def build_graph_log_summary(nodes, edges, starting_ids):
    """Build a compact traversal summary for analytics logging (Level 2 only).

    Captures enough detail to analyze classification quality, hop depth,
    and type distribution without storing full descriptions (~2-4 KB).
    """
    try:
        # Type breakdown
        type_counts = {}
        for n in nodes.values():
            t = n.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        # Starting node names for readability
        starting_names = [
            nodes[sid].get("name", sid) for sid in starting_ids if sid in nodes
        ]

        # Compact node list — id, name, type, hop (no descriptions)
        nodes_summary = [
            {"id": n["id"], "name": n.get("name", ""), "type": n.get("type", ""), "hop": n.get("hop", -1)}
            for n in sorted(nodes.values(), key=lambda x: (x.get("hop", 99), x.get("type", "")))
        ]

        # Compact edge list — from, to, label
        edges_summary = [
            {"from": e.get("from_id", ""), "to": e.get("to_id", ""), "label": e.get("label", "")}
            for e in edges
        ]

        return {
            "starting_ids": starting_ids,
            "starting_names": starting_names,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": type_counts,
            "nodes_summary": nodes_summary,
            "edges_summary": edges_summary,
        }
    except Exception as e:
        logging.warning(f"build_graph_log_summary failed: {e}")
        return None


def get_graph_context_for_message(message, recent_messages=None):
    """Graph RAG Layer 2: one traversal → agent context + sidebar viz.

    1. Classifier picks 1-3 starting vertices (any type)
    2. Generic traversal walks 1-2 hops outward
    3. Same data feeds BOTH agent context text AND sidebar visualization

    Returns (context_string, graph_viz_dict, starting_ids, traversal_log).
    """
    try:
        import graph_helper
        gremlin = get_gremlin_client()
        if not gremlin:
            return "", None, [], None

        # Step 1: find starting nodes
        vertex_ids = classify_graph_nodes(message, recent_messages=recent_messages)
        if not vertex_ids:
            return "", None, [], None

        # Step 2: traverse outward — one generic traversal for any vertex type
        nodes, edges = graph_helper.traverse_neighborhood(gremlin, vertex_ids, max_hops=3)
        if not nodes:
            return "", None, vertex_ids, None

        # Step 3: build both outputs from the same traversal data
        context = graph_helper.build_graph_context(nodes, edges, vertex_ids)
        viz = graph_helper.build_graph_viz(nodes, edges, vertex_ids)

        # Step 4: build traversal log for analytics (Level 2 only)
        traversal_log = build_graph_log_summary(nodes, edges, vertex_ids)

        logging.info(f"Layer 2: {len(vertex_ids)} starting nodes → {len(nodes)} total nodes, "
                     f"{len(edges)} edges, {len(context)} chars context")

        # Track usage on starting nodes (fire-and-forget)
        try:
            graph_helper.increment_hit_count(gremlin, vertex_ids)
        except Exception:
            pass

        return context, viz, vertex_ids, traversal_log

    except Exception as e:
        logging.warning(f"Graph context failed (proceeding without): {e}")

    return "", None, [], None


def log_to_lake(folder, record):
    """Append one JSON record to today's JSONL file in the analytics blob container.

    Uses AppendBlob — designed for concurrent writes, each append_block() is atomic.
    Folder examples: "conversations", "feedback"
    Path written: analytics/{folder}/YYYY/MM/DD.jsonl

    IMPORTANT: Wrapped defensively — a logging failure must never break the chat response.
    """
    try:
        blob_service = get_blob_service_client()
        container = blob_service.get_container_client("analytics")

        # Create the analytics container if it doesn't exist yet
        try:
            container.create_container()
        except Exception:
            pass  # already exists

        today = datetime.now(timezone.utc)
        blob_path = f"{folder}/{today.year}/{today.month:02d}/{today.day:02d}.jsonl"
        blob_client = container.get_blob_client(blob_path)

        # Create append blob ONLY if it doesn't exist yet
        # if_none_match="*" = atomic "create only if missing" — without this,
        # create_append_blob() silently overwrites the existing blob with an empty one
        try:
            blob_client.create_append_blob(if_none_match="*")
        except Exception:
            pass  # blob already exists — just append below

        line = json.dumps(record) + "\n"
        blob_client.append_block(line.encode("utf-8"))

    except Exception as e:
        # Never let analytics logging break the main chat response
        logging.warning(f"log_to_lake({folder}) failed: {e}")


def log_graph_traversal(conversation_id, turn_id, turn_number, timestamp, traversal_log):
    """Write flat JSONL files for graph traversal analysis (developer use).

    Splits the traversal into two tables:
      graph-nodes — one row per node (id, name, type, hop, is_starting_node)
      graph-edges — one row per edge (from_id, to_id, label)

    Both include conversation_id + turn_id for joining to conversations table in Power BI.
    Fire-and-forget — failures never break the chat response.
    """
    try:
        starting_set = set(traversal_log.get("starting_ids", []))

        # One row per node in the traversal
        for node in traversal_log.get("nodes_summary", []):
            log_to_lake("graph-nodes", {
                "timestamp": timestamp,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "turn_number": turn_number,
                "node_id": node.get("id", ""),
                "node_name": node.get("name", ""),
                "node_type": node.get("type", ""),
                "hop": node.get("hop", -1),
                "is_starting_node": node.get("id", "") in starting_set,
            })

        # One row per edge in the traversal
        for edge in traversal_log.get("edges_summary", []):
            log_to_lake("graph-edges", {
                "timestamp": timestamp,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "turn_number": turn_number,
                "from_id": edge.get("from", ""),
                "to_id": edge.get("to", ""),
                "label": edge.get("label", ""),
            })

    except Exception as e:
        logging.warning(f"log_graph_traversal failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# CITATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════
#
# The agent (azure_ai_search tool) outputs citations in several inconsistent
# formats depending on how Foundry and the LLM interact on a given run:
#
#   Format A: (Name) 【N:M†source】      — parenthetical + Foundry marker
#   Format B: [Name](blob_url)           — markdown link to blob storage
#   Format C: [Name]()                   — empty-URL markdown link
#   Format D: ([Name](blob_url) ts)      — markdown link wrapped in parens + timestamp
#   Format E: (Name)(url)                — name and URL in separate parens
#   Format F: (Name (url))               — URL embedded inside name parens
#   Format G: [Name]                     — single-bracket, no URL
#   Format H: [[Name]]                   — double-bracket, no URL
#   Format I: (Name](url)                — broken hybrid: ( instead of [ at start
#
# IMPORTANT: Video transcript names like "Davenport Machine Model B - Preventive
# Maintenance" reference .md files in blob storage that have NO value as links.
# They must be converted to YouTube URLs via YOUTUBE_VIDEO_MAP. Timestamps like
# "04:14–05:22" (note: agent uses en-dash U+2013, not hyphen) should become
# YouTube deep links (&t=254).
#
# Pipeline order matters — each step handles one format and normalizes for the
# next. Adding/reordering steps can break the chain.
#
# Pipeline (11 steps, both streaming and non-streaming):
#   1. process_citations         — Format A: (Name)【marker】 → [Name](url) or (Name)
#   1b. fix_broken_markdown_links — Format I: (Name](url) → [Name](url)
#   2. clean_search_service_urls — strips .search.windows.net URLs (not real blob URLs)
#   3. fill_empty_url_citations  — Format C/D: [Name]() → YouTube or (Name) for fallback
#   3b. fix_fake_markdown_links  — [Category](DocName) → [Category] (DocName)
#                                  Agent mimics [Tooling] tags from Layer 2 diagnostic context
#   4. convert_inline_url        — Format E: (Name)(url) → [Name](url)
#   5. convert_embedded_url      — Format F: (Name (url)) → [Name](url)
#   6. convert_bracket_citations — Format H: [[Name]] → (Name)
#   7. convert_single_bracket    — Format G: [Name] → (Name)
#   8. fallback_link_citations   — (Name) → [Name](blob_url or YouTube)
#                                  Also handles Format D via embedded markdown detection
#   9. transform_transcript_urls — Format B: [Name](blob_url) → [Name](YouTube)
#
# KEY GOTCHA: fallback_link_citations (step 8) matches ANY (text) not preceded
# by ]. This can grab Format D content ([Name](blob_url) timestamp) that still
# has outer parens. The replace_unlinked function detects embedded markdown links
# and handles them properly instead of nesting broken links.
# ═══════════════════════════════════════════════════════════════════════════════


def transform_transcript_urls_to_youtube(text):
    """Replace transcript URLs in response text with YouTube URLs.

    Changes links from video-training/*.md to YouTube URLs with timestamps.
    Extracts timestamps from surrounding text (e.g., "02:28-02:38" or "04:14").
    """
    # Pattern: [link text](https://storage.blob.../video-training/Name.md) optional_timestamp
    # Use .+? (non-greedy) to handle filenames with parentheses like "(part 1)"
    # Timestamp separator: hyphen OR en-dash (U+2013) — agent uses both
    pattern = rf'\[([^\]]+)\]\((https://{STORAGE_ACCOUNT}\.blob\.core\.windows\.net/{TRANSCRIPT_CONTAINER}/(.+?)\.md)\)(\s*(\d{{1,2}}:\d{{2}}(?:[^\d\s]\d{{1,2}}:\d{{2}})?))?'

    def replace_with_youtube(match):
        link_text = match.group(1)
        video_name_encoded = match.group(3)
        timestamp_str = match.group(5)  # e.g., "02:28" or "02:28-02:38"

        from urllib.parse import unquote
        video_name = unquote(video_name_encoded)

        youtube_id = YOUTUBE_VIDEO_MAP.get(video_name)
        if not youtube_id:
            return match.group(0)

        youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"

        if timestamp_str:
            # Normalize en-dash/em-dash to hyphen before splitting (agent uses both)
            time_part = timestamp_str.replace('\u2013', '-').replace('\u2014', '-').split('-')[0]
            parts = time_part.split(':')
            if len(parts) == 2:
                minutes, seconds = int(parts[0]), int(parts[1])
                total_seconds = minutes * 60 + seconds
                youtube_url += f"&t={total_seconds}"

        display_text = link_text
        if timestamp_str:
            display_text = f"{link_text} {timestamp_str}"
        return f"[{display_text}]({youtube_url})"

    result = re.sub(pattern, replace_with_youtube, text)

    # Also handle plain URLs without markdown formatting
    plain_pattern = rf'(https://{STORAGE_ACCOUNT}\.blob\.core\.windows\.net/{TRANSCRIPT_CONTAINER}/(.+?)\.md)(?=[\s")\]]|$)'

    def replace_plain_url(match):
        full_url = match.group(1)
        video_name_encoded = match.group(2)
        from urllib.parse import unquote
        video_name = unquote(video_name_encoded)
        youtube_id = YOUTUBE_VIDEO_MAP.get(video_name)
        if youtube_id:
            return f"https://www.youtube.com/watch?v={youtube_id}"
        return full_url

    return re.sub(plain_pattern, replace_plain_url, result)


def extract_blob_urls_from_response(response):
    """Extract real blob storage URLs from the response.

    The unified index embeds blob URLs as [source: URL] prefixes in snippet text.
    The azure_ai_search tool returns these snippets in its output. This function
    searches the full serialized response to find those real blob URLs, building
    a lookup for citation linking.

    Returns: dict of {lowercase_display_name: (display_name, blob_url)}
    """
    url_lookup = {}
    try:
        response_dict = response.to_dict()
        raw = json.dumps(response_dict)

        # Find [source: URL] patterns embedded in search result snippets
        for url in re.findall(r'\[source:\s*(https://[^\]\\\"]+)\]', raw):
            if 'blob.core.windows.net' in url:
                filename = unquote(url.split("/")[-1])
                name = filename.rsplit(".", 1)[0]  # drop .pdf/.md
                if name:
                    url_lookup[name.lower()] = (name, url)

        # Also check the output_text for blob URLs the agent may have included directly
        output_text = getattr(response, 'output_text', '') or ''
        # Match blob URLs to file extension — allows parens in path (video names like "(part 1)")
        for url in re.findall(r'https://\w+\.blob\.core\.windows\.net/[\w-]+/[^\s"<>]+?\.(?:pdf|md|docx)', output_text):
            filename = unquote(url.split("/")[-1])
            name = filename.rsplit(".", 1)[0]
            if name and name.lower() not in url_lookup:
                url_lookup[name.lower()] = (name, url)

        logging.info(f"extract_blob_urls: found {len(url_lookup)} blob URLs: {list(url_lookup.keys())}")
    except Exception as e:
        logging.warning(f"extract_blob_urls failed: {e}")
    return url_lookup


# Cache for SAS-signed URLs — avoids regenerating for the same blob within a request
_sas_url_cache = {}
_sas_cache_time = 0
_SAS_CACHE_TTL = 3600  # 1 hour — SAS tokens are valid for 24h so this is safe


def add_sas_to_blob_url(blob_url):
    """Add a read-only SAS token to a blob URL so the browser can open it.

    Uses user delegation SAS via managed identity (no storage account key needed).
    Caches the delegation key for 1 hour to avoid repeated key requests.
    Falls back to returning the original URL if SAS generation fails.
    """
    global _sas_url_cache, _sas_cache_time

    if not blob_url or 'blob.core.windows.net' not in blob_url:
        return blob_url

    # Return cached SAS URL if available
    now = time.time()
    if now - _sas_cache_time < _SAS_CACHE_TTL and blob_url in _sas_url_cache:
        return _sas_url_cache[blob_url]

    try:
        from urllib.parse import urlparse, unquote, quote
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

        parsed = urlparse(blob_url)
        # e.g., host = stj6lw7vswhnnhw.blob.core.windows.net
        account_name = parsed.hostname.split('.')[0]
        # path = /container/path/to/file.pdf
        path_parts = parsed.path.lstrip('/').split('/', 1)
        if len(path_parts) != 2:
            return blob_url
        container_name, blob_name = path_parts[0], unquote(path_parts[1])

        credential = DefaultAzureCredential()
        blob_service = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=credential
        )

        # Get user delegation key (valid 24h)
        start_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        expiry_time = datetime.now(timezone.utc) + timedelta(hours=24)
        delegation_key = blob_service.get_user_delegation_key(start_time, expiry_time)

        # Generate SAS with read permission + inline content disposition for PDFs
        content_disposition = "inline" if blob_name.lower().endswith('.pdf') else None
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=blob_name,
            user_delegation_key=delegation_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry_time,
            start=start_time,
            content_disposition=content_disposition,
        )

        sas_url = f"{blob_url}?{sas_token}"

        # Cache for reuse
        _sas_url_cache[blob_url] = sas_url
        _sas_cache_time = now

        return sas_url

    except Exception as e:
        logging.warning(f"SAS token generation failed for {blob_url}: {e}")
        return blob_url


def add_sas_to_all_blob_urls(text):
    """Find all blob.core.windows.net URLs in text and add SAS tokens.

    Runs as a final pass on response text after all citation processing.
    Only modifies URLs that don't already have a query string (no double-SAS).
    """
    def replace_url(match):
        url = match.group(0)
        # Skip if already has query params (already SAS-signed)
        if '?' in url:
            return url
        return add_sas_to_blob_url(url)

    # Match blob storage URLs — stop at whitespace, quotes, closing parens/brackets
    return re.sub(
        r'https://\w+\.blob\.core\.windows\.net/[^\s"<>\)]+',
        replace_url,
        text
    )


def clean_search_service_urls(text):
    """Remove search service URL references that the agent or Foundry inserts.

    The azure_ai_search tool annotations reference the search service URL
    (e.g., https://srch-*.search.windows.net/), not the actual blob storage URL.
    These leak into the output as empty or misleading links.

    Patterns cleaned:
    - [](https://srch-...search.windows.net/...) → removed entirely
    - [text](https://srch-...search.windows.net/...) → text kept, link removed
    """
    # Remove empty links to search service: [](search-url) → ""
    text = re.sub(r'\[\]\(https?://[^)]*\.search\.windows\.net[^)]*\)\s*', '', text)
    # Unlink non-empty links to search service: [text](search-url) → text
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]*\.search\.windows\.net[^)]*\)', r'\1', text)
    # Clean up double spaces left by removals
    text = re.sub(r'  +', ' ', text)
    return text


def process_citations(response, text):
    """Replace Foundry citation markers with proper markdown links.

    When the agent uses azure_ai_search, Foundry auto-inserts 【N:M†source】 markers
    and stores annotation objects (url, title) on the response. We combine these with
    the agent's (Source Name) parenthetical to produce [Source Name](URL) links.

    IMPORTANT: azure_ai_search annotations often contain the search SERVICE URL
    (e.g., https://srch-*.search.windows.net/) instead of the real blob URL.
    When that happens, we fall back to blob URLs extracted from [source: URL] prefixes
    in the search result snippets.

    Pattern handled: (Source Name)【N:M†source】 → [Source Name](url)
    """
    try:
        response_dict = response.to_dict()

        # Build (output_idx, ann_idx) -> annotation lookup from message content
        ann_lookup = {}
        for out_idx, output_item in enumerate(response_dict.get("output", [])):
            if output_item.get("type") != "message":
                continue
            for content in output_item.get("content", []):
                for ann_idx, ann in enumerate(content.get("annotations", [])):
                    ann_lookup[(out_idx, ann_idx)] = ann
                    logging.info(
                        f"Citation annotation [{out_idx}:{ann_idx}]: "
                        f"type={ann.get('type')}, "
                        f"url={ann.get('url', '')[:100]}, "
                        f"title={ann.get('title', '')}"
                    )

        if not ann_lookup:
            logging.info("No citation annotations found — stripping markers")
            return re.sub(r'【\d+:\d+†\w+】', '', text)

        # Build blob URL lookup for fallback when annotations have search service URLs
        blob_urls = extract_blob_urls_from_response(response)

        # Replace (Source Name)【N:M†source】 → [Source Name](url)
        def replace_paren_citation(match):
            name = match.group(1).strip()
            n, m = int(match.group(2)), int(match.group(3))
            ann = ann_lookup.get((n, m), {})
            url = ann.get("url", "")

            # Skip search service URLs — they're not useful for citations
            if url and '.search.windows.net' in url:
                url = ""

            # If no good URL from annotation, try blob URL lookup by name match
            if not url and blob_urls:
                name_lower = name.lower()
                for key, (display, blob_url) in blob_urls.items():
                    if key and (name_lower in key or key in name_lower):
                        return f"([{display}]({blob_url}))"

            if url:
                return f"[{name}]({url})"
            return f"({name})"  # No URL found — keep for fallback pass

        result = re.sub(
            r'\(([^)]+)\)【(\d+):(\d+)†\w+】',
            replace_paren_citation,
            text
        )

        # Strip any remaining 【...】 markers — catches both numeric (6:1†source)
        # and text-based (【Instruction Book - Part 1 of 3】) annotation formats
        result = re.sub(r'【[^】]*】', '', result)
        return result

    except Exception as e:
        logging.warning(f"process_citations failed: {e}")
        return re.sub(r'【[^】]*】', '', text)


def fix_broken_markdown_links(text):
    """Fix (Name](url) → [Name](url) — agent sometimes writes ( instead of [.

    The agent occasionally outputs a hybrid citation format: opening paren instead
    of opening bracket, but correct ](url) closing. This creates a malformed
    markdown link that no browser or renderer can parse.

    Must run EARLY — before other steps try to parse (Name) patterns.
    """
    try:
        # Match (text](https://url) — opening ( instead of [, with valid URL
        return re.sub(
            r'\(([^)\]]+)\]\((https?://[^)]+)\)',
            r'[\1](\2)',
            text,
        )
    except Exception as e:
        logging.warning(f"fix_broken_markdown_links failed: {e}")
        return text


def convert_inline_url_citations(text):
    """Convert (Name)(URL) patterns to [Name](URL) markdown links.

    The agent sometimes writes citations as (Source Name)(https://blob.url)
    instead of using Foundry markers. This converts them to proper markdown
    before the fallback pass runs.

    Must run AFTER process_citations and clean_search_service_urls,
    but BEFORE fallback_link_citations.
    """
    try:
        # Match (Name)(https://url) — name in parens followed immediately by URL in parens
        # The name group excludes http to avoid matching (URL)(URL) pairs
        def replace_inline(match):
            name = match.group(1).strip()
            url = match.group(2).strip()
            return f"[{name}]({url})"

        result = re.sub(
            r'\(([^()]+?)\)\s*\((https?://[^)]+)\)',
            replace_inline,
            text
        )
        return result
    except Exception as e:
        logging.warning(f"convert_inline_url_citations failed: {e}")
        return text


def convert_embedded_url_citations(text):
    """Convert (Name (URL)) and (Name URL) patterns to [Name](URL) markdown links.

    The agent sometimes embeds a URL inside the same parenthetical as the citation
    name, e.g., (Instruction Book (https://blob.url/file.pdf)) or
    (Instruction Book https://blob.url/file.pdf). These need converting to
    [Name](URL) before the fallback citation linker runs, or the fallback will
    double-encode the URL.

    Must run AFTER convert_inline_url_citations, BEFORE fallback_link_citations.
    """
    try:
        # Pattern 1: (Name (https://URL)) — URL inside nested parens
        result = re.sub(
            r'\(([^()]+?)\s*\((https?://[^)]+)\)\)',
            lambda m: f"[{m.group(1).strip()}]({m.group(2).strip()})",
            text
        )

        # Pattern 2: (Name https://URL) — URL directly in same parens, no nesting
        result = re.sub(
            r'\(([^()]+?)\s+(https?://[^\s)]+)\)',
            lambda m: f"[{m.group(1).strip()}]({m.group(2).strip()})",
            result
        )

        return result
    except Exception as e:
        logging.warning(f"convert_embedded_url_citations failed: {e}")
        return text


def convert_bracket_citations(text):
    """Convert [[Name]] double-bracket citations to (Name) format.

    The agent sometimes writes citations as [[Document Name]] instead of
    (Document Name). This normalizes them so fallback_link_citations can
    match and link them.
    """
    try:
        return re.sub(r'\[\[([^\]]+)\]\]', r'(\1)', text)
    except Exception as e:
        logging.warning(f"convert_bracket_citations failed: {e}")
        return text


def fill_empty_url_citations(text):
    """Fill in empty-URL markdown links [Name]() with real URLs.

    The agent sometimes creates [Name]() when it knows the document name
    but can't resolve the URL (common with azure_ai_search annotations).
    Also handles [[Name]() timestamp] — double-bracket wrapping with timestamps.

    Priority: YOUTUBE_VIDEO_MAP first → (Name) for fallback pass.
    Must run AFTER clean_search_service_urls, BEFORE convert_bracket_citations.
    """
    def fill_url(match):
        name = match.group(1).strip()
        timestamp = match.group(2)  # may be None
        name_lower = name.lower()

        # Try YOUTUBE_VIDEO_MAP first
        for video_name, yt_id in YOUTUBE_VIDEO_MAP.items():
            if name_lower in video_name.lower() or video_name.lower() in name_lower:
                yt_url = f"https://www.youtube.com/watch?v={yt_id}"
                # Parse timestamp to seconds for YouTube deep link
                if timestamp:
                    time_part = timestamp.strip().replace('\u2013', '-').split('-')[0]
                    parts = time_part.split(':')
                    if len(parts) == 2:
                        try:
                            total_seconds = int(parts[0]) * 60 + int(parts[1])
                            yt_url += f"&t={total_seconds}"
                        except ValueError:
                            pass
                display = f"{video_name} {timestamp}" if timestamp else video_name
                return f"[{display}]({yt_url})"

        # No URL found — convert to (Name) so fallback_link_citations can try
        full_name = f"{name} {timestamp}" if timestamp else name
        return f"({full_name})"

    # Use [^\d\s] for dash — matches en-dash, em-dash, hyphen, arrow, any separator
    try:
        # Pattern 1: [[Name]() timestamp] — double-bracket wrapped citation
        pat1 = r'\[\[([^\]]+)\]\(\)\s*(\d{1,2}:\d{2}(?:[^\d\s]\d{1,2}:\d{2})?)?\]'
        logging.info(f"fill_empty_url: scanning {len(text)} chars, pattern1 matches={len(re.findall(pat1, text))}")
        text = re.sub(pat1, fill_url, text)

        # Pattern 2: [Name]() — standalone empty-URL markdown link (with optional timestamp)
        pat2 = r'\[([^\]]+)\]\(\)\s*(\d{1,2}:\d{2}(?:[^\d\s]\d{1,2}:\d{2})?)?'
        text = re.sub(pat2, fill_url, text)
        return text
    except Exception as e:
        logging.warning(f"fill_empty_url_citations failed: {e}")
        return text


def fix_fake_markdown_links(text):
    """Separate [Category](Document Name) that looks like a markdown link but isn't.

    With Layer 2 context injected, the agent sees [Tooling], [Work Holding] etc.
    in the diagnostic checklist and outputs [Category](Document Name) — which regex
    treats as a valid markdown link. This step adds a space: [Category] (Document Name)
    so subsequent steps can process category tags and document citations independently.

    Only affects patterns where the "URL" part does NOT start with http.
    Real markdown links [Name](https://...) are left untouched.
    """
    try:
        return re.sub(r'\[([^\]]+)\]\((?!https?://)', r'[\1] (', text)
    except Exception as e:
        logging.warning(f"fix_fake_markdown_links failed: {e}")
        return text


def convert_single_bracket_citations(text):
    """Convert [Name] single-bracket citations to (Name) format.

    The agent often writes citations as [Document Name] without a URL.
    This normalizes them to (Name) so fallback_link_citations can
    fuzzy-match against known blob URLs.

    Skips: markdown links [Name](url), category tags [Machine], short names.
    """
    # Known category tags the agent uses — never convert these
    category_tags = {"Tooling", "Machine", "Feeds & Speeds", "Work Holding",
                     "Stock/Material", "Stock", "General"}
    try:
        def replace_bracket(match):
            name = match.group(1).strip()
            if name in category_tags or len(name) < 8:
                return match.group(0)  # leave as-is
            return f"({name})"

        # Match [Name] NOT followed by ( (which would be a markdown link)
        return re.sub(r'\[([^\]]+)\](?!\()', replace_bracket, text)
    except Exception as e:
        logging.warning(f"convert_single_bracket_citations failed: {e}")
        return text


def fallback_link_citations(text, response):
    """Third pass: link any remaining (Name) citations that earlier passes missed.

    When the agent writes (Maintenance Manual) without Foundry's 【markers】
    or inline URLs, this function uses real blob URLs extracted from search
    result snippets (via [source: URL] prefixes) to fuzzy-match unlinked
    (Name) patterns.

    If blob URL extraction finds nothing (common in streaming responses where
    MCP tool output may not be in the completed event), falls back to constructing
    blob URLs from the known storage account + knowledge base containers.

    Must run AFTER process_citations, clean_search_service_urls, and
    convert_inline_url_citations.
    """
    try:
        # Use blob URLs from search results — NOT annotation URLs (which point to search service)
        url_lookup = extract_blob_urls_from_response(response)

        # Known category tags that should never be linked
        category_tags = {"Tooling", "Machine", "Feeds & Speeds", "Work Holding", "Stock/Material"}

        # Known knowledge base containers and their document patterns
        # Used as fallback when blob URL extraction returns nothing (streaming responses)
        known_containers = [
            "maintenance-manuals", "engineering-tips", "technical-tips",
            "troubleshooting", "video-training",
        ]

        def build_blob_url_fallback(name):
            """Construct a blob URL by matching name keywords to the right container.

            The unified index stores docs as: <container>/<filename>.pdf or .md
            The agent cites them by display name (filename minus extension).
            We match keywords in the name to pick the most likely container.

            SAFETY: If the name already contains a URL, extract and return it
            instead of constructing a new one (prevents double-nesting).
            """
            from urllib.parse import quote

            # Guard: if name already contains a URL, extract and return it directly
            url_match = re.search(r'https?://[^\s)"\]]+', name)
            if url_match:
                return url_match.group(0)

            name_lower = name.lower()

            # Check YOUTUBE_VIDEO_MAP first — video names don't always have "video"/"training" keywords
            for video_name in YOUTUBE_VIDEO_MAP:
                if name_lower in video_name.lower() or video_name.lower() in name_lower:
                    container = "video-training"
                    url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{container}/{quote(video_name)}.md"
                    return url

            # Map name keywords → most likely container
            if any(w in name_lower for w in ["manual", "instruction", "operation"]):
                container = "maintenance-manuals"
            elif "troubleshoot" in name_lower:
                container = "troubleshooting"
            elif "training" in name_lower or "video" in name_lower:
                container = "video-training"
                # Video transcripts are markdown
                url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{container}/{quote(name)}.md"
                return url
            elif "engineering" in name_lower:
                container = "engineering-tips"
            elif "tips" in name_lower or "technical" in name_lower:
                container = "technical-tips"
            else:
                # Default to maintenance-manuals — most citations are from there
                container = "maintenance-manuals"

            url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{container}/{quote(name)}.pdf"
            return url

        def safe_markdown_link(display, url):
            """Build [display](url) with parens encoded so markdown doesn't break."""
            safe_url = url.replace('(', '%28').replace(')', '%29')
            return f"[{display}]({safe_url})"

        def replace_unlinked(match):
            name = match.group(1).strip()
            # Skip category tags and very short names (likely not citations)
            if name in category_tags or len(name) < 8:
                return match.group(0)

            # Skip comma-separated lists — they're descriptions, not document names
            if name.count(',') >= 2:
                return match.group(0)

            # If the name already contains a markdown link [text](url), extract properly.
            # This happens when fallback_link_citations captures ([Name](blob_url) timestamp)
            # — the agent put a valid markdown link inside parens.
            md_link = re.search(r'\[([^\]]+)\]\((https?://[^)]+)\)', name)
            if md_link:
                display = md_link.group(1).strip()
                url = md_link.group(2).strip()
                # Get any text after the markdown link (e.g., timestamps "04:14–05:22")
                suffix = name[md_link.end():].strip()
                # Video transcripts (.md in video-training) → YouTube with timestamp
                if f'/{TRANSCRIPT_CONTAINER}/' in url and url.endswith('.md'):
                    video_name_encoded = url.split('/')[-1].rsplit('.', 1)[0]
                    video_name = unquote(video_name_encoded)
                    yt_id = YOUTUBE_VIDEO_MAP.get(video_name)
                    if yt_id:
                        yt_url = f"https://www.youtube.com/watch?v={yt_id}"
                        if suffix:
                            # Parse first timestamp for YouTube deep link
                            ts = re.search(r'(\d{1,2}):(\d{2})', suffix)
                            if ts:
                                total_seconds = int(ts.group(1)) * 60 + int(ts.group(2))
                                yt_url += f"&t={total_seconds}"
                        link_display = f"{video_name} {suffix}" if suffix else video_name
                        return safe_markdown_link(link_display, yt_url)
                # Non-video markdown link — preserve with suffix
                link_display = f"{display} {suffix}" if suffix else display
                return safe_markdown_link(link_display, url)

            # If the name contains a bare URL (no markdown syntax), extract and link
            embedded_url = re.search(r'https?://[^\s)"\]]+', name)
            if embedded_url:
                url = embedded_url.group(0)
                clean_name = re.sub(r'https?://[^\s)"\]]+', '', name).strip()
                clean_name = re.sub(r'\.\w{2,4}$', '', clean_name).strip(' .')
                if not clean_name:
                    filename = unquote(url.split("/")[-1])
                    clean_name = filename.rsplit(".", 1)[0]
                return safe_markdown_link(clean_name, url)

            name_lower = name.lower()
            # First try: videos always go to YouTube (before url_lookup which has blob URLs)
            for video_name, yt_id in YOUTUBE_VIDEO_MAP.items():
                if name_lower in video_name.lower() or video_name.lower() in name_lower:
                    yt_url = f"https://www.youtube.com/watch?v={yt_id}"
                    return safe_markdown_link(video_name, yt_url)

            # Second try: match against actual blob URLs from response
            for key, (display, url) in url_lookup.items():
                if key and (name_lower in key or key in name_lower):
                    return safe_markdown_link(display, url)

            # Third try: construct blob URL from known storage layout
            # Only for names that look like document citations (contain common doc words)
            # Note: "part" removed — too many false positives on descriptive text
            doc_indicators = ["manual", "instruction", "book", "training",
                              "tips", "troubleshooting", "operations", "pages",
                              "algorithm"]
            if any(ind in name_lower for ind in doc_indicators):
                url = build_blob_url_fallback(name)
                if url:
                    return safe_markdown_link(name, url)
            return match.group(0)  # no match found, leave as-is

        # Match (Name) that isn't part of a markdown link — negative lookbehind for ]
        # Allows one level of balanced inner parens so video names like "(part 1)" work
        result = re.sub(r'(?<!\])\(([^()]+(?:\([^()]*\)[^()]*)*)\)(?![\[(])', replace_unlinked, text)

        # Insert space between adjacent markdown links so they don't run together
        # e.g. [A](url1)[B](url2) → [A](url1) [B](url2)
        result = re.sub(r'\)\[', ') [', result)

        return result

    except Exception as e:
        logging.warning(f"fallback_link_citations failed: {e}")
        return text


def extract_reasoning_trace(response):
    """Extract reasoning trace from agent response for debugging."""
    trace = {
        "agent": None,
        "query_intents": [],
        "sources_found": 0,
        "tokens": {}
    }

    try:
        response_dict = response.to_dict()

        if "agent" in response_dict:
            agent = response_dict["agent"]
            trace["agent"] = f"{agent.get('name', 'unknown')} v{agent.get('version', '?')}"

        if "usage" in response_dict:
            usage = response_dict["usage"]
            trace["tokens"] = {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "total": usage.get("total_tokens", 0)
            }

        for item in response_dict.get("output", []):
            if item.get("type") == "mcp_call":
                args_str = item.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                    intents = args.get("request", {}).get("knowledgeAgentIntents", [])
                    trace["query_intents"] = intents
                except (json.JSONDecodeError, KeyError):
                    pass

                output_str = item.get("output", "")
                if "Retrieved" in output_str:
                    match = re.search(r"Retrieved (\d+) documents", output_str)
                    if match:
                        trace["sources_found"] = int(match.group(1))

    except Exception as e:
        logging.warning(f"Failed to extract trace: {e}")

    return trace


def generate_turn_id():
    """Generate a short unique turn identifier (e.g., 'turn_a1b2c3d4')."""
    return f"turn_{uuid.uuid4().hex[:8]}"


def extract_sources_cited(text):
    """Extract unique sources from markdown links in the response.

    Parses [Name](url) patterns from the processed response text.
    Returns list of {"name": ..., "url": ...} dicts, deduplicated by URL.
    """
    matches = re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)', text)
    seen = set()
    sources = []
    for name, url in matches:
        if url not in seen:
            seen.add(url)
            sources.append({"name": name, "url": url})
    return sources


def extract_categories_tagged(text):
    """Extract unique category tags like [Tooling], [Machine] from response text.

    Only matches known Davenport categories to avoid false positives
    from markdown links or other bracketed text.
    """
    known = {"Tooling", "Machine", "Feeds & Speeds", "Work Holding", "Stock/Material"}
    found = re.findall(r'\[([^\]]+)\]', text)
    # dict.fromkeys preserves first-seen order while deduplicating
    return list(dict.fromkeys(cat for cat in found if cat in known))


# ---------------------------------------------------------------------------
# Login endpoint — no auth required on this one
# ---------------------------------------------------------------------------

@app.route(route="auth/login", methods=["POST"])
async def login(req: Request) -> JSONResponse:
    """Authenticate shop floor user and return JWT token."""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    username = body.get("username", "").strip().lower()
    password = body.get("password", "")

    if not username or not password:
        return JSONResponse({"error": "Username and password required"}, status_code=400)

    # Fix #4: Brute force protection — 5 failures in 5 min triggers 60s cooldown
    if auth_helper.check_rate_limit(username):
        logging.warning(f"Rate-limited login attempt for user: {username}")
        return JSONResponse({"error": "Too many failed attempts, try again later"}, status_code=429)

    user = auth_helper.authenticate_user(username, password)
    if not user:
        auth_helper.record_login_failure(username)
        logging.warning(f"Failed login attempt for user: {username}")
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)

    auth_helper.clear_login_failures(username)
    token = auth_helper.create_token(user["username"], user["display_name"], user["role"])
    logging.info(f"Successful login for user: {username} ({user['display_name']})")
    return JSONResponse({
        "token": token,
        "display_name": user["display_name"],
        "role": user["role"],
        "expires_in": auth_helper.TOKEN_EXPIRY_SECONDS,
    })


# ---------------------------------------------------------------------------
# Non-streaming chat endpoint — fallback if streaming is unavailable
# ---------------------------------------------------------------------------

@app.route(route="chat", methods=["POST"])
async def chat(req: Request) -> JSONResponse:
    """Handle chat requests (non-streaming fallback)."""
    logging.info('Chat function processing request')

    # Auth check — returns JWT payload dict on success, JSONResponse on failure
    auth_result = auth_helper.require_auth(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    display_name = auth_result.get("display_name", auth_result.get("sub", ""))

    try:
        req_body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)

    message = req_body.get('message')
    conversation_id = req_body.get('conversation_id')
    reasoning_level = req_body.get('reasoning_level', 'thorough')

    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    agent_name = AGENTS.get(reasoning_level, DEFAULT_AGENT)
    logging.info(f"Using agent: {agent_name} (reasoning_level: {reasoning_level})")

    try:
        timings = {}

        t0 = time.time()
        _, openai_client = get_clients()
        timings["client_init"] = round((time.time() - t0) * 1000)

        t1 = time.time()
        if not conversation_id:
            conversation = openai_client.conversations.create()
            conversation_id = conversation.id
        timings["conversation_create"] = round((time.time() - t1) * 1000)

        # V3 Graph RAG: two-layer context
        t_graph = time.time()
        turn_number = req_body.get("turn_number", 1)
        recent_messages = req_body.get("recent_messages", [])
        # Layer 1: World model — only on turn 1 (Foundry conversation retains it for later turns)
        world_model = get_world_model() if turn_number <= 1 else ""
        # Layer 2: Generic traversal → agent context + sidebar viz (one call, both outputs)
        graph_context, graph_viz, graph_ids, traversal_log = get_graph_context_for_message(message, recent_messages=recent_messages)
        # Assemble agent input with available context
        parts = []
        if world_model:
            parts.append(world_model)
        if graph_context:
            parts.append(graph_context)
        parts.append(f"USER QUESTION:\n{message}")
        agent_input = "\n\n".join(parts)
        graph_active = bool(world_model or graph_context)
        timings["graph_context"] = round((time.time() - t_graph) * 1000)

        t2 = time.time()
        response = openai_client.responses.create(
            conversation=conversation_id,
            tool_choice="required",
            input=agent_input,
            extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
            truncation="auto",  # drop oldest messages when context grows too large
        )
        timings["agent_response"] = round((time.time() - t2) * 1000)
        timings["total"] = round((time.time() - t0) * 1000)

        trace = extract_reasoning_trace(response)
        trace["timings"] = timings
        trace["graph_starting_ids"] = graph_ids or []
        trace["graph_context_used"] = graph_active
        trace["graph_layer2_chars"] = len(graph_context) if graph_context else 0
        trace["pipeline_version"] = PIPELINE_VERSION

        # Citation pipeline: markers → fix broken → strip search URLs → fill empty → inline → embedded → fallback (Name) → YouTube
        response_text = process_citations(response, response.output_text)
        response_text = fix_broken_markdown_links(response_text)
        response_text = clean_search_service_urls(response_text)
        response_text = fill_empty_url_citations(response_text)
        response_text = fix_fake_markdown_links(response_text)
        response_text = convert_inline_url_citations(response_text)
        response_text = convert_embedded_url_citations(response_text)
        response_text = convert_bracket_citations(response_text)
        response_text = convert_single_bracket_citations(response_text)
        response_text = fallback_link_citations(response_text, response)
        response_text = transform_transcript_urls_to_youtube(response_text)
        response_text = add_sas_to_all_blob_urls(response_text)  # SAS tokens for browser access
        logging.info(f"Timings: {timings}")

        # Extract structured metadata from the processed response
        turn_id = generate_turn_id()
        turn_number = req_body.get("turn_number", 1)
        sources = extract_sources_cited(response_text)
        categories = extract_categories_tagged(response_text)
        trace["sources_found"] = len(sources)

        # Log every interaction to the data lake (fire-and-forget — never blocks response)
        log_to_lake("conversations", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "turn_number": turn_number,
            "is_first_turn": turn_number == 1,
            "initials": display_name,  # server-authoritative identity from JWT
            "message": message[:4000],
            "response": response_text[:4000],
            "agent": agent_name,
            "reasoning_level": reasoning_level,
            "duration_ms": timings["total"],
            "timing_search_ms": 0,  # search happens inside Foundry agent — not separately measurable
            "timing_agent_ms": timings.get("agent_response", 0),
            "timing_graph_ms": timings.get("graph_context", 0),
            "timing_citations_ms": timings.get("total", 0) - timings.get("agent_response", 0) - timings.get("graph_context", 0) - timings.get("client_init", 0) - timings.get("conversation_create", 0),
            "sources_cited": sources,
            "categories_tagged": categories,
            "source_count": len(sources),
            "category_count": len(categories),
            "graph_starting_ids": graph_ids or [],
            "graph_starting_names": traversal_log["starting_names"] if traversal_log else [],
            "graph_context_provided": graph_active,
            "graph_node_count": traversal_log["node_count"] if traversal_log else 0,
            "graph_edge_count": traversal_log["edge_count"] if traversal_log else 0,
            # Performance visibility — token and context sizes
            "agent_input_chars": len(agent_input),
            "graph_context_chars": len(graph_context) if graph_context else 0,
            "world_model_chars": len(world_model) if world_model else 0,
            "input_tokens": trace.get("tokens", {}).get("input", 0),
            "output_tokens": trace.get("tokens", {}).get("output", 0),
            "total_tokens": trace.get("tokens", {}).get("total", 0),
        })

        # Log graph traversal details to separate flat files (developer analysis)
        if traversal_log:
            log_graph_traversal(conversation_id, turn_id, turn_number,
                                datetime.now(timezone.utc).isoformat(), traversal_log)

        # Track graph node usage (fire-and-forget)
        if graph_ids:
            try:
                import graph_helper as gh_track
                gremlin_track = get_gremlin_client()
                if gremlin_track:
                    gh_track.increment_hit_count(gremlin_track, graph_ids)
            except Exception as e:
                logging.warning(f"Graph hit tracking failed: {e}")

        result = {
            "response": response_text,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "trace": trace,
        }
        if graph_viz:
            result["graph_viz"] = graph_viz

        return JSONResponse(result, status_code=200)

    except Exception as e:
        logging.error(f"Error processing chat: {str(e)}")
        return JSONResponse({"error": "Internal server error"}, status_code=500)


# ---------------------------------------------------------------------------
# Streaming chat endpoint — tokens appear as they're generated
# ---------------------------------------------------------------------------

@app.route(route="chat/stream", methods=["POST"])
async def chat_stream(req: Request) -> StreamingResponse:
    """Stream chat response using Server-Sent Events.

    Emits SSE events:
      {type: 'session', conversation_id}   — immediately, so frontend can resume
      {type: 'status', text}               — 'Searching knowledge base...'
      {type: 'delta', text}                — token chunk (if agent supports per-token streaming)
      {type: 'done', full_text, trace}     — final complete text + trace
      {type: 'error', text}                — on failure

    Note: stream=True with agent_reference may produce per-token deltas OR a single
    response.completed event depending on whether the Foundry agent passes through
    token-level events. The generator handles both cases gracefully.
    """
    # Auth check — returns JWT payload dict on success, JSONResponse on failure
    auth_result = auth_helper.require_auth(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    display_name = auth_result.get("display_name", auth_result.get("sub", ""))

    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)

    message = body.get("message")
    conversation_id = body.get("conversation_id")
    reasoning_level = body.get("reasoning_level", "thorough")
    turn_number = body.get("turn_number", 1)

    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    agent_name = AGENTS.get(reasoning_level, DEFAULT_AGENT)
    logging.info(f"Streaming: agent={agent_name}")

    _, openai_client = get_clients()

    # Conversation history management: reset after MAX_TURNS to bound token growth.
    # Summarize what was discussed, start fresh conversation with summary injected.
    conversation_reset = False
    if turn_number >= MAX_TURNS_BEFORE_RESET and conversation_id:
        logging.info(f"Turn {turn_number} >= {MAX_TURNS_BEFORE_RESET}: resetting conversation with summary")
        message_history = body.get("message_history", [])
        conversation_summary = summarize_conversation(message_history)
        # Start a fresh Foundry conversation
        conversation = openai_client.conversations.create()
        conversation_id = conversation.id
        turn_number = 1  # reset counter
        conversation_reset = True
    else:
        conversation_summary = ""

    if not conversation_id:
        conversation = openai_client.conversations.create()
        conversation_id = conversation.id

    # V3 Graph RAG: two-layer context (before streaming starts)
    t_graph_start = time.time()
    recent_messages = body.get("recent_messages", [])
    # Layer 1: World model — on turn 1 OR after reset (new conversation needs machine context)
    world_model = get_world_model() if (turn_number <= 1 or conversation_reset) else ""
    # Layer 2: Generic traversal → agent context + sidebar viz (one call, both outputs)
    graph_context, graph_viz, graph_ids, traversal_log = get_graph_context_for_message(message, recent_messages=recent_messages)
    graph_ms = round((time.time() - t_graph_start) * 1000)
    # Assemble agent input with available context
    parts = []
    if conversation_summary:
        parts.append(conversation_summary)
    if world_model:
        parts.append(world_model)
    if graph_context:
        parts.append(graph_context)
    parts.append(f"USER QUESTION:\n{message}")
    agent_input = "\n\n".join(parts)
    graph_active = bool(world_model or graph_context)

    async def event_generator():
        # Send conversation_id immediately so the frontend can persist it
        session_event = {'type': 'session', 'conversation_id': conversation_id}
        if conversation_reset:
            session_event['reset'] = True  # tell frontend to reset turn counter
            session_event['turn_number'] = 1
        yield f"data: {json.dumps(session_event)}\n\n"
        status_msg = "Analyzing machine knowledge..." if graph_active else "Searching knowledge base..."
        yield f"data: {json.dumps({'type': 'status', 'text': status_msg})}\n\n"

        try:
            t_start = time.time()
            response = openai_client.responses.create(
                conversation=conversation_id,
                tool_choice="required",
                input=agent_input,
                extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
                stream=True,
            )

            full_text = ""
            completed = False
            for event in response:
                event_type = getattr(event, "type", None)

                if event_type == "response.output_text.delta":
                    # Per-token streaming — agent passes through token deltas
                    delta = getattr(event, "delta", "")
                    full_text += delta
                    yield f"data: {json.dumps({'type': 'delta', 'text': delta})}\n\n"

                elif event_type == "response.completed":
                    # Signals end of stream — use accumulated deltas or pull full text
                    if not full_text:
                        full_text = getattr(event.response, "output_text", "")
                    # Citation pipeline: markers → fix broken → strip search URLs → fill empty → inline → embedded → fallback (Name) → YouTube
                    t_cite_start = time.time()
                    full_text = process_citations(event.response, full_text)
                    full_text = fix_broken_markdown_links(full_text)
                    full_text = clean_search_service_urls(full_text)
                    full_text = fill_empty_url_citations(full_text)
                    full_text = fix_fake_markdown_links(full_text)
                    full_text = convert_inline_url_citations(full_text)
                    full_text = convert_embedded_url_citations(full_text)
                    full_text = convert_bracket_citations(full_text)
                    full_text = convert_single_bracket_citations(full_text)
                    full_text = fallback_link_citations(full_text, event.response)
                    full_text = transform_transcript_urls_to_youtube(full_text)
                    full_text = add_sas_to_all_blob_urls(full_text)  # SAS tokens for browser access
                    citations_ms = round((time.time() - t_cite_start) * 1000)
                    elapsed_ms = round((time.time() - t_start) * 1000)
                    # Total wall time includes graph + agent + citations
                    total_ms = graph_ms + elapsed_ms
                    trace = extract_reasoning_trace(event.response)
                    trace["timings"] = {"total": total_ms, "graph_context": graph_ms, "agent_response": elapsed_ms, "citations": citations_ms}
                    trace["graph_starting_ids"] = graph_ids or []
                    trace["graph_context_used"] = graph_active
                    trace["graph_layer2_chars"] = len(graph_context) if graph_context else 0
                    trace["pipeline_version"] = PIPELINE_VERSION
                    # Extract sources before yielding so trace includes the count
                    sources = extract_sources_cited(full_text)
                    categories = extract_categories_tagged(full_text)
                    trace["sources_found"] = len(sources)
                    turn_id = generate_turn_id()

                    # Send graph viz as SSE event (already computed before streaming started)
                    if graph_viz:
                        yield f"data: {json.dumps({'type': 'graph', 'data': graph_viz})}\n\n"

                    yield f"data: {json.dumps({'type': 'done', 'full_text': full_text, 'turn_id': turn_id, 'trace': trace})}\n\n"
                    completed = True

                    # Log to data lake after yielding (display_name captured from JWT in outer scope)
                    log_to_lake("conversations", {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "turn_number": turn_number,
                        "is_first_turn": turn_number == 1,
                        "initials": display_name,  # server-authoritative identity from JWT
                        "message": message[:4000],
                        "response": full_text[:4000],
                        "agent": agent_name,
                        "reasoning_level": reasoning_level,
                        "duration_ms": total_ms,
                        "timing_agent_ms": elapsed_ms,  # agent call (includes Foundry-side search + LLM)
                        "timing_search_ms": 0,  # search happens inside Foundry agent — not separately measurable
                        "timing_graph_ms": graph_ms,  # graph context lookup (world model + traversal)
                        "timing_citations_ms": citations_ms,
                        "sources_cited": sources,
                        "categories_tagged": categories,
                        "source_count": len(sources),
                        "category_count": len(categories),
                        "graph_starting_ids": graph_ids or [],
                        "graph_starting_names": traversal_log["starting_names"] if traversal_log else [],
                        "graph_context_provided": graph_active,
                        "conversation_reset": conversation_reset,
                        "graph_node_count": traversal_log["node_count"] if traversal_log else 0,
                        "graph_edge_count": traversal_log["edge_count"] if traversal_log else 0,
                        # Performance visibility — token and context sizes
                        "agent_input_chars": len(agent_input),
                        "graph_context_chars": len(graph_context) if graph_context else 0,
                        "world_model_chars": len(world_model) if world_model else 0,
                        "input_tokens": trace.get("tokens", {}).get("input", 0),
                        "output_tokens": trace.get("tokens", {}).get("output", 0),
                        "total_tokens": trace.get("tokens", {}).get("total", 0),
                    })

                    # Log graph traversal details to separate flat files (developer analysis)
                    if traversal_log:
                        log_graph_traversal(conversation_id, turn_id, turn_number,
                                            datetime.now(timezone.utc).isoformat(), traversal_log)

                    # Track graph node usage (fire-and-forget)
                    if graph_ids:
                        try:
                            import graph_helper as gh_track
                            gremlin_track = get_gremlin_client()
                            if gremlin_track:
                                gh_track.increment_hit_count(gremlin_track, graph_ids)
                        except Exception as e:
                            logging.warning(f"Graph hit tracking failed: {e}")

            # Safety: if stream ended without a completed event, send what we have
            if full_text and not completed:
                full_text = re.sub(r'【\d+:\d+†\w+】', '', full_text)  # strip markers, no response object available
                full_text = transform_transcript_urls_to_youtube(full_text)
                full_text = add_sas_to_all_blob_urls(full_text)
                yield f"data: {json.dumps({'type': 'done', 'full_text': full_text, 'trace': {}})}\n\n"

        except Exception as e:
            logging.error(f"Streaming error: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Feedback endpoints — thumbs up/down, flag, and notes
# ---------------------------------------------------------------------------

@app.route(route="feedback", methods=["POST"])
async def submit_feedback(req: Request) -> JSONResponse:
    """Save user feedback (thumbs up/down/flag) for a response.

    Upserts by turn_id — re-rating or adding notes to the same turn
    updates the existing row instead of creating a duplicate.
    """
    # Auth check — returns JWT payload dict on success
    auth_result = auth_helper.require_auth(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    display_name = auth_result.get("display_name", auth_result.get("sub", ""))

    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    turn_id = body.get("turn_id", "")
    if not turn_id:
        return JSONResponse({"error": "turn_id is required"}, status_code=400)

    now = datetime.now(timezone.utc)
    entity = {
        "PartitionKey": now.strftime("%Y-%m-%d"),
        "RowKey": turn_id,  # upsert key — one feedback row per turn
        "conversation_id": body.get("conversation_id", ""),
        "turn_id": turn_id,
        "turn_number": body.get("turn_number", 0),
        "message": body.get("message", "")[:32000],
        "response": body.get("response", "")[:32000],
        "rating": body.get("rating", ""),
        "notes": body.get("notes", "")[:4000],
        "initials": body.get("initials", ""),  # who typed the comment (shop floor identity)
        "username": display_name,  # who is logged in (JWT identity)
        "reasoning_level": body.get("reasoning_level", ""),
        # Prior turns in the conversation — allows admin to see full thread context
        "conversation_history": json.dumps(body.get("conversation_history", []))[:32000],
    }

    try:
        table = get_table_client()
        # Upsert (merge) — updates existing fields, preserves any not in this request
        from azure.data.tables import UpdateMode
        table.upsert_entity(entity, mode=UpdateMode.MERGE)
        logging.info(f"Feedback saved: {entity['rating']} from {display_name} (initials: {entity['initials'] or 'none'})")

        # Also log to data lake for Power BI analytics (fire-and-forget)
        log_to_lake("feedback", {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "conversation_id": entity["conversation_id"],
            "turn_id": entity["turn_id"],
            "turn_number": entity["turn_number"],
            "message": body.get("message", "")[:4000],
            "response": body.get("response", "")[:4000],
            "rating": entity["rating"],
            "initials": entity["initials"],  # shop floor identity
            "username": display_name,  # JWT identity
            "notes": entity["notes"],
            "reasoning_level": entity["reasoning_level"],
        })

        return JSONResponse({"status": "saved"}, status_code=201)
    except Exception as e:
        logging.error(f"Failed to save feedback: {str(e)}")
        return JSONResponse({"error": "Failed to save feedback"}, status_code=500)


@app.route(route="feedback", methods=["GET"])
async def get_feedback(req: Request) -> JSONResponse:
    """Retrieve feedback entries for admin review.

    Optional query params: ?rating=flagged&date=2026-02-25
    """
    # Fix #3: Admin-only — feedback contains all user conversations
    auth_result = auth_helper.require_admin(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    rating_filter = req.query_params.get("rating")
    date_filter = req.query_params.get("date")

    # Fix #2: Validate inputs to prevent OData injection
    valid_ratings = {"thumbs_up", "thumbs_down", "flagged"}
    if rating_filter and rating_filter not in valid_ratings:
        return JSONResponse({"error": "Invalid rating filter"}, status_code=400)
    if date_filter and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_filter):
        return JSONResponse({"error": "Invalid date format, use YYYY-MM-DD"}, status_code=400)

    filters = []
    if date_filter:
        filters.append(f"PartitionKey eq '{date_filter}'")
    if rating_filter:
        filters.append(f"rating eq '{rating_filter}'")
    query_filter = " and ".join(filters) if filters else None

    try:
        table = get_table_client()
        entities = list(table.query_entities(query_filter=query_filter))
        results = [
            {
                "date": entity.get("PartitionKey"),
                "id": entity.get("RowKey"),
                "conversation_id": entity.get("conversation_id"),
                "message": entity.get("message"),
                "response": entity.get("response"),
                "rating": entity.get("rating"),
                "notes": entity.get("notes"),
                "initials": entity.get("initials"),
                "username": entity.get("username", ""),
                "reasoning_level": entity.get("reasoning_level"),
                "conversation_history": entity.get("conversation_history", "[]"),
            }
            for entity in entities
        ]
        return JSONResponse(results, status_code=200)
    except Exception as e:
        logging.error(f"Failed to get feedback: {str(e)}")
        return JSONResponse({"error": "Failed to retrieve feedback"}, status_code=500)


@app.route(route="feedback/{partition_key}/{row_key}", methods=["PATCH"])
async def update_feedback(req: Request) -> JSONResponse:
    """Update editable fields on a feedback entry (admin only).

    Currently supports updating initials only — Rich uses this to fix
    entries where a machinist forgot to enter their initials.
    """
    auth_result = auth_helper.require_admin(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    partition_key = req.path_params.get("partition_key", "")
    row_key = req.path_params.get("row_key", "")

    # Validate partition key is a date (prevents OData injection)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", partition_key):
        return JSONResponse({"error": "Invalid partition_key"}, status_code=400)
    if not row_key or len(row_key) > 200:
        return JSONResponse({"error": "Invalid row_key"}, status_code=400)

    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    initials = body.get("initials", "").strip()[:20]
    if not initials:
        return JSONResponse({"error": "initials is required"}, status_code=400)

    try:
        table = get_table_client()
        from azure.data.tables import UpdateMode
        # Merge update — only changes initials, preserves all other fields
        table.update_entity(
            {"PartitionKey": partition_key, "RowKey": row_key, "initials": initials},
            mode=UpdateMode.MERGE,
        )
        logging.info(f"Feedback initials updated: {partition_key}/{row_key} -> {initials}")
        return JSONResponse({"status": "updated", "initials": initials}, status_code=200)
    except Exception as e:
        logging.error(f"Failed to update feedback: {str(e)}")
        return JSONResponse({"error": "Failed to update feedback"}, status_code=500)


# ---------------------------------------------------------------------------
# Voice memo endpoint — save audio recordings for later transcription
# ---------------------------------------------------------------------------

@app.route(route="voice-memo", methods=["POST"])
async def voice_memo(req: Request) -> JSONResponse:
    """Save voice memo audio to blob storage for later transcription.

    Expects raw audio bytes in the request body.
    Query params: conversation_id, initials
    """
    # Auth check — returns JWT payload dict on success
    auth_result = auth_helper.require_auth(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    display_name = auth_result.get("display_name", auth_result.get("sub", ""))

    try:
        # Fix #6: Validate file size and content type before accepting
        content_type = req.headers.get("content-type", "")
        if content_type and not content_type.startswith("audio/"):
            return JSONResponse({"error": "Invalid content type, expected audio/*"}, status_code=400)

        audio_data = await req.body()
        conv_id = req.query_params.get("conversation_id", "")
        initials = req.query_params.get("initials", "") or display_name

        if not audio_data:
            return JSONResponse({"error": "No audio data in request body"}, status_code=400)

        # 10MB limit — voice memos should be short recordings
        if len(audio_data) > 10_000_000:
            return JSONResponse({"error": "File too large, 10MB maximum"}, status_code=413)

        now = datetime.now(timezone.utc)
        blob_name = (
            f"voice-memos/{now.strftime('%Y-%m-%d')}/"
            f"{now.strftime('%H%M%S')}_{initials}_{conv_id[:8]}.webm"
        )

        blob_service = get_blob_service_client()
        container = blob_service.get_container_client("knowledge-gaps")

        try:
            container.create_container()
        except Exception:
            pass  # Already exists

        container.get_blob_client(blob_name).upload_blob(audio_data, overwrite=True)

        logging.info(f"Voice memo saved: {blob_name} ({len(audio_data)} bytes)")
        return JSONResponse({"status": "saved", "blob": blob_name}, status_code=201)

    except Exception as e:
        logging.error(f"Failed to save voice memo: {str(e)}")
        return JSONResponse({"error": "Failed to save voice memo"}, status_code=500)


# ---------------------------------------------------------------------------
# Analytics endpoint — admin-only, reads conversation JSONL from blob storage
# ---------------------------------------------------------------------------

# In-memory cache for analytics (avoid re-reading blobs on tab switches)
_analytics_cache = None
_analytics_cache_time = 0
_ANALYTICS_CACHE_TTL = 300  # 5 minutes


@app.route(route="analytics/summary", methods=["GET"])
async def analytics_summary(req: Request) -> JSONResponse:
    """Return last 30 days of daily conversation aggregates for the analytics tab.

    Admin-only. Reads JSONL files from analytics/conversations/ blobs.
    Response includes daily turn counts, avg duration, unique conversations,
    and timing breakdowns (search, agent, graph).
    """
    global _analytics_cache, _analytics_cache_time

    # Admin check
    auth_result = auth_helper.require_admin(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    # Return cached result if fresh
    now = time.time()
    if _analytics_cache is not None and (now - _analytics_cache_time) < _ANALYTICS_CACHE_TTL:
        return JSONResponse(_analytics_cache, status_code=200)

    try:
        blob_service = get_blob_service_client()
        container = blob_service.get_container_client("analytics")

        today = datetime.now(timezone.utc)
        days_data = []

        # Read last 30 days of conversation JSONL
        for days_ago in range(30):
            day = today - timedelta(days=days_ago)
            blob_path = f"conversations/{day.year}/{day.month:02d}/{day.day:02d}.jsonl"
            date_str = day.strftime("%Y-%m-%d")

            day_record = {
                "date": date_str,
                "turn_count": 0,
                "avg_duration_sec": 0,
                "avg_agent_sec": 0,
                "avg_graph_sec": 0,
                "avg_citations_sec": 0,
                "unique_conversations": 0,
                "unique_users": 0,
            }

            try:
                blob_client = container.get_blob_client(blob_path)
                content = blob_client.download_blob().readall().decode("utf-8")
                lines = [l for l in content.strip().split("\n") if l.strip()]

                if not lines:
                    days_data.append(day_record)
                    continue

                total_duration = 0
                total_agent = 0
                total_graph = 0
                total_citations = 0
                total_input_tokens = 0
                total_output_tokens = 0
                total_graph_context_chars = 0
                total_agent_input_chars = 0
                conversation_ids = set()
                users = set()

                for line in lines:
                    try:
                        record = json.loads(line)
                        total_duration += record.get("duration_ms", 0)
                        total_agent += record.get("timing_agent_ms", 0)
                        total_graph += record.get("timing_graph_ms", 0)
                        total_citations += record.get("timing_citations_ms", 0)
                        total_input_tokens += record.get("input_tokens", 0)
                        total_output_tokens += record.get("output_tokens", 0)
                        total_graph_context_chars += record.get("graph_context_chars", 0)
                        total_agent_input_chars += record.get("agent_input_chars", 0)
                        if record.get("conversation_id"):
                            conversation_ids.add(record["conversation_id"])
                        if record.get("initials"):
                            users.add(record["initials"])
                    except json.JSONDecodeError:
                        continue

                count = len(lines)
                day_record["turn_count"] = count
                day_record["avg_duration_sec"] = round(total_duration / count / 1000, 1) if count else 0
                day_record["avg_agent_sec"] = round(total_agent / count / 1000, 1) if count else 0
                day_record["avg_graph_sec"] = round(total_graph / count / 1000, 1) if count else 0
                day_record["avg_citations_sec"] = round(total_citations / count / 1000, 1) if count else 0
                day_record["unique_conversations"] = len(conversation_ids)
                day_record["unique_users"] = len(users)
                day_record["avg_input_tokens"] = round(total_input_tokens / count) if count else 0
                day_record["avg_output_tokens"] = round(total_output_tokens / count) if count else 0
                day_record["avg_graph_context_chars"] = round(total_graph_context_chars / count) if count else 0
                day_record["avg_agent_input_chars"] = round(total_agent_input_chars / count) if count else 0

            except Exception:
                pass  # Blob doesn't exist for this day — zeros

            days_data.append(day_record)

        # Compute totals
        total_turns = sum(d["turn_count"] for d in days_data)
        total_convos = sum(d["unique_conversations"] for d in days_data)
        active_days = sum(1 for d in days_data if d["turn_count"] > 0)
        all_durations = [d["avg_duration_sec"] for d in days_data if d["turn_count"] > 0]
        avg_duration = round(sum(all_durations) / len(all_durations), 1) if all_durations else 0

        result = {
            "days": list(reversed(days_data)),  # oldest first for chart
            "totals": {
                "turn_count": total_turns,
                "avg_duration_sec": avg_duration,
                "unique_conversations": total_convos,
                "active_days": active_days,
            }
        }

        # Cache result
        _analytics_cache = result
        _analytics_cache_time = time.time()

        return JSONResponse(result, status_code=200)

    except Exception as e:
        logging.error(f"Analytics summary failed: {e}")
        return JSONResponse({"error": "Failed to generate analytics"}, status_code=500)


@app.route(route="analytics/by-user", methods=["GET"])
async def analytics_by_user(req: Request) -> JSONResponse:
    """Feedback counts grouped by initials + ISO week.

    Admin-only. Query param: ?weeks=4 (default 4, max 12).
    Returns rows like: {initials, week, total, thumbs_up, thumbs_down, flagged}
    Reads from the feedback table (not JSONL) since initials lives there.
    """
    auth_result = auth_helper.require_admin(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        weeks = int(req.query_params.get("weeks", "4"))
    except ValueError:
        weeks = 4
    weeks = max(1, min(weeks, 12))

    try:
        # Date range: last N weeks
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(weeks=weeks)
        start_str = start_date.strftime("%Y-%m-%d")

        table = get_table_client()
        # PartitionKey is the date — filter by range
        entities = list(table.query_entities(
            query_filter=f"PartitionKey ge '{start_str}'"
        ))

        # Group: {(initials, week): {total, thumbs_up, thumbs_down, flagged}}
        groups = {}
        for e in entities:
            initials = (e.get("initials") or "").strip() or "(none)"
            date_str = e.get("PartitionKey", "")
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
                week_key = d.strftime("%G-W%V")  # ISO week (Monday-based)
            except ValueError:
                continue

            key = (initials, week_key)
            if key not in groups:
                groups[key] = {"total": 0, "thumbs_up": 0, "thumbs_down": 0, "flagged": 0}
            groups[key]["total"] += 1
            rating = e.get("rating", "")
            if rating in ("thumbs_up", "thumbs_down", "flagged"):
                groups[key][rating] += 1

        # Flatten to list, sort by week desc then total desc
        rows = [
            {"initials": k[0], "week": k[1], **v}
            for k, v in groups.items()
        ]
        rows.sort(key=lambda r: (r["week"], r["total"]), reverse=True)

        return JSONResponse({"rows": rows, "weeks": weeks}, status_code=200)

    except Exception as e:
        logging.error(f"Analytics by-user failed: {e}")
        return JSONResponse({"error": "Failed to generate by-user analytics"}, status_code=500)


# ---------------------------------------------------------------------------
# Admin user management — single endpoint, dispatches by action query param
# Azure Functions can't reliably mix exact + parameterized routes on the same
# path prefix, so we use: /api/admin/users?action=list|create|delete|reset_password
# ---------------------------------------------------------------------------

@app.route(route="manage-users", methods=["GET", "POST", "PUT", "DELETE"])
async def admin_users(req: Request) -> JSONResponse:
    """Admin user management endpoint. Admin-only.

    Actions (inferred from HTTP method):
      GET              → list all users (no password hashes)
      POST             → create user  (body: {username, display_name, password, role})
      DELETE ?user=X   → delete user X (can't delete yourself)
      PUT ?user=X      → reset password (body: {password})
    """
    auth_result = auth_helper.require_admin(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    method = req.method.upper()

    # --- LIST ---
    if method == "GET":
        users = auth_helper.get_all_users()
        safe_users = [
            {"username": u["username"], "display_name": u["display_name"], "role": u["role"]}
            for u in users
        ]
        return JSONResponse(safe_users, status_code=200)

    # --- CREATE ---
    if method == "POST":
        try:
            body = await req.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        username = body.get("username", "").strip().lower()
        display_name = body.get("display_name", "").strip()
        password = body.get("password", "")
        role = body.get("role", "user").strip().lower()

        if not username or not password:
            return JSONResponse({"error": "username and password are required"}, status_code=400)
        if role not in ("user", "admin"):
            return JSONResponse({"error": "role must be 'user' or 'admin'"}, status_code=400)
        if not display_name:
            display_name = username.title()

        if auth_helper.get_user_info(username):
            return JSONResponse({"error": f"User '{username}' already exists"}, status_code=409)

        password_hash = auth_helper.generate_password_hash(password)

        try:
            from azure.data.tables import TableServiceClient
            endpoint = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"
            credential = DefaultAzureCredential()
            service = TableServiceClient(endpoint=endpoint, credential=credential)
            table = service.get_table_client("users")

            table.create_entity({
                "PartitionKey": "users",
                "RowKey": username,
                "display_name": display_name,
                "password_hash": password_hash,
                "role": role,
            })
            auth_helper.invalidate_user_cache()

            logging.info(f"User created: {username} ({display_name}, role={role})")
            return JSONResponse({"status": "created", "username": username}, status_code=201)

        except Exception as e:
            logging.error(f"Failed to create user: {e}")
            return JSONResponse({"error": "Failed to create user"}, status_code=500)

    # --- DELETE ---
    if method == "DELETE":
        username = req.query_params.get("user", "").strip()
        if not username:
            return JSONResponse({"error": "?user= query param required"}, status_code=400)

        if username == auth_result.get("sub", ""):
            return JSONResponse({"error": "Cannot delete your own account"}, status_code=400)

        try:
            from azure.data.tables import TableServiceClient
            endpoint = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"
            credential = DefaultAzureCredential()
            service = TableServiceClient(endpoint=endpoint, credential=credential)
            table = service.get_table_client("users")

            table.delete_entity(partition_key="users", row_key=username)
            auth_helper.invalidate_user_cache()

            logging.info(f"User deleted: {username}")
            return JSONResponse({"status": "deleted"}, status_code=200)

        except Exception as e:
            logging.error(f"Failed to delete user: {e}")
            return JSONResponse({"error": "Failed to delete user"}, status_code=500)

    # --- RESET PASSWORD ---
    if method == "PUT":
        username = req.query_params.get("user", "").strip()
        if not username:
            return JSONResponse({"error": "?user= query param required"}, status_code=400)

        try:
            body = await req.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        password = body.get("password", "")
        if not password:
            return JSONResponse({"error": "password is required"}, status_code=400)

        password_hash = auth_helper.generate_password_hash(password)

        try:
            from azure.data.tables import TableServiceClient, UpdateMode
            endpoint = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"
            credential = DefaultAzureCredential()
            service = TableServiceClient(endpoint=endpoint, credential=credential)
            table = service.get_table_client("users")

            table.upsert_entity(
                {"PartitionKey": "users", "RowKey": username, "password_hash": password_hash},
                mode=UpdateMode.MERGE,
            )
            auth_helper.invalidate_user_cache()

            logging.info(f"Password reset for user: {username}")
            return JSONResponse({"status": "password_updated"}, status_code=200)

        except Exception as e:
            logging.error(f"Failed to reset password: {e}")
            return JSONResponse({"error": "Failed to reset password"}, status_code=500)

    return JSONResponse({"error": "Method not allowed"}, status_code=405)


# ---------------------------------------------------------------------------
# Time entry endpoints — digital version of paper Operator Hour Report
# One entry = one machine's hours for one operator on one date
# ---------------------------------------------------------------------------

_HOUR_FIELDS = ["setup", "run", "reset", "repair", "wait_tool", "other"]


def _parse_hours(value):
    """Parse an hours input. Empty/None becomes 0.0. Returns float or raises ValueError."""
    if value in (None, "", 0):
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid hours value: {value!r}")
    if f < 0 or f > 24:
        raise ValueError(f"Hours out of range (0-24): {f}")
    return round(f, 2)


@app.route(route="time-entries", methods=["POST"])
async def submit_time_entry(req: Request) -> JSONResponse:
    """Save a time entry (one machine's hours for one operator/day).

    Body: {date: "YYYY-MM-DD", initials, machine, setup, run, reset, repair, wait_tool, other, notes?}
    """
    auth_result = auth_helper.require_auth(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    display_name = auth_result.get("display_name", auth_result.get("sub", ""))

    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    date_str = body.get("date", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return JSONResponse({"error": "Invalid date, use YYYY-MM-DD"}, status_code=400)

    initials = (body.get("initials") or "").strip()[:20]
    if not initials:
        return JSONResponse({"error": "initials is required"}, status_code=400)

    try:
        machine = int(body.get("machine", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "machine must be an integer"}, status_code=400)
    if machine < 1 or machine > 50:
        return JSONResponse({"error": "machine must be between 1 and 50"}, status_code=400)

    hours = {}
    try:
        for f in _HOUR_FIELDS:
            hours[f] = _parse_hours(body.get(f))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    notes = (body.get("notes") or "")[:500]
    now = datetime.now(timezone.utc)
    row_key = f"{initials}_{machine:02d}_{uuid.uuid4().hex[:8]}"

    entity = {
        "PartitionKey": date_str,
        "RowKey": row_key,
        "date": date_str,
        "initials": initials,
        "username": display_name,
        "machine": machine,
        **hours,
        "notes": notes,
        "created_at": now.isoformat(),
    }

    try:
        table = get_table_client("timeentries")
        table.create_entity(entity)
        logging.info(f"Time entry saved: {date_str} {initials} machine {machine}")
        return JSONResponse({"status": "saved", "id": row_key, **entity}, status_code=201)
    except Exception as e:
        logging.error(f"Failed to save time entry: {e}")
        return JSONResponse({"error": "Failed to save time entry"}, status_code=500)


@app.route(route="time-entries", methods=["GET"])
async def list_time_entries(req: Request) -> JSONResponse:
    """List time entries. Regular users see only their own; admins see all.

    Query params: ?date=YYYY-MM-DD (single day) or ?start=YYYY-MM-DD&end=YYYY-MM-DD (range)
                  ?initials=XX (admin-only filter)
    """
    auth_result = auth_helper.require_auth(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    display_name = auth_result.get("display_name", auth_result.get("sub", ""))
    is_admin = auth_result.get("role") == "admin"

    date_filter = req.query_params.get("date")
    start = req.query_params.get("start")
    end = req.query_params.get("end")
    initials_filter = req.query_params.get("initials")

    filters = []
    for val, name in [(date_filter, "date"), (start, "start"), (end, "end")]:
        if val and not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            return JSONResponse({"error": f"Invalid {name} format, use YYYY-MM-DD"}, status_code=400)

    if date_filter:
        filters.append(f"PartitionKey eq '{date_filter}'")
    else:
        if start:
            filters.append(f"PartitionKey ge '{start}'")
        if end:
            filters.append(f"PartitionKey le '{end}'")

    # Default: last 7 days if no filters
    if not filters:
        today = datetime.now(timezone.utc).date()
        week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        filters.append(f"PartitionKey ge '{week_ago}'")

    query_filter = " and ".join(filters)

    try:
        table = get_table_client("timeentries")
        entities = list(table.query_entities(query_filter=query_filter))

        # Non-admins only see their own entries
        if not is_admin:
            entities = [e for e in entities if e.get("username") == display_name]
        elif initials_filter:
            entities = [e for e in entities if e.get("initials") == initials_filter]

        results = [
            {
                "id": e.get("RowKey"),
                "date": e.get("date") or e.get("PartitionKey"),
                "initials": e.get("initials", ""),
                "username": e.get("username", ""),
                "machine": e.get("machine"),
                "setup": e.get("setup", 0),
                "run": e.get("run", 0),
                "reset": e.get("reset", 0),
                "repair": e.get("repair", 0),
                "wait_tool": e.get("wait_tool", 0),
                "other": e.get("other", 0),
                "notes": e.get("notes", ""),
                "created_at": e.get("created_at", ""),
            }
            for e in entities
        ]
        # Sort by date desc, then machine asc
        results.sort(key=lambda r: (r["date"], -int(r.get("machine") or 0)), reverse=True)
        return JSONResponse(results, status_code=200)
    except Exception as e:
        logging.error(f"Failed to list time entries: {e}")
        return JSONResponse({"error": "Failed to list time entries"}, status_code=500)


@app.route(route="time-entries/{partition_key}/{row_key}", methods=["DELETE"])
async def delete_time_entry(req: Request) -> JSONResponse:
    """Delete a time entry. Users can delete their own; admins can delete any."""
    auth_result = auth_helper.require_auth(req)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    display_name = auth_result.get("display_name", auth_result.get("sub", ""))
    is_admin = auth_result.get("role") == "admin"

    partition_key = req.path_params.get("partition_key", "")
    row_key = req.path_params.get("row_key", "")

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", partition_key):
        return JSONResponse({"error": "Invalid partition_key"}, status_code=400)
    if not row_key or len(row_key) > 200:
        return JSONResponse({"error": "Invalid row_key"}, status_code=400)

    try:
        table = get_table_client("timeentries")
        # Check ownership before deleting (unless admin)
        if not is_admin:
            entity = table.get_entity(partition_key=partition_key, row_key=row_key)
            if entity.get("username") != display_name:
                return JSONResponse({"error": "Forbidden"}, status_code=403)
        table.delete_entity(partition_key=partition_key, row_key=row_key)
        return JSONResponse({"status": "deleted"}, status_code=200)
    except Exception as e:
        logging.error(f"Failed to delete time entry: {e}")
        return JSONResponse({"error": "Failed to delete time entry"}, status_code=500)
