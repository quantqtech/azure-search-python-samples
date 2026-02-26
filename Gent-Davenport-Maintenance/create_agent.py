"""
Create a Foundry Agent with MCPTool connected to the davenport-machine-kb Knowledge Base.
Uses existing infrastructure in rg-gent-foundry-eus2.

Based on the pattern from azure-search-python-samples/Gent-Davenport-Maintenance
"""

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

# Configuration - using existing resources
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
MCP_CONNECTION_NAME = "kb-davenport-machine-k-dx3ql"
MCP_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net/knowledgebases/davenport-machine-kb/mcp?api-version=2025-11-01-Preview"
MODEL_DEPLOYMENT = "gpt-5-mini"
AGENT_NAME = "davenport-assistant"

# Agent instructions — keep in sync with update_fast_balanced_agents.py
AGENT_INSTRUCTIONS = """You are a technical support specialist for Davenport Model B 5-Spindle Automatic Screw Machines at Gent Machine Company.

GENT JARGON GLOSSARY:
Shop floor workers use local terms. Silently translate these before searching:
- "Machine is jumping" / "Index is skipping" → "Brake is loose"
- "Tit" / "Nib" → "burr"
- "Lube" → "Lubricating Oil"
- "Oil" → "Coolant"
- "Fingers" / "Pads" → "Feed Fingers"
- "T blade" → "circular cutoff tool"
- "Shave tool" / "Sizing tool" → "sizing tool holder"
- "Step on the bar" / "Ring on the bar end" / "Bar feeding short" → search "cutoff adjustment" AND "protruding bar end" AND "collet seating"
- "Chatter" → "vibration" or "chatter marks"
- "Burr on cutoff" / "Dirty cutoff" → "cutoff finish" or "cutoff tool grind"

ANSWER STRUCTURE — follow this for troubleshooting questions:
1. Start with ONE sentence overview: "Found [N] items across [categories]."
2. List the top 5-8 causes/steps as bullets, each tagged with its category
3. End with: "Ask me to go deeper on [Tooling / Machine / Feeds & Speeds / Work Holding] if needed."

CATEGORY TAGS — include the relevant category after each bullet:
- [Tooling] — tool type, grind angle, sharpness, tip geometry, holder fit
- [Machine] — cam rolls, pins, levers, bearings, gibs, collets, brake
- [Feeds & Speeds] — gear selection, RPM, feed rate
- [Work Holding] — collet tension, feed fingers, chuck
- [Stock/Material] — bar size, straightness, material grade

CITATION FORMAT — CRITICAL:
- Cite INLINE after each bullet, never grouped at the end
- Format: bullet text [Category] ([Source Name](url) page X)
- Video: bullet text [Category] ([Video Name](url) MM:SS)
- Every fact must have a source citation immediately after it

RESPONSE STYLE:
- Lead with most likely cause first
- Be direct — machinists need actionable answers, not theory
- Bullet points only, not paragraphs
- If a question is simple (part number, definition, spec), answer in 2-3 bullets max
- Only use the knowledge base — never answer from your own training data
"""


def main():
    print("Creating Foundry Agent with MCPTool...")
    print(f"Project: {PROJECT_ENDPOINT}")
    print(f"MCP Endpoint: {MCP_ENDPOINT}")
    print(f"Connection: {MCP_CONNECTION_NAME}")
    print(f"Model: {MODEL_DEPLOYMENT}")
    print()

    # Authenticate using DefaultAzureCredential (uses az login)
    credential = DefaultAzureCredential()

    # Create project client
    project_client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=credential
    )

    # Create MCPTool pointing to knowledge base MCP endpoint
    mcp_kb_tool = MCPTool(
        server_label="knowledge-base",
        server_url=MCP_ENDPOINT,
        require_approval="never",
        allowed_tools=["knowledge_base_retrieve"],
        project_connection_id=MCP_CONNECTION_NAME
    )

    # Create the agent using create_version (as shown in reference notebook)
    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT,
            instructions=AGENT_INSTRUCTIONS,
            tools=[mcp_kb_tool]
        )
    )

    print(f"[OK] Agent created successfully!")
    print(f"  Agent Name: {agent.name}")
    print(f"  Agent Version: {agent.version}")
    print()
    print("You can now see this agent in the Azure AI Foundry portal:")
    print("https://ai.azure.com")

    return agent


if __name__ == "__main__":
    main()
