"""
Azure Function: Chat API endpoint for Davenport Assistant.
Connects to the agentic retrieval agent via Azure AI Projects SDK.
"""

import json
import logging
import time
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

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

# Cache clients for reuse across invocations
_project_client = None
_openai_client = None


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
                except:
                    pass

                # Count sources from output
                output_str = item.get("output", "")
                if "Retrieved" in output_str:
                    # Parse "Retrieved X documents"
                    import re
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
    reasoning_level = req_body.get('reasoning_level', 'thorough')  # Default to thorough

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

        logging.info(f"Timings: {timings}")

        return func.HttpResponse(
            json.dumps({
                "response": response.output_text,
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
