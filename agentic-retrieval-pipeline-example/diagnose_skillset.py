"""
Diagnostic: dump the auth config from each skill in the maintenance-manuals skillset.
Shows how each skill authenticates to AOAI so we can fix the 401 errors.

Usage:
  python agentic-retrieval-pipeline-example/diagnose_skillset.py
"""

import json
import requests
from azure.identity import DefaultAzureCredential

SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
API_VERSION = "2025-11-01-Preview"
SKILLSET_NAME = "ks-azureblob-maintenance-manuals-skillset"


def main():
    credential = DefaultAzureCredential()
    token = credential.get_token("https://search.azure.com/.default")
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }

    url = f"{SEARCH_ENDPOINT}/skillsets/{SKILLSET_NAME}?api-version={API_VERSION}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    skillset = response.json()

    print(f"Skillset: {skillset['name']}")
    print(f"Skills count: {len(skillset.get('skills', []))}")
    print("=" * 60)

    for i, skill in enumerate(skillset.get("skills", [])):
        skill_type = skill.get("@odata.type", "unknown")
        skill_name = skill.get("name", f"skill-{i}")

        print(f"\n--- Skill {i}: {skill_name} ---")
        print(f"  Type: {skill_type}")

        # Auth-related fields for embedding skills
        if "Embedding" in skill_type:
            print(f"  deploymentId: {skill.get('deploymentId', 'NOT SET')}")
            print(f"  modelName: {skill.get('modelName', 'NOT SET')}")
            print(f"  dimensions: {skill.get('dimensions', 'NOT SET')}")
            print(f"  resourceUri: {skill.get('resourceUri', 'NOT SET')}")
            print(f"  apiKey: {'SET (redacted)' if skill.get('apiKey') else 'NOT SET'}")
            print(f"  authIdentity: {skill.get('authIdentity', 'NOT SET')}")

        # Auth-related fields for ChatCompletion / GenAI skills
        if "ChatCompletion" in skill_type or "GenAI" in skill_type:
            print(f"  uri: {skill.get('uri', 'NOT SET')}")
            print(f"  httpMethod: {skill.get('httpMethod', 'NOT SET')}")
            print(f"  authResourceId: {skill.get('authResourceId', 'NOT SET')}")
            print(f"  authIdentity: {skill.get('authIdentity', 'NOT SET')}")
            # Check httpHeaders for api-key
            http_headers = skill.get("httpHeaders", {})
            if http_headers:
                for key, val in http_headers.items():
                    redacted = "SET (redacted)" if val else "NOT SET"
                    print(f"  httpHeaders[{key}]: {redacted}")
            else:
                print(f"  httpHeaders: NONE")

        # Show inputs summary
        inputs = skill.get("inputs", [])
        print(f"  inputs: {[inp.get('name') for inp in inputs]}")

    # Also check cognitiveServices config on the skillset
    cog = skillset.get("cognitiveServices")
    print(f"\n{'=' * 60}")
    print(f"cognitiveServices: {json.dumps(cog, indent=2) if cog else 'NOT SET'}")

    # Check knowledgeStore
    ks = skillset.get("knowledgeStore")
    print(f"knowledgeStore: {'SET' if ks else 'NOT SET'}")

    # Dump full JSON for reference
    print(f"\n{'=' * 60}")
    print("Full skillset JSON (for reference):")
    print(json.dumps(skillset, indent=2))


if __name__ == "__main__":
    main()
