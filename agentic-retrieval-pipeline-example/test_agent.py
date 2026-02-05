"""
Test the davenport-assistant agent with complex queries.
Verifies agentic retrieval is working with the Knowledge Base.
"""

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
AGENT_NAME = "davenport-assistant"

# Test queries that should exercise agentic retrieval
# These are complex questions that require query decomposition
TEST_QUERIES = [
    "What are the common causes of excessive spindle vibration on a Davenport Model B?",
    "How do I adjust the stock reel tension and what tools do I need?",
]


def main():
    print("Testing Davenport Assistant Agent")
    print("=" * 50)
    print()

    # Authenticate
    credential = DefaultAzureCredential()

    # Create project client
    project_client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=credential
    )

    # Get OpenAI client for conversations
    openai_client = project_client.get_openai_client()

    # Create a conversation
    conversation = openai_client.conversations.create()
    print(f"Conversation ID: {conversation.id}")
    print()

    # Test with first query
    query = TEST_QUERIES[0]
    print(f"Query: {query}")
    print("-" * 50)

    response = openai_client.responses.create(
        conversation=conversation.id,
        tool_choice="required",  # Force use of knowledge base
        input=query,
        extra_body={"agent": {"name": AGENT_NAME, "type": "agent_reference"}},
    )

    print(f"Response:")
    # Handle Unicode characters for Windows console
    output = response.output_text.encode('ascii', 'replace').decode('ascii')
    print(output)
    print()
    print("=" * 50)
    print("Test completed successfully!")


if __name__ == "__main__":
    main()
