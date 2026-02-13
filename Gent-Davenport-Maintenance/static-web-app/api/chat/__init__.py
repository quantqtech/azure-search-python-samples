"""
Azure Function: Chat API endpoint for Davenport Assistant.
Connects to the agentic retrieval agent via Azure AI Projects SDK.
"""

import json
import logging
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
AGENT_NAME = "davenport-assistant"

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


def main(req: func.HttpRequest) -> func.HttpResponse:
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

    if not message:
        return func.HttpResponse(
            json.dumps({"error": "Message is required"}),
            mimetype="application/json",
            status_code=400
        )

    try:
        _, openai_client = get_clients()

        # Create new conversation if not provided
        if not conversation_id:
            conversation = openai_client.conversations.create()
            conversation_id = conversation.id

        # Send message to agent
        response = openai_client.responses.create(
            conversation=conversation_id,
            tool_choice="required",
            input=message,
            extra_body={"agent": {"name": AGENT_NAME, "type": "agent_reference"}},
        )

        return func.HttpResponse(
            json.dumps({
                "response": response.output_text,
                "conversation_id": conversation_id
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
