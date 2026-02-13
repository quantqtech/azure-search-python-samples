"""
Streamlit Chat UI for Davenport Assistant Agent.
Provides a web interface to the agentic retrieval system.

Run with: streamlit run app.py
"""

import streamlit as st
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
AGENT_NAME = "davenport-assistant"

# Page config
st.set_page_config(
    page_title="Davenport Technical Support",
    page_icon="🔧",
    layout="wide"
)

st.title("🔧 Davenport Model B Technical Support")
st.caption("Ask questions about your Davenport 5-Spindle Automatic Screw Machine")


@st.cache_resource
def get_clients():
    """Initialize Azure clients (cached for performance)."""
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=credential
    )
    openai_client = project_client.get_openai_client()
    return project_client, openai_client


def get_conversation_id():
    """Get or create a conversation ID for the session."""
    if "conversation_id" not in st.session_state:
        _, openai_client = get_clients()
        conversation = openai_client.conversations.create()
        st.session_state.conversation_id = conversation.id
    return st.session_state.conversation_id


def ask_agent(query: str) -> str:
    """Send a query to the agent and return the response."""
    _, openai_client = get_clients()
    conversation_id = get_conversation_id()

    response = openai_client.responses.create(
        conversation=conversation_id,
        tool_choice="required",
        input=query,
        extra_body={"agent": {"name": AGENT_NAME, "type": "agent_reference"}},
    )

    return response.output_text


# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask about your Davenport machine..."):
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("Searching knowledge base..."):
            try:
                response = ask_agent(prompt)
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

# Sidebar with example questions
with st.sidebar:
    st.header("Example Questions")
    st.markdown("""
    Try asking:
    - What are the common causes of spindle vibration?
    - How do I adjust the stock reel tension?
    - What's the procedure for replacing cam rolls?
    - How do I troubleshoot chatter on position 3?
    - What preventive maintenance should I perform weekly?
    """)

    st.divider()

    if st.button("Clear Chat History"):
        st.session_state.messages = []
        if "conversation_id" in st.session_state:
            del st.session_state.conversation_id
        st.rerun()

    st.divider()
    st.caption("Powered by Azure AI Foundry + Agentic Retrieval")
