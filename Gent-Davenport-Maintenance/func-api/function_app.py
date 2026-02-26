"""
Azure Function: Chat API endpoint for Davenport Assistant.
Connects to the agentic retrieval agent via Azure AI Projects SDK.
Includes streaming, feedback, and voice memo endpoints for production use.
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
    "fast": "davenport-fast",        # Minimal reasoning ~10s
    "balanced": "davenport-balanced", # Low reasoning ~20s
    "thorough": "davenport-assistant" # Medium reasoning ~45s
}
DEFAULT_AGENT = "davenport-assistant"

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
    # We need to capture the full markdown link plus any timestamp after it
    # Use .+? (non-greedy) instead of [^)]+ to handle filenames with parentheses like "(part 1)"
    pattern = rf'\[([^\]]+)\]\((https://{STORAGE_ACCOUNT}\.blob\.core\.windows\.net/{TRANSCRIPT_CONTAINER}/(.+?)\.md)\)(\s*(\d{{1,2}}:\d{{2}}(?:-\d{{1,2}}:\d{{2}})?))?'

    def replace_with_youtube(match):
        link_text = match.group(1)
        video_name_encoded = match.group(3)
        timestamp_str = match.group(5)  # e.g., "02:28" or "02:28-02:38"

        # URL decode the video name (replace %20 with space, etc.)
        from urllib.parse import unquote
        video_name = unquote(video_name_encoded)

        # Look up YouTube video ID
        youtube_id = YOUTUBE_VIDEO_MAP.get(video_name)
        if not youtube_id:
            # No YouTube mapping, keep original link
            return match.group(0)

        # Build YouTube URL
        youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"

        # Add timestamp if present (use first timestamp in range)
        if timestamp_str:
            # Parse timestamp like "02:28" or "02:28-02:38" (take first part)
            time_part = timestamp_str.split('-')[0]
            parts = time_part.split(':')
            if len(parts) == 2:
                minutes, seconds = int(parts[0]), int(parts[1])
                total_seconds = minutes * 60 + seconds
                youtube_url += f"&t={total_seconds}"

        # Return new markdown link (keep original text, add timestamp to display)
        display_text = link_text
        if timestamp_str:
            display_text = f"{link_text} {timestamp_str}"
        return f"[{display_text}]({youtube_url})"

    result = re.sub(pattern, replace_with_youtube, text)

    # Also handle plain URLs without markdown formatting
    # Use .+? (non-greedy) to handle filenames with parentheses
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

        # Get agent info
        if "agent" in response_dict:
            agent = response_dict["agent"]
            trace["agent"] = f"{agent.get('name', 'unknown')} v{agent.get('version', '?')}"

        # Get token usage
        if "usage" in response_dict:
            usage = response_dict["usage"]
            trace["tokens"] = {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "total": usage.get("total_tokens", 0)
            }

        # Extract MCP call details (query decomposition)
        for item in response_dict.get("output", []):
            if item.get("type") == "mcp_call":
                args_str = item.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                    intents = args.get("request", {}).get("knowledgeAgentIntents", [])
                    trace["query_intents"] = intents
                except (json.JSONDecodeError, KeyError):
                    pass  # MCP args may not always be valid JSON

                # Count sources from output
                output_str = item.get("output", "")
                if "Retrieved" in output_str:
                    # Parse "Retrieved X documents"
                    match = re.search(r"Retrieved (\d+) documents", output_str)
                    if match:
                        trace["sources_found"] = int(match.group(1))

    except Exception as e:
        logging.warning(f"Failed to extract trace: {e}")

    return trace


@app.route(route="chat", methods=["POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    """Handle chat requests."""
    logging.info('Chat function processing request')

    # Parse request body
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON in request body"}),
            mimetype="application/json",
            status_code=400
        )

    message = req_body.get('message')
    conversation_id = req_body.get('conversation_id')
    reasoning_level = req_body.get('reasoning_level', 'thorough')  # Default to thorough for accuracy

    if not message:
        return func.HttpResponse(
            json.dumps({"error": "Message is required"}),
            mimetype="application/json",
            status_code=400
        )

    # Select agent based on reasoning level
    agent_name = AGENTS.get(reasoning_level, DEFAULT_AGENT)
    logging.info(f"Using agent: {agent_name} (reasoning_level: {reasoning_level})")

    try:
        # Track timing for each phase
        timings = {}

        t0 = time.time()
        _, openai_client = get_clients()
        timings["client_init"] = round((time.time() - t0) * 1000)  # ms

        # Create new conversation if not provided
        t1 = time.time()
        if not conversation_id:
            conversation = openai_client.conversations.create()
            conversation_id = conversation.id
        timings["conversation_create"] = round((time.time() - t1) * 1000)

        # Send message to selected agent (main bottleneck)
        t2 = time.time()
        response = openai_client.responses.create(
            conversation=conversation_id,
            tool_choice="required",
            input=message,
            extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
        )
        timings["agent_response"] = round((time.time() - t2) * 1000)
        timings["total"] = round((time.time() - t0) * 1000)

        # Extract reasoning trace from response
        trace = extract_reasoning_trace(response)
        trace["timings"] = timings

        # Transform transcript URLs to YouTube URLs in response text
        response_text = transform_transcript_urls_to_youtube(response.output_text)

        logging.info(f"Timings: {timings}")

        return func.HttpResponse(
            json.dumps({
                "response": response_text,
                "conversation_id": conversation_id,
                "trace": trace
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error processing chat: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )


# ---------------------------------------------------------------------------
# Streaming chat endpoint — tokens appear as they're generated
# ---------------------------------------------------------------------------

@app.route(route="chat/stream", methods=["POST"])
def chat_stream(req: func.HttpRequest) -> func.HttpResponse:
    """Streaming chat endpoint using Server-Sent Events.

    Sends tokens as they arrive from the agent, so the user sees
    the response building progressively instead of waiting 30-45s.

    Uses azurefunctions-extensions-http-fastapi for streaming support.
    Falls back gracefully to an error if the extension is unavailable.
    """
    try:
        from azurefunctions.extensions.http.fastapi import StreamingResponse
    except ImportError:
        return func.HttpResponse(
            json.dumps({"error": "Streaming not available — azurefunctions-extensions-http-fastapi not installed"}),
            mimetype="application/json", status_code=501
        )

    try:
        body = req.get_json()
    except ValueError:
        body = {}
    message = body.get("message")
    conversation_id = body.get("conversation_id")
    reasoning_level = body.get("reasoning_level", "thorough")

    if not message:
        return func.HttpResponse(
            json.dumps({"error": "Message is required"}),
            mimetype="application/json", status_code=400
        )

    agent_name = AGENTS.get(reasoning_level, DEFAULT_AGENT)
    logging.info(f"[stream] Using agent: {agent_name} (reasoning_level: {reasoning_level})")

    def event_generator():
        """Sync generator that yields SSE events from the agent stream."""
        try:
            t0 = time.time()
            _, openai_client = get_clients()

            # Create conversation if needed
            if not conversation_id:
                conversation = openai_client.conversations.create()
                conv_id = conversation.id
            else:
                conv_id = conversation_id

            # Send conversation_id immediately so frontend can track it
            yield f"data: {json.dumps({'type': 'session', 'conversation_id': conv_id})}\n\n"

            # Notify user that search is starting
            yield f"data: {json.dumps({'type': 'status', 'text': 'Searching knowledge base...'})}\n\n"

            # Stream the agent response — tokens arrive as they're generated
            stream = openai_client.responses.create(
                conversation=conv_id,
                tool_choice="required",
                input=message,
                stream=True,
                extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
            )

            full_text = ""
            first_text = True
            trace = {
                "agent": agent_name,
                "query_intents": [],
                "sources_found": 0,
                "tokens": {}
            }

            for event in stream:
                event_type = getattr(event, "type", None)

                # Text delta — the main content tokens
                if event_type == "response.output_text.delta":
                    delta = event.delta
                    full_text += delta
                    if first_text:
                        # Notify frontend that text is starting (search phase done)
                        yield f"data: {json.dumps({'type': 'status', 'text': 'Generating answer...'})}\n\n"
                        first_text = False
                    yield f"data: {json.dumps({'type': 'delta', 'text': delta})}\n\n"

                # MCP call events — extract query decomposition for trace
                elif event_type == "response.mcp_call.arguments.delta":
                    pass  # MCP args arrive in chunks, we'll get full args on completion
                elif event_type == "response.mcp_call.completed":
                    # Try to extract trace info from completed MCP call
                    try:
                        if hasattr(event, "arguments"):
                            args = json.loads(event.arguments)
                            intents = args.get("request", {}).get("knowledgeAgentIntents", [])
                            if intents:
                                trace["query_intents"] = intents
                    except (json.JSONDecodeError, AttributeError):
                        pass

                # Response completed — send final transformed text + trace
                elif event_type == "response.completed":
                    elapsed = round((time.time() - t0) * 1000)
                    trace["timings"] = {"total": elapsed}

                    # Extract token usage from the completed response
                    try:
                        resp = event.response
                        if hasattr(resp, "usage") and resp.usage:
                            trace["tokens"] = {
                                "input": getattr(resp.usage, "input_tokens", 0),
                                "output": getattr(resp.usage, "output_tokens", 0),
                                "total": getattr(resp.usage, "total_tokens", 0)
                            }
                    except Exception:
                        pass

                    # Apply YouTube URL transformation to the full assembled text
                    final_text = transform_transcript_urls_to_youtube(full_text)
                    yield f"data: {json.dumps({'type': 'done', 'full_text': final_text, 'trace': trace})}\n\n"

            logging.info(f"[stream] Completed in {round((time.time() - t0) * 1000)}ms")

        except Exception as e:
            logging.error(f"[stream] Error: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if behind proxy
        }
    )


# ---------------------------------------------------------------------------
# Feedback endpoints — thumbs up/down, flag, and notes
# ---------------------------------------------------------------------------

@app.route(route="feedback", methods=["POST"])
def submit_feedback(req: func.HttpRequest) -> func.HttpResponse:
    """Save user feedback (thumbs up/down/flag) for a response."""
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            mimetype="application/json", status_code=400
        )

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
        return func.HttpResponse(
            json.dumps({"status": "saved"}),
            mimetype="application/json", status_code=201
        )
    except Exception as e:
        logging.error(f"Failed to save feedback: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json", status_code=500
        )


@app.route(route="feedback", methods=["GET"])
def get_feedback(req: func.HttpRequest) -> func.HttpResponse:
    """Retrieve feedback entries for admin review.

    Optional query params: ?rating=flagged&date=2026-02-25
    """
    rating_filter = req.params.get("rating")
    date_filter = req.params.get("date")

    # Build OData filter
    filters = []
    if date_filter:
        filters.append(f"PartitionKey eq '{date_filter}'")
    if rating_filter:
        filters.append(f"rating eq '{rating_filter}'")
    query_filter = " and ".join(filters) if filters else None

    try:
        table = get_table_client()
        entities = list(table.query_entities(query_filter=query_filter))

        # Convert to JSON-serializable format
        results = []
        for entity in entities:
            results.append({
                "date": entity.get("PartitionKey"),
                "id": entity.get("RowKey"),
                "conversation_id": entity.get("conversation_id"),
                "message": entity.get("message"),
                "response": entity.get("response"),
                "rating": entity.get("rating"),
                "notes": entity.get("notes"),
                "initials": entity.get("initials"),
                "reasoning_level": entity.get("reasoning_level"),
            })

        return func.HttpResponse(
            json.dumps(results, default=str),
            mimetype="application/json", status_code=200
        )
    except Exception as e:
        logging.error(f"Failed to get feedback: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json", status_code=500
        )


# ---------------------------------------------------------------------------
# Voice memo endpoint — save audio recordings for later transcription
# ---------------------------------------------------------------------------

@app.route(route="voice-memo", methods=["POST"])
def voice_memo(req: func.HttpRequest) -> func.HttpResponse:
    """Save voice memo audio to blob storage for later transcription.

    Technicians can record a voice note when flagging an issue.
    Audio is stored in the knowledge-gaps container for batch processing.

    Expects raw audio bytes in the request body.
    Query params: conversation_id, initials
    """
    try:
        audio_data = req.get_body()
        conv_id = req.params.get("conversation_id", "")
        initials = req.params.get("initials", "")

        if not audio_data:
            return func.HttpResponse(
                json.dumps({"error": "No audio data in request body"}),
                mimetype="application/json", status_code=400
            )

        now = datetime.now(timezone.utc)
        blob_name = (
            f"voice-memos/{now.strftime('%Y-%m-%d')}/"
            f"{now.strftime('%H%M%S')}_{initials}_{conv_id[:8]}.webm"
        )

        blob_service = get_blob_service_client()
        container = blob_service.get_container_client("knowledge-gaps")

        # Create container if it doesn't exist (idempotent)
        try:
            container.create_container()
        except Exception:
            pass  # Already exists

        container.get_blob_client(blob_name).upload_blob(audio_data, overwrite=True)

        logging.info(f"Voice memo saved: {blob_name} ({len(audio_data)} bytes)")
        return func.HttpResponse(
            json.dumps({"status": "saved", "blob": blob_name}),
            mimetype="application/json", status_code=201
        )

    except Exception as e:
        logging.error(f"Failed to save voice memo: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json", status_code=500
        )
