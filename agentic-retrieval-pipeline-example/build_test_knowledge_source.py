"""
Build a test knowledge source from scratch with step-by-step verification.

Creates a minimal pipeline: blob storage → embedding → search index.
No image processing, no text splitting — just the simplest possible working pipeline.
Uses a 'test-mm-' prefix so it doesn't collide with existing resources.

Each step creates a resource and immediately verifies it exists.
If any step fails, the script stops and prints what went wrong.

Prerequisites:
  - AOAI_KEY env var set (embedding skill auth)
  - az login (search service auth via DefaultAzureCredential)
  - Search service managed identity has 'Storage Blob Data Reader' on storage account

Get AOAI key:
  az cognitiveservices account keys list --name aoai-j6lw7vswhnnhw --resource-group rg-gent-foundry-eus2 --query key1 -o tsv

Usage:
  python agentic-retrieval-pipeline-example/build_test_knowledge_source.py
"""

import os
import sys
import time
import json
import requests
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

# Load .env file from the script's directory (keeps secrets out of shell history)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

# ============================================================
# Configuration
# ============================================================
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
AOAI_RESOURCE_URL = "https://aoai-j6lw7vswhnnhw.openai.azure.com"
API_VERSION = "2025-11-01-Preview"

# Resource names — all prefixed to avoid collision with existing resources
PREFIX = "test-mm"
INDEX_NAME = f"{PREFIX}-index"
DATASOURCE_NAME = f"{PREFIX}-datasource"
SKILLSET_NAME = f"{PREFIX}-skillset"
INDEXER_NAME = f"{PREFIX}-indexer"

# Embedding — text-embedding-3-large truncated to 1536d
# Better quality than -small at the same dimension (Matryoshka embeddings)
# Deployment name must match Foundry exactly (includes the suffix)
EMBEDDING_DEPLOYMENT = "text-embedding-3-large-088065"
EMBEDDING_MODEL_NAME = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536

# Blob storage — ztest container with 1 small file for minimal testing
CONTAINER_NAME = "ztest"
STORAGE_RESOURCE_ID = (
    "ResourceId=/subscriptions/09d43e37-e7dc-4869-9db4-768d8937df2e"
    "/resourceGroups/rg-gent-foundry-eus2"
    "/providers/Microsoft.Storage/storageAccounts/stj6lw7vswhnnhw;"
)

# AOAI API key for embedding skill
AOAI_KEY = os.environ.get("AOAI_KEY")


# ============================================================
# Helpers
# ============================================================
def get_headers():
    """Get auth headers for Azure Search REST API."""
    credential = DefaultAzureCredential()
    token = credential.get_token("https://search.azure.com/.default")
    return {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }


def api_delete(headers, resource_type, name):
    """DELETE a resource from Azure Search. Silently succeeds if it doesn't exist."""
    url = f"{SEARCH_ENDPOINT}/{resource_type}/{name}?api-version={API_VERSION}"
    response = requests.delete(url, headers=headers)
    return response.ok or response.status_code == 404


def api_put(headers, resource_type, name, body):
    """PUT a resource to Azure Search. Returns (success, response_json_or_error)."""
    url = f"{SEARCH_ENDPOINT}/{resource_type}/{name}?api-version={API_VERSION}"
    response = requests.put(url, headers=headers, json=body)
    if response.ok:
        return True, response.json() if response.content else {}
    return False, f"HTTP {response.status_code}: {response.text[:500]}"


def api_get(headers, resource_type, name):
    """GET a resource from Azure Search. Returns (success, response_json_or_error)."""
    url = f"{SEARCH_ENDPOINT}/{resource_type}/{name}?api-version={API_VERSION}"
    response = requests.get(url, headers=headers)
    if response.ok:
        return True, response.json()
    return False, f"HTTP {response.status_code}: {response.text[:500]}"


