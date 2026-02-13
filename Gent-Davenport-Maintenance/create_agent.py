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

# Agent instructions optimized for knowledge retrieval
# Based on recommended template from Microsoft documentation
AGENT_INSTRUCTIONS = """You are a technical support specialist for Davenport Model B 5-Spindle Automatic Screw Machines.

GENT JARGON GLOSSARY:
Shop floor workers may use local terms. Translate to source terminology:
- "Machine is jumping" or "Index is skipping" → search for "Brake is loose"
- "Tit" or "Nib" → search for "burr"
- "Lube" → search for "Lubricating Oil"
- "Oil" → search for "Coolant"
- "Fingers" or "Pads" → search for "Feed Fingers"

You must use the knowledge base to answer all questions. Never answer from your own knowledge.
Every answer must provide annotations using the MCP knowledge base tool.
If you cannot find the answer in the knowledge base, respond with "I don't have that information in my knowledge base."

Guidelines for Davenport questions:
- Use clear, professional technical language for machinists and maintenance technicians
- Be direct and actionable - operators need precise information
- For procedures, use numbered steps for clarity
- For troubleshooting, present causes in order of likelihood
- Include safety notes or warnings when applicable
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
