"""
Update the davenport-assistant agent with shop-floor friendly instructions.
- Shorter, more direct answers
- Human-readable source references instead of ref_id
"""

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
MCP_CONNECTION_NAME = "kb-davenport-machine-k-dx3ql"
MCP_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net/knowledgebases/davenport-machine-kb/mcp?api-version=2025-11-01-Preview"
MODEL_DEPLOYMENT = "gpt-5-mini"
AGENT_NAME = "davenport-assistant"

# Shop-floor friendly instructions
AGENT_INSTRUCTIONS = """You are a technical support assistant for Davenport Model B screw machines.

RESPONSE STYLE - CRITICAL:
- Keep answers SHORT and DIRECT - these are busy shop floor workers
- Use bullet points, not paragraphs
- Lead with the most likely cause first
- Skip background explanations - just give the fix
- Maximum 5-6 bullet points per answer unless asked for more detail

CITATION FORMAT - CRITICAL:
- Do NOT use [ref_id:X] format - workers can't use these
- Instead cite like: (Source: Video - Preventive Maintenance) or (Source: Tech Tip - Cam Roll Inspection)
- Map source types:
  - Video training content -> "Video - [topic]"
  - Engineering tips -> "Engineering Bulletin - [topic]"
  - Technical tips -> "Tech Tip - [topic]"
  - Troubleshooting guides -> "Troubleshooting Guide"
  - Maintenance manuals -> "Maintenance Manual"

EXAMPLE GOOD RESPONSE:
"Common causes of spindle vibration (check in this order):
1. Wrong feed/speed gears - verify against setup sheet
2. Loose tooling or worn dovetails - check tool mounting
3. Worn feed fingers - test tension while stocking
4. Bad cam rolls - lift lever, feel for flat spots
5. Bent bar stock - inspect and replace

(Sources: Troubleshooting Guide, Video - Preventive Maintenance)"

If asked for more detail on any item, then expand on that specific item only.
"""


def main():
    print("Updating Davenport Assistant with shop-floor friendly instructions...")
    print()

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    # Create MCPTool
    mcp_kb_tool = MCPTool(
        server_label="knowledge-base",
        server_url=MCP_ENDPOINT,
        require_approval="never",
        allowed_tools=["knowledge_base_retrieve"],
        project_connection_id=MCP_CONNECTION_NAME
    )

    # Create new version of the agent with updated instructions
    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT,
            instructions=AGENT_INSTRUCTIONS,
            tools=[mcp_kb_tool]
        )
    )

    print(f"[OK] Agent updated successfully!")
    print(f"  Agent Name: {agent.name}")
    print(f"  New Version: {agent.version}")
    print()
    print("Changes made:")
    print("  - Shorter, bullet-point responses")
    print("  - Human-readable source citations")
    print("  - Shop-floor worker friendly tone")


if __name__ == "__main__":
    main()