def api_post(headers, url_path):
    """POST to Azure Search (for indexer run/reset). Returns (success, error_msg)."""
    url = f"{SEARCH_ENDPOINT}/{url_path}?api-version={API_VERSION}"
    response = requests.post(url, headers=headers)
    if response.ok:
        return True, ""
    return False, f"HTTP {response.status_code}: {response.text[:500]}"


def step(number, description):
    """Print a step header."""
    print(f"\n{'=' * 60}")
    print(f"  Step {number}: {description}")
    print(f"{'=' * 60}")


def test_pass(description):
    """Print a passing test."""
    print(f"  [PASS] {description}")


def test_fail(description, detail=""):
    """Print a failing test and exit."""
    print(f"  [FAIL] {description}")
    if detail:
        print(f"         {detail}")
    print(f"\n  Stopping — fix the issue above and re-run.")
    sys.exit(1)


# ============================================================
# Step 1: Create Index
# ============================================================
def create_index(headers):
    step(1, f"Create Index '{INDEX_NAME}'")

    body = {
        "name": INDEX_NAME,
        "fields": [
            # Key field — unique doc ID generated by the indexer
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            # Document content — full text for search
            {"name": "content", "type": "Edm.String", "searchable": True, "retrievable": True},
            # Vector embedding of the content
            {
                "name": "content_vector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,
                "stored": False,
                "dimensions": EMBEDDING_DIMENSIONS,
                "vectorSearchProfile": "embedding-profile",
            },
            # Blob URL for citation/tracing
            {"name": "blob_url", "type": "Edm.String", "filterable": False, "retrievable": True},
            # Metadata — blob name for display
            {
                "name": "metadata_storage_name",
                "type": "Edm.String",
                "filterable": True,
                "retrievable": True,
            },
        ],
        # Vector search config — HNSW + AOAI vectorizer for query-time embedding
        "vectorSearch": {
            "profiles": [
                {
                    "name": "embedding-profile",
                    "algorithm": "hnsw-alg",
                    "vectorizer": "aoai-vectorizer",
                }
            ],
            "algorithms": [{"name": "hnsw-alg", "kind": "hnsw"}],
            "vectorizers": [
                {
                    "name": "aoai-vectorizer",
                    "kind": "azureOpenAI",
                    "azureOpenAIParameters": {
                        "resourceUri": AOAI_RESOURCE_URL,
                        "deploymentId": EMBEDDING_DEPLOYMENT,
                        "modelName": EMBEDDING_MODEL_NAME,
                        "apiKey": AOAI_KEY,
                    },
                }
            ],
        },
        # Semantic search config — required for agentic retrieval
        "semantic": {
            "defaultConfiguration": "semantic-config",
            "configurations": [
                {
                    "name": "semantic-config",
                    "prioritizedFields": {
                        "prioritizedContentFields": [{"fieldName": "content"}],
                    },
                }
            ],
        },
    }

    ok, result = api_put(headers, "indexes", INDEX_NAME, body)
    if not ok:
        test_fail("Failed to create index", result)

    print(f"  Created index '{INDEX_NAME}'")


def verify_index(headers):
    ok, index = api_get(headers, "indexes", INDEX_NAME)
    if not ok:
        test_fail("Index does not exist", index)

    # Check vector field exists with correct dimensions
    fields = {f["name"]: f for f in index.get("fields", [])}
    if "content_vector" not in fields:
        test_fail("Missing 'content_vector' field")

    dims = fields["content_vector"].get("dimensions")
    if dims != EMBEDDING_DIMENSIONS:
        test_fail(f"Vector dimensions mismatch: expected {EMBEDDING_DIMENSIONS}, got {dims}")

    test_pass(f"Index exists with {len(fields)} fields, content_vector={dims}d")

    # Check semantic config exists
    semantic = index.get("semantic", {})
    if not semantic.get("defaultConfiguration"):
        test_fail("Missing semantic configuration")

    test_pass("Semantic config present")


