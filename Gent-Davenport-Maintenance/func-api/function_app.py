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
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azurefunctions.extensions.http.fastapi import Request, StreamingResponse, JSONResponse

# Storage config for video links
STORAGE_ACCOUNT = "stj6lw7vswhnnhw"
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

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"

# Agent routing by reasoning level
AGENTS = {
    "fast": "davenport-fast",           # Minimal reasoning ~40s (MCP)
    "balanced": "davenport-balanced",   # Low reasoning ~55s (MCP)
    "thorough": "davenport-assistant",  # Medium reasoning ~2 min (MCP)
    "direct": "davenport-direct-v1",    # Unified index, direct search ~30s — no mode selector in new SWA
}
DEFAULT_AGENT = "davenport-direct-v1"

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
_symptom_cache = None      # V3 Graph RAG — cached symptom list for classification


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
    """Get or create Azure Table Storage client (cached)."""
    global _table_client
    if _table_client is None:
        from azure.data.tables import TableServiceClient
        credential = DefaultAzureCredential()
        service = TableServiceClient(
            endpoint=TABLE_STORAGE_ENDPOINT,
            credential=credential
        )
        # Create table if it doesn't exist (idempotent)
        service.create_table_if_not_exists(table_name)
        _table_client = service.get_table_client(table_name)
    return _table_client


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


def classify_symptom(message, openai_client):
    """Classify user question into a known graph symptom. Returns (symptom_id, symptom_name) or (None, None).

    Uses gpt-5-mini to match against the symptom list from Cosmos DB.
    Cached symptom list is loaded once and refreshed on function app restart.
    """
    global _symptom_cache

    gremlin = get_gremlin_client()
    if not gremlin:
        return None, None

    # Load symptom list once (refreshed on function app restart)
    if _symptom_cache is None:
        import graph_helper
        _symptom_cache = graph_helper.query_all_symptoms(gremlin)
        logging.info(f"Loaded {len(_symptom_cache)} symptoms for classification")

    if not _symptom_cache:
        return None, None

    # Build the symptom list for the LLM prompt
    symptom_list = "\n".join(
        f"- {s['id']}: {s['name']} (aliases: {', '.join(s.get('aliases', []))})"
        for s in _symptom_cache
    )

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": (
                    "You classify Davenport Model B screw machine questions into known symptom categories.\n\n"
                    f"Known symptoms:\n{symptom_list}\n\n"
                    "Return JSON: {\"symptom_id\": \"the_id\"} if the question matches a symptom, "
                    "or {\"symptom_id\": null} if it doesn't (e.g., general info questions, definitions, part numbers)."
                )},
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        sid = result.get("symptom_id")
        if sid:
            # Look up the display name
            name = next((s["name"] for s in _symptom_cache if s["id"] == sid), sid)
            logging.info(f"Symptom classified: {sid} ({name})")
            return sid, name
    except Exception as e:
        logging.warning(f"classify_symptom failed: {e}")

    return None, None


def get_graph_context_for_message(message, openai_client):
    """V3 Graph RAG: classify symptom and build graph context for the agent.

    Returns (graph_context_string, symptom_id) — both empty/None if graph is unavailable
    or the question doesn't match a known symptom. Never raises exceptions.
    """
    try:
        symptom_id, symptom_name = classify_symptom(message, openai_client)
        if not symptom_id:
            return "", None

        import graph_helper
        gremlin = get_gremlin_client()
        if not gremlin:
            return "", None

        graph_context = graph_helper.get_graph_context(gremlin, symptom_id)
        if graph_context:
            logging.info(f"Graph context matched: {symptom_id} ({symptom_name}), {len(graph_context)} chars")
        return graph_context, symptom_id

    except Exception as e:
        logging.warning(f"Graph context failed (proceeding without): {e}")
        return "", None


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


def transform_transcript_urls_to_youtube(text):
    """Replace transcript URLs in response text with YouTube URLs.

    Changes links from video-training/*.md to YouTube URLs with timestamps.
    Extracts timestamps from surrounding text (e.g., "02:28-02:38" or "04:14").
    """
    # Pattern: [link text](https://storage.blob.../video-training/Name.md) optional_timestamp
    # Use .+? (non-greedy) to handle filenames with parentheses like "(part 1)"
    pattern = rf'\[([^\]]+)\]\((https://{STORAGE_ACCOUNT}\.blob\.core\.windows\.net/{TRANSCRIPT_CONTAINER}/(.+?)\.md)\)(\s*(\d{{1,2}}:\d{{2}}(?:-\d{{1,2}}:\d{{2}})?))?'

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
            time_part = timestamp_str.split('-')[0]
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
        for url in re.findall(r'https://\w+\.blob\.core\.windows\.net/[^\s)"\]]+', output_text):
            filename = unquote(url.split("/")[-1])
            name = filename.rsplit(".", 1)[0]
            if name and name.lower() not in url_lookup:
                url_lookup[name.lower()] = (name, url)

        logging.info(f"extract_blob_urls: found {len(url_lookup)} blob URLs: {list(url_lookup.keys())}")
    except Exception as e:
        logging.warning(f"extract_blob_urls failed: {e}")
    return url_lookup


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

        # Strip any remaining bare 【N:M†source】 markers (e.g. after inline citations)
        result = re.sub(r'【\d+:\d+†\w+】', '', result)
        return result

    except Exception as e:
        logging.warning(f"process_citations failed: {e}")
        return re.sub(r'【\d+:\d+†\w+】', '', text)


