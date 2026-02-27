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

        t2 = time.time()
        response = openai_client.responses.create(
            conversation=conversation_id,
            tool_choice="required",
            input=message,
            extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
        )
        timings["agent_response"] = round((time.time() - t2) * 1000)
        timings["total"] = round((time.time() - t0) * 1000)

        trace = extract_reasoning_trace(response)
        trace["timings"] = timings

        response_text = transform_transcript_urls_to_youtube(response.output_text)
        logging.info(f"Timings: {timings}")

        return JSONResponse(
            {"response": response_text, "conversation_id": conversation_id, "trace": trace},
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

    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)

    agent_name = AGENTS.get(reasoning_level, DEFAULT_AGENT)
    logging.info(f"Streaming: agent={agent_name}")

    _, openai_client = get_clients()

    if not conversation_id:
        conversation = openai_client.conversations.create()
        conversation_id = conversation.id

    async def event_generator():
        # Send conversation_id immediately so the frontend can persist it
        yield f"data: {json.dumps({'type': 'session', 'conversation_id': conversation_id})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'text': 'Searching knowledge base...'})}\n\n"

        try:
            t_start = time.time()
            response = openai_client.responses.create(
                conversation=conversation_id,
                tool_choice="required",
                input=message,
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
                    full_text = transform_transcript_urls_to_youtube(full_text)
                    trace = extract_reasoning_trace(event.response)
                    trace["timings"] = {"total": round((time.time() - t_start) * 1000)}
                    yield f"data: {json.dumps({'type': 'done', 'full_text': full_text, 'trace': trace})}\n\n"
                    completed = True

            # Safety: if stream ended without a completed event, send what we have
            if full_text and not completed:
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
