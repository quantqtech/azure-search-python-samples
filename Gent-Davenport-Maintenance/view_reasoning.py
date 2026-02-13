"""
View agentic reasoning by inspecting agent response details.
Shows MCP tool calls and knowledge base retrieval activity.
"""

import json
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
AGENT_NAME = "davenport-assistant"


def query_with_details(question: str):
    """Query the agent and show detailed reasoning information."""

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
    openai_client = project_client.get_openai_client()

    print(f"Question: {question}")
    print("=" * 70)
    print()

    # Create conversation
    conversation = openai_client.conversations.create()
    print(f"Conversation ID: {conversation.id}")

    # Send message with tool_choice=required to force KB retrieval
    response = openai_client.responses.create(
        conversation=conversation.id,
        tool_choice="required",
        input=question,
        extra_body={"agent": {"name": AGENT_NAME, "type": "agent_reference"}},
    )

    # Convert to dict to inspect all fields
    response_dict = response.to_dict()

    print()
    print("AGENT ACTIVITY:")
    print("-" * 50)

    # Show tool calls (this is where MCP/KB queries show up)
    if "output" in response_dict:
        output_items = response_dict.get("output", [])
        for item in output_items:
            item_type = item.get("type", "unknown")

            if item_type == "mcp_call":
                print(f"\n[MCP Tool Call]")
                print(f"  Server: {item.get('server_label', 'N/A')}")
                print(f"  Tool: {item.get('name', 'N/A')}")

                # Show the query sent to knowledge base
                arguments = item.get("arguments", {})
                if arguments:
                    print(f"  Query sent to Knowledge Base:")
                    print(f"    {json.dumps(arguments, indent=4)[:500]}")

            elif item_type == "mcp_call_output":
                print(f"\n[Knowledge Base Response]")
                output = item.get("output", "")
                # Parse if JSON
                try:
                    kb_response = json.loads(output) if isinstance(output, str) else output
                    if isinstance(kb_response, dict):
                        # Show reasoning activities if present
                        if "activities" in kb_response:
                            print("  AGENTIC REASONING STEPS:")
                            for i, act in enumerate(kb_response["activities"], 1):
                                print(f"    {i}. {act.get('kind', 'unknown')}")
                        # Show result count
                        if "results" in kb_response:
                            print(f"  Results returned: {len(kb_response['results'])}")
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Couldn't parse as structured response — show raw output
                    print(f"  Output (truncated): {str(output)[:300]}...")

            elif item_type == "message":
                # Final message
                pass

    # Show usage stats (shows total tokens which indicates LLM reasoning)
    if "usage" in response_dict:
        usage = response_dict["usage"]
        print()
        print("TOKEN USAGE (indicates reasoning complexity):")
        print(f"  Input tokens:  {usage.get('input_tokens', 0)}")
        print(f"  Output tokens: {usage.get('output_tokens', 0)}")
        print(f"  Total tokens:  {usage.get('total_tokens', 0)}")

    print()
    print("=" * 70)
    print("ANSWER PREVIEW (first 800 chars):")
    print("-" * 50)
    answer = response.output_text
    # Replace unicode for console
    answer = answer.encode('ascii', 'replace').decode('ascii')
    print(answer[:800] + "..." if len(answer) > 800 else answer)

    # Save full response for detailed inspection
    with open("agent_response.json", "w", encoding="utf-8") as f:
        json.dump(response_dict, f, indent=2, default=str)
    print()
    print("Full response saved to agent_response.json")

    return response_dict


if __name__ == "__main__":
    question = "What are the common causes of spindle vibration and how do I troubleshoot them?"
    query_with_details(question)