def fallback_link_citations(text, response):
    """Second pass: link any remaining (Name) citations that process_citations missed.

    When the agent writes (Maintenance Manual) without Foundry's 【markers】,
    process_citations can't help. This function uses the real blob URLs extracted
    from search result snippets (via [source: URL] prefixes) to fuzzy-match
    unlinked (Name) patterns.

    Must run AFTER process_citations and clean_search_service_urls.
    """
    try:
        # Use blob URLs from search results — NOT annotation URLs (which point to search service)
        url_lookup = extract_blob_urls_from_response(response)

        if not url_lookup:
            return text  # no blob URLs found in response

        # Known category tags that should never be linked
        category_tags = {"Tooling", "Machine", "Feeds & Speeds", "Work Holding", "Stock/Material"}

        def replace_unlinked(match):
            name = match.group(1).strip()
            # Skip category tags and very short names (likely not citations)
            if name in category_tags or len(name) < 8:
                return match.group(0)
            name_lower = name.lower()
            # Try substring containment match against blob URL display names
            for key, (display, url) in url_lookup.items():
                if key and (name_lower in key or key in name_lower):
                    return f"([{display}]({url}))"
            return match.group(0)  # no match found, leave as-is

        # Match (Name) that isn't part of a markdown link — negative lookbehind for ]
        result = re.sub(r'(?<!\])\(([^()]+)\)(?![\[(])', replace_unlinked, text)
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
# Non-streaming chat endpoint — fallback if streaming is unavailable
# ---------------------------------------------------------------------------

