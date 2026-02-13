"""
Fix MCP connections to match the working connection format.
The working connection uses CustomKeys auth and specific metadata.
"""

import os
import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# Configuration
PROJECT_RESOURCE_ID = "/subscriptions/09d43e37-e7dc-4869-9db4-768d8937df2e/resourceGroups/rg-gent-foundry-eus2/providers/Microsoft.CognitiveServices/accounts/aoai-j6lw7vswhnnhw/projects/proj-j6lw7vswhnnhw"
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"

# Get Search API key
SEARCH_KEY = os.environ.get("SEARCH_KEY")


def main():
    if not SEARCH_KEY:
        print("ERROR: SEARCH_KEY environment variable not set")
        print("Get key: az search admin-key show --resource-group rg-gent-foundry-eus2 --service-name srch-j6lw7vswhnnhw --query primaryKey -o tsv")
        return

    print("Fixing MCP connections to match working format...")
    print("=" * 50)

    credential = DefaultAzureCredential()
    bearer_token_provider = get_bearer_token_provider(credential, "https://management.azure.com/.default")
    headers = {
        "Authorization": f"Bearer {bearer_token_provider()}",
        "Content-Type": "application/json"
    }

    connections = [
        ("kb-minimal-connection", "davenport-kb-minimal"),
        ("kb-low-connection", "davenport-kb-low"),
    ]

    for conn_name, kb_name in connections:
        mcp_endpoint = f"{SEARCH_ENDPOINT}/knowledgebases/{kb_name}/mcp?api-version=2025-11-01-Preview"

        # Match the working connection format exactly
        payload = {
            "name": conn_name,
            "type": "Microsoft.MachineLearningServices/workspaces/connections",
            "properties": {
                "authType": "CustomKeys",
                "category": "RemoteTool",
                "target": mcp_endpoint,
                "isSharedToAll": False,
                "isDefault": False,
                "metadata": {
                    "knowledgeBaseName": kb_name,
                    "type": "knowledgeBase_MCP"
                },
                "credentials": {
                    "keys": {
                        "api-key": SEARCH_KEY
                    }
                }
            }
        }

        url = f"https://management.azure.com{PROJECT_RESOURCE_ID}/connections/{conn_name}?api-version=2025-10-01-preview"
        response = requests.put(url, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            print(f"[OK] Fixed connection: {conn_name}")
            print(f"     authType: CustomKeys")
            print(f"     metadata.type: knowledgeBase_MCP")
        else:
            print(f"[ERROR] {conn_name}: {response.status_code}")
            print(f"        {response.text[:200]}")

    print("\n" + "=" * 50)
    print("Connections fixed! Refresh Foundry and test agents.")


if __name__ == "__main__":
    main()