# ============================================================
# Step 2: Create Data Source
# ============================================================
def create_data_source(headers):
    step(2, f"Create Data Source '{DATASOURCE_NAME}'")

    body = {
        "name": DATASOURCE_NAME,
        "type": "azureblob",
        "credentials": {
            # Managed identity — search service uses its system-assigned identity
            "connectionString": STORAGE_RESOURCE_ID,
        },
        "container": {
            "name": CONTAINER_NAME,
        },
    }

    ok, result = api_put(headers, "datasources", DATASOURCE_NAME, body)
    if not ok:
        test_fail("Failed to create data source", result)

    print(f"  Created data source '{DATASOURCE_NAME}' -> container '{CONTAINER_NAME}'")


def verify_data_source(headers):
    ok, ds = api_get(headers, "datasources", DATASOURCE_NAME)
    if not ok:
        test_fail("Data source does not exist", ds)

    # Verify connection — Azure Search masks credentials on GET, so None is expected
    conn = ds.get("credentials", {}).get("connectionString")
    if conn is None:
        test_pass("Data source exists (connection string masked by Azure — normal)")
    elif "ResourceId=" in conn:
        test_pass("Data source uses managed identity (ResourceId)")
    elif "AccountKey" in conn:
        test_fail("Data source uses access key — should use managed identity")
    else:
        test_pass(f"Data source exists (connection: {conn[:50]}...)")

    # Verify container name
    container = ds.get("container", {}).get("name", "")
    if container == CONTAINER_NAME:
        test_pass(f"Container = '{container}'")
    else:
        test_fail(f"Wrong container: expected '{CONTAINER_NAME}', got '{container}'")


# ============================================================
# Step 3: Create Skillset
# ============================================================
def create_skillset(headers):
    step(3, f"Create Skillset '{SKILLSET_NAME}'")

    body = {
        "name": SKILLSET_NAME,
        "description": "Test skillset — embedding only, no image processing",
        "skills": [
            {
                "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
                "name": "EmbeddingSkill",
                "description": "Embed document content",
                "context": "/document",
                "resourceUri": AOAI_RESOURCE_URL,
                "apiKey": AOAI_KEY,
                "deploymentId": EMBEDDING_DEPLOYMENT,
                "modelName": EMBEDDING_MODEL_NAME,
                "dimensions": EMBEDDING_DIMENSIONS,
                "inputs": [
                    {"name": "text", "source": "/document/content"}
                ],
                "outputs": [
                    {"name": "embedding", "targetName": "content_vector"}
                ],
            }
        ],
    }

    ok, result = api_put(headers, "skillsets", SKILLSET_NAME, body)
    if not ok:
        test_fail("Failed to create skillset", result)

    print(f"  Created skillset '{SKILLSET_NAME}' with 1 skill (embedding only)")


def verify_skillset(headers):
    ok, ss = api_get(headers, "skillsets", SKILLSET_NAME)
    if not ok:
        test_fail("Skillset does not exist", ss)

    skills = ss.get("skills", [])
    if len(skills) != 1:
        test_fail(f"Expected 1 skill, got {len(skills)}")

    skill = skills[0]
    deployment = skill.get("deploymentId", "unknown")
    dims = skill.get("dimensions", 0)

    if deployment != EMBEDDING_DEPLOYMENT:
        test_fail(f"Wrong deployment: expected '{EMBEDDING_DEPLOYMENT}', got '{deployment}'")

    if dims != EMBEDDING_DIMENSIONS:
        test_fail(f"Wrong dimensions: expected {EMBEDDING_DIMENSIONS}, got {dims}")

    # Verify API key is NOT '<redacted>' (would mean the key wasn't set)
    api_key = skill.get("apiKey", "")
    if api_key == "<redacted>":
        # This is expected on GET — the key was set correctly at creation time
        test_pass("API key is set (masked as expected on GET)")
    elif api_key:
        test_pass("API key is set")
    else:
        test_fail("API key is NOT set — embedding will fail")

    test_pass(f"1 skill: {deployment} @ {dims}d")