@app.route(route="chat", methods=["POST"])
async def chat(req: Request) -> JSONResponse:
    """Handle chat requests (non-streaming fallback)."""
    logging.info('Chat function processing request')

    try:
        req_body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)

    message = req_body.get('message')
    conversation_id = req_body.get('conversation_id')
    reasoning_level = req_body.get('reasoning_level', 'thorough')
    initials = req_body.get('initials', '')

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

        # V3 Graph RAG: classify symptom and prepend diagnostic context
        t_graph = time.time()
        graph_context, symptom_id = get_graph_context_for_message(message, openai_client)
        agent_input = f"{graph_context}\n\nUSER QUESTION:\n{message}" if graph_context else message
        timings["graph_context"] = round((time.time() - t_graph) * 1000)

        t2 = time.time()
        response = openai_client.responses.create(
            conversation=conversation_id,
            tool_choice="required",
            input=agent_input,
            extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
        )
        timings["agent_response"] = round((time.time() - t2) * 1000)
        timings["total"] = round((time.time() - t0) * 1000)

        trace = extract_reasoning_trace(response)
        trace["timings"] = timings

        # Citation pipeline: markers → strip search URLs → link remaining (Name) → YouTube
        response_text = process_citations(response, response.output_text)
        response_text = clean_search_service_urls(response_text)
        response_text = fallback_link_citations(response_text, response)
        response_text = transform_transcript_urls_to_youtube(response_text)
        logging.info(f"Timings: {timings}")

        # Extract structured metadata from the processed response
        turn_id = generate_turn_id()
        turn_number = req_body.get("turn_number", 1)
        sources = extract_sources_cited(response_text)
        categories = extract_categories_tagged(response_text)

        # Log every interaction to the data lake (fire-and-forget — never blocks response)
        log_to_lake("conversations", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "turn_number": turn_number,
            "is_first_turn": turn_number == 1,
            "initials": initials,
            "message": message[:4000],
            "response": response_text[:4000],
            "agent": agent_name,
            "reasoning_level": reasoning_level,
            "duration_ms": timings["total"],
            "sources_cited": sources,
            "categories_tagged": categories,
            "source_count": len(sources),
            "category_count": len(categories),
            "graph_symptom_matched": symptom_id or "",
            "graph_context_provided": bool(graph_context),
        })

        # V3: Track graph node usage (fire-and-forget)
        if symptom_id:
            try:
                import graph_helper
                gremlin = get_gremlin_client()
                if gremlin:
                    graph_helper.increment_hit_count(gremlin, [symptom_id])
            except Exception:
                pass

        return JSONResponse(
            {"response": response_text, "conversation_id": conversation_id, "turn_id": turn_id, "trace": trace},
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error processing chat: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


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
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON in request body"}, status_code=400)

    message = body.get("message")
    conversation_id = body.get("conversation_id")
    reasoning_level = body.get("reasoning_level", "thorough")
    initials = body.get("initials", "")
    turn_number = body.get("turn_number", 1)

    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    agent_name = AGENTS.get(reasoning_level, DEFAULT_AGENT)
    logging.info(f"Streaming: agent={agent_name}")

    _, openai_client = get_clients()

    if not conversation_id:
        conversation = openai_client.conversations.create()
        conversation_id = conversation.id

    # V3 Graph RAG: classify symptom and prepend diagnostic context (before streaming starts)
    graph_context, symptom_id = get_graph_context_for_message(message, openai_client)
    agent_input = f"{graph_context}\n\nUSER QUESTION:\n{message}" if graph_context else message

    async def event_generator():
        # Send conversation_id immediately so the frontend can persist it
        yield f"data: {json.dumps({'type': 'session', 'conversation_id': conversation_id})}\n\n"
        status_msg = "Analyzing diagnostic knowledge..." if graph_context else "Searching knowledge base..."
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
                    # Citation pipeline: markers → strip search URLs → link remaining (Name) → YouTube
                    full_text = process_citations(event.response, full_text)
                    full_text = clean_search_service_urls(full_text)
                    full_text = fallback_link_citations(full_text, event.response)
                    full_text = transform_transcript_urls_to_youtube(full_text)
                    elapsed_ms = round((time.time() - t_start) * 1000)
                    trace = extract_reasoning_trace(event.response)
                    trace["timings"] = {"total": elapsed_ms}
                    turn_id = generate_turn_id()
                    yield f"data: {json.dumps({'type': 'done', 'full_text': full_text, 'turn_id': turn_id, 'trace': trace})}\n\n"
                    completed = True

                    # Extract structured metadata for analytics
                    sources = extract_sources_cited(full_text)
                    categories = extract_categories_tagged(full_text)

                    # Log to data lake after yielding (message/agent_name/initials captured from outer scope)
                    log_to_lake("conversations", {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "turn_number": turn_number,
                        "is_first_turn": turn_number == 1,
                        "initials": initials,
                        "message": message[:4000],
                        "response": full_text[:4000],
                        "agent": agent_name,
                        "reasoning_level": reasoning_level,
                        "duration_ms": elapsed_ms,
                        "sources_cited": sources,
                        "categories_tagged": categories,
                        "source_count": len(sources),
                        "category_count": len(categories),
                        "graph_symptom_matched": symptom_id or "",
                        "graph_context_provided": bool(graph_context),
                    })

                    # V3: Track graph node usage (fire-and-forget)
                    if symptom_id:
                        try:
                            import graph_helper
                            gremlin = get_gremlin_client()
                            if gremlin:
                                graph_helper.increment_hit_count(gremlin, [symptom_id])
                        except Exception:
                            pass

            # Safety: if stream ended without a completed event, send what we have
            if full_text and not completed:
                full_text = re.sub(r'【\d+:\d+†\w+】', '', full_text)  # strip markers, no response object available
                full_text = transform_transcript_urls_to_youtube(full_text)
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
    """Save user feedback (thumbs up/down/flag) for a response."""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    now = datetime.now(timezone.utc)
    entity = {
        "PartitionKey": now.strftime("%Y-%m-%d"),
        "RowKey": f"{now.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "conversation_id": body.get("conversation_id", ""),
        "turn_id": body.get("turn_id", ""),
        "turn_number": body.get("turn_number", 0),
        "message": body.get("message", "")[:32000],
        "response": body.get("response", "")[:32000],
        "rating": body.get("rating", ""),
        "notes": body.get("notes", "")[:4000],
        "initials": body.get("initials", ""),
        "reasoning_level": body.get("reasoning_level", ""),
    }

    try:
        table = get_table_client()
        table.create_entity(entity)
        logging.info(f"Feedback saved: {entity['rating']} from {entity['initials'] or 'anonymous'}")

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
            "initials": entity["initials"],
            "notes": entity["notes"],
            "reasoning_level": entity["reasoning_level"],
        })

        return JSONResponse({"status": "saved"}, status_code=201)
    except Exception as e:
        logging.error(f"Failed to save feedback: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.route(route="feedback", methods=["GET"])
async def get_feedback(req: Request) -> JSONResponse:
    """Retrieve feedback entries for admin review.

    Optional query params: ?rating=flagged&date=2026-02-25
    """
    rating_filter = req.query_params.get("rating")
    date_filter = req.query_params.get("date")

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
                "reasoning_level": entity.get("reasoning_level"),
            }
            for entity in entities
        ]
        return JSONResponse(results, status_code=200)
    except Exception as e:
        logging.error(f"Failed to get feedback: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Voice memo endpoint — save audio recordings for later transcription
# ---------------------------------------------------------------------------

@app.route(route="voice-memo", methods=["POST"])
async def voice_memo(req: Request) -> JSONResponse:
    """Save voice memo audio to blob storage for later transcription.

    Expects raw audio bytes in the request body.
    Query params: conversation_id, initials
    """
    try:
        audio_data = await req.body()
        conv_id = req.query_params.get("conversation_id", "")
        initials = req.query_params.get("initials", "")

        if not audio_data:
            return JSONResponse({"error": "No audio data in request body"}, status_code=400)

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
        return JSONResponse({"error": str(e)}, status_code=500)
