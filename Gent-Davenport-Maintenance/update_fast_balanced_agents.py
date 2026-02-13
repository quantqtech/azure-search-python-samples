"""
Update davenport-fast and davenport-balanced agents to v3.
Points them to the fixed Knowledge Bases with correct MCP config.
"""

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
MODEL = "gpt-5-mini"

AGENT_INSTRUCTIONS = """You are a technical support assistant for Davenport Model B screw machines.

GENT JARGON GLOSSARY:
Shop floor workers may use local terms. Translate to source terminology:
- "Machine is jumping" or "Index is skipping" → search for "Brake is loose"
- "Tit" or "Nib" → search for "burr"
- "Lube" → search for "Lubricating Oil"
- "Oil" → search for "Coolant"
- "Fingers" or "Pads" → search for "Feed Fingers"

RESPONSE STYLE:
- Use bullet points, be concise
- Lead with most likely cause first
- Shop floor workers need quick answers

CITATION FORMAT - CRITICAL:
- Put citations INLINE after each bullet point, not grouped at the end
- Format: bullet point text ([Source Name](url) page X)
- Include page number or timestamp when available
- Every fact should have its source immediately after it

RESPONSE LENGTH:
- Simple questions: 50-100 words
- Complex questions: 150-250 words
- Always use bullet points
"""


def main():
    print("Updating Fast and Balanced agents to v3...")
    print("=" * 50)

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    # Agent configs: (name, mcp_connection, kb_name)
    agents_config = [
        ("davenport-fast", "kb-minimal-connection", "davenport-kb-minimal"),
        ("davenport-balanced", "kb-low-connection", "davenport-kb-low"),
    ]

    for agent_name, mcp_connection, kb_name in agents_config:
        mcp_endpoint = f"{SEARCH_ENDPOINT}/knowledgebases/{kb_name}/mcp?api-version=2025-11-01-Preview"

        mcp_tool = MCPTool(
            server_label="knowledge-base",
            server_url=mcp_endpoint,
            require_approval="never",
            allowed_tools=["knowledge_base_retrieve"],
            project_connection_id=mcp_connection
        )

        agent = project_client.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(
                model=MODEL,
                instructions=AGENT_INSTRUCTIONS,
                tools=[mcp_tool]
            )
        )
        print(f"[OK] {agent_name} updated to v{agent.version}")
        print(f"     Using KB: {kb_name}")
        print(f"     MCP connection: {mcp_connection}")

    print("\n" + "=" * 50)
    print("Agents updated! Test Fast and Balanced modes now.")


if __name__ == "__main__":
    main()