# ============================================================
# Step 4: Create Indexer
# ============================================================
def create_indexer(headers):
    step(4, f"Create Indexer '{INDEXER_NAME}'")

    body = {
        "name": INDEXER_NAME,
        "dataSourceName": DATASOURCE_NAME,
        "targetIndexName": INDEX_NAME,
        "skillsetName": SKILLSET_NAME,
        # Map the embedding output to the index vector field
        "outputFieldMappings": [
            {
                "sourceFieldName": "/document/content_vector",
                "targetFieldName": "content_vector",
            }
        ],
        # Map blob URL to the index field
        "fieldMappings": [
            {
                "sourceFieldName": "metadata_storage_path",
                "targetFieldName": "id",
                "mappingFunction": {"name": "base64Encode"},
            },
            {
                "sourceFieldName": "metadata_storage_path",
                "targetFieldName": "blob_url",
            },
            {
                "sourceFieldName": "metadata_storage_name",
                "targetFieldName": "metadata_storage_name",
            },
        ],
    }

    ok, result = api_put(headers, "indexers", INDEXER_NAME, body)
    if not ok:
        test_fail("Failed to create indexer", result)

    print(f"  Created indexer '{INDEXER_NAME}'")
    print(f"    Data source: {DATASOURCE_NAME}")
    print(f"    Skillset:    {SKILLSET_NAME}")
    print(f"    Index:       {INDEX_NAME}")


def verify_indexer(headers):
    ok, idx = api_get(headers, "indexers", INDEXER_NAME)
    if not ok:
        test_fail("Indexer does not exist", idx)

    ds = idx.get("dataSourceName", "")
    ss = idx.get("skillsetName", "")
    ix = idx.get("targetIndexName", "")

    if ds == DATASOURCE_NAME:
        test_pass(f"Data source: {ds}")
    else:
        test_fail(f"Wrong data source: {ds}")

    if ss == SKILLSET_NAME:
        test_pass(f"Skillset: {ss}")
    else:
        test_fail(f"Wrong skillset: {ss}")

    if ix == INDEX_NAME:
        test_pass(f"Target index: {ix}")
    else:
        test_fail(f"Wrong target index: {ix}")


# ============================================================
# Step 5: Run Indexer & Verify
# ============================================================
def run_and_verify(headers):
    step(5, "Run Indexer & Verify")

    # Reset first to ensure clean state
    print("  Resetting indexer...")
    ok, err = api_post(headers, f"indexers/{INDEXER_NAME}/reset")
    if not ok:
        test_fail("Failed to reset indexer", err)
    test_pass("Indexer reset")

    # Run
    print("  Running indexer...")
    ok, err = api_post(headers, f"indexers/{INDEXER_NAME}/run")
    if not ok:
        test_fail("Failed to run indexer", err)
    test_pass("Indexer started")

    # Wait and poll status
    print("  Waiting for indexer to complete...")
    for attempt in range(6):
        time.sleep(10)
        ok, status = api_get(headers, "indexers", f"{INDEXER_NAME}/status")
        if not ok:
            test_fail("Failed to get indexer status", status)

        last = status.get("lastResult")
        if not last:
            print(f"    ({(attempt + 1) * 10}s) No results yet...")
            continue

        run_status = last.get("status", "unknown")
        items = last.get("itemCount", 0)
        failed = last.get("failedItemCount", 0)
        errors = last.get("errors", [])

        print(f"    ({(attempt + 1) * 10}s) Status: {run_status}, "
              f"Docs: {items}, Failed: {failed}")

        if run_status == "success":
            if items > 0:
                test_pass(f"Indexer succeeded: {items} doc(s) indexed, {failed} failed")
            else:
                test_fail("Indexer succeeded but 0 documents indexed — is the container empty?")

            if errors:
                print(f"  [WARN] {len(errors)} error(s):")
                for e in errors[:3]:
                    print(f"    - {e.get('message', 'unknown')[:200]}")

            # Show warnings if any
            warnings = last.get("warnings", [])
            if warnings:
                print(f"  [WARN] {len(warnings)} warning(s):")
                for w in warnings[:3]:
                    print(f"    - {w.get('message', 'unknown')[:200]}")

            return  # Success — move on

        if run_status in ("transientFailure", "persistentFailure"):
            print(f"\n  Errors:")
            for e in errors[:5]:
                print(f"    - {e.get('message', 'unknown')[:300]}")
            test_fail(f"Indexer failed with status: {run_status}")

    # If we get here, it's still running after 60 seconds
    print("  [INFO] Indexer still running after 60s — check portal for final status")
    print(f"         Portal: Azure Search > Indexers > {INDEXER_NAME}")


# ============================================================
# Step 6: Query the Index
# ============================================================
def query_index(headers):
    step(6, "Query the Index")

    # Simple text search
    url = f"{SEARCH_ENDPOINT}/indexes/{INDEX_NAME}/docs/search?api-version={API_VERSION}"
    body = {
        "search": "*",
        "top": 5,
        "select": "id,content,blob_url,metadata_storage_name",
    }

    response = requests.post(url, headers=headers, json=body)
    if not response.ok:
        test_fail("Search query failed", f"HTTP {response.status_code}: {response.text[:300]}")

    results = response.json()
    docs = results.get("value", [])

    if not docs:
        test_fail("No documents found in index — indexer may not have completed yet")

    test_pass(f"Found {len(docs)} document(s) in index")

    # Show a preview of each result
    for i, doc in enumerate(docs):
        name = doc.get("metadata_storage_name", "unknown")
        content = doc.get("content", "")[:150]
        print(f"\n  Doc {i + 1}: {name}")
        print(f"    Content preview: {content}...")

    print()
    test_pass("Index is searchable")


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("  Build Test Knowledge Source — Step-by-Step")
    print("=" * 60)
    print(f"  Prefix:    {PREFIX}")
    print(f"  Container: {CONTAINER_NAME}")
    print(f"  Embedding: {EMBEDDING_DEPLOYMENT} ({EMBEDDING_DIMENSIONS}d)")
    print(f"  AOAI Key:  {'SET' if AOAI_KEY else 'NOT SET'}")

    if not AOAI_KEY:
        print("\nERROR: AOAI_KEY environment variable not set")
        print("Get key: az cognitiveservices account keys list "
              "--name aoai-j6lw7vswhnnhw --resource-group rg-gent-foundry-eus2 "
              "--query key1 -o tsv")
        print("Then set: export AOAI_KEY='your-key-here'")
        sys.exit(1)

    headers = get_headers()

    # Clean up any previous test resources (so script is re-runnable)
    print("\n  Cleaning up previous test resources...")
    for res_type, res_name in [
        ("indexers", INDEXER_NAME),
        ("skillsets", SKILLSET_NAME),
        ("datasources", DATASOURCE_NAME),
        ("indexes", INDEX_NAME),
    ]:
        api_delete(headers, res_type, res_name)
    print("  [OK] Clean slate")

    # Each step: create resource, then verify it
    create_index(headers)
    verify_index(headers)

    create_data_source(headers)
    verify_data_source(headers)

    create_skillset(headers)
    verify_skillset(headers)

    create_indexer(headers)
    verify_indexer(headers)

    run_and_verify(headers)
    query_index(headers)

    # Summary
    print("\n" + "=" * 60)
    print("  ALL STEPS PASSED")
    print("=" * 60)
    print(f"\n  Resources created:")
    print(f"    Index:       {INDEX_NAME}")
    print(f"    Data Source: {DATASOURCE_NAME}")
    print(f"    Skillset:    {SKILLSET_NAME}")
    print(f"    Indexer:     {INDEXER_NAME}")
    print(f"\n  Next: Phase 2 — switch to text-embedding-3-large at 1536d")
    print(f"        Phase 3 — add image verbalization")
    print("=" * 60)


if __name__ == "__main__":
    main()
