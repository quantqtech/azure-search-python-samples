"""
Merge 5 Foundry knowledge-source indexes into 1 unified BM25 index.

Why: The Foundry MCP pipeline that spans these indexes takes 43-49s per query.
Switching to a single azure_ai_search direct tool drops that to ~2s.

What this does:
  1. Creates davenport-kb-unified with a simple searchable schema
  2. Reads all docs from each of the 5 source indexes (paginated)
  3. Uploads them to the unified index with source_type + category tags

Re-runnable: uses mergeOrUpload, so re-running overwrites existing docs in-place.

Run: python build_unified_index.py
"""

import json
import time
import urllib.request
import urllib.error
from azure.identity import DefaultAzureCredential

# ── Config ────────────────────────────────────────────────────────────────────
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
API_VERSION     = "2025-11-01-Preview"
UNIFIED_INDEX   = "davenport-kb-unified"
BATCH_SIZE      = 500   # Azure Search max batch is 1000 docs; 500 is safe

# Source indexes — order matters: biggest first so we see progress early
SOURCE_INDEXES = [
    {"name": "ks-azureblob-maintenance-manuals-index", "source_type": "document", "category": "maintenance-manuals"},
    {"name": "ks-azureblob-video-training-index",      "source_type": "video",    "category": "video-training"},
    {"name": "ks-azureblob-engineering-tips-index",    "source_type": "document", "category": "engineering-tips"},
    {"name": "ks-azureblob-technical-tips-index",      "source_type": "document", "category": "technical-tips"},
    {"name": "ks-azureblob-troubleshooting-index",     "source_type": "document", "category": "troubleshooting"},
]

# ── Auth ──────────────────────────────────────────────────────────────────────
# DefaultAzureCredential picks up your active az login session
credential = DefaultAzureCredential()

def get_token():
    """Get a fresh bearer token for Azure Search."""
    token = credential.get_token("https://search.azure.com/.default")
    return token.token

def headers():
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type":  "application/json",
    }

# ── HTTP helpers ──────────────────────────────────────────────────────────────
def rest_put(path, payload):
    """PUT to Azure Search REST API — used for idempotent index creation."""
    url  = f"{SEARCH_ENDPOINT}{path}?api-version={API_VERSION}"
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, method="PUT", headers=headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def rest_get(path, params=""):
    """GET from Azure Search REST API — used for reading docs."""
    url = f"{SEARCH_ENDPOINT}{path}?api-version={API_VERSION}{params}"
    req = urllib.request.Request(url, headers=headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def rest_post(path, payload):
    """POST to Azure Search REST API — used for batch doc upload."""
    url  = f"{SEARCH_ENDPOINT}{path}?api-version={API_VERSION}"
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, method="POST", headers=headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ── Step 1: Create the unified index ─────────────────────────────────────────
def create_unified_index():
    """
    PUT the unified index definition — idempotent, safe to re-run.
    No vector field: we're using BM25 (simple query) for speed.
    source_type and category are filterable for future faceting.
    """
    print(f"Creating index: {UNIFIED_INDEX}")

    index_def = {
        "name": UNIFIED_INDEX,
        "fields": [
            # chunk_id is the unique key — maps from uid in source indexes
            {"name": "chunk_id",          "type": "Edm.String", "key": True,  "searchable": False, "filterable": True,  "retrievable": True},
            # snippet is the main searchable text
            {"name": "snippet",           "type": "Edm.String", "key": False, "searchable": True,  "filterable": False, "retrievable": True, "analyzer": "en.microsoft"},
            # blob_url for citations (videos: function_app.py converts these to YouTube URLs)
            {"name": "blob_url",          "type": "Edm.String", "key": False, "searchable": False, "filterable": False, "retrievable": True},
            # parent doc ID — used for context grouping if needed later
            {"name": "snippet_parent_id", "type": "Edm.String", "key": False, "searchable": False, "filterable": True,  "retrievable": True},
            # "video" or "document" — lets agents distinguish citation format
            {"name": "source_type",       "type": "Edm.String", "key": False, "searchable": False, "filterable": True,  "retrievable": True, "facetable": True},
            # original knowledge base category (maintenance-manuals, video-training, etc.)
            {"name": "category",          "type": "Edm.String", "key": False, "searchable": False, "filterable": True,  "retrievable": True, "facetable": True},
        ],
        # BM25 is the default; semantic and vector config intentionally omitted for speed
        "similarity": {"@odata.type": "#Microsoft.Azure.Search.BM25Similarity"},
    }

    result = rest_put(f"/indexes/{UNIFIED_INDEX}", index_def)
    print(f"  Index ready: {result.get('name', '?')} ({len(result.get('fields', []))} fields)")
    return result


# ── Step 2: Read all docs from a source index ─────────────────────────────────
def read_all_docs(index_name):
    """
    Read every doc from a source index using $skip pagination.
    Returns a list of raw doc dicts from Azure Search.
    """
    all_docs = []
    skip = 0
    page_size = 1000  # max per Azure Search request

    while True:
        params = f"&$top={page_size}&$skip={skip}&$select=uid,snippet,blob_url,snippet_parent_id&$count=true"
        data   = rest_get(f"/indexes/{index_name}/docs", params)

        batch = data.get("value", [])
        all_docs.extend(batch)

        # First page: show expected total
        if skip == 0:
            total = data.get("@odata.count", "?")
            print(f"    Expected total: {total}")

        if len(batch) < page_size:
            break  # last page
        skip += page_size

    return all_docs


# ── Step 3: Map source doc to unified schema ──────────────────────────────────
def map_doc(raw_doc, source_type, category):
    """
    Map a Foundry-generated source doc to the unified index schema.
    uid → chunk_id (the key field)
    Adds source_type and category tags.
    """
    return {
        "@search.action": "mergeOrUpload",  # idempotent upsert
        "chunk_id":          raw_doc.get("uid", ""),
        "snippet":           raw_doc.get("snippet", ""),
        "blob_url":          raw_doc.get("blob_url", ""),
        "snippet_parent_id": raw_doc.get("snippet_parent_id", ""),
        "source_type":       source_type,
        "category":          category,
    }


# ── Step 4: Upload docs in batches ────────────────────────────────────────────
def upload_batch(docs, index_name=UNIFIED_INDEX):
    """Upload a batch of mapped docs to the unified index."""
    payload = {"value": docs}
    result  = rest_post(f"/indexes/{index_name}/docs/index", payload)

    # Check for per-doc failures (Azure Search returns 200 even if some docs failed)
    results = result.get("value", [])
    failed  = [r for r in results if not r.get("status", False)]
    if failed:
        print(f"    WARNING: {len(failed)} docs failed to upload:")
        for f in failed[:5]:  # show first 5
            print(f"      {f.get('key', '?')}: {f.get('errorMessage', '?')}")

    return len(results) - len(failed)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Building davenport-kb-unified index")
    print("=" * 60)

    # Step 1: Create the index (idempotent PUT)
    create_unified_index()
    print()

    total_uploaded = 0

    # Step 2+3+4: For each source index, read → map → upload
    for src in SOURCE_INDEXES:
        index_name  = src["name"]
        source_type = src["source_type"]
        category    = src["category"]

        print(f"Processing: {index_name}")
        print(f"  source_type={source_type}, category={category}")

        # Read all docs from this source index
        raw_docs = read_all_docs(index_name)
        print(f"  Read {len(raw_docs)} docs")

        if not raw_docs:
            print("  Skipping (no docs found)")
            continue

        # Map to unified schema
        mapped_docs = [map_doc(d, source_type, category) for d in raw_docs]

        # Upload in batches
        uploaded = 0
        for i in range(0, len(mapped_docs), BATCH_SIZE):
            batch   = mapped_docs[i : i + BATCH_SIZE]
            success = upload_batch(batch)
            uploaded += success
            print(f"  Batch {i // BATCH_SIZE + 1}: uploaded {success}/{len(batch)}")

        print(f"  Done: {uploaded}/{len(raw_docs)} docs uploaded")
        total_uploaded += uploaded
        print()

    # Step 5: Verify final count (allow a moment for indexing to settle)
    print("Verifying unified index...")
    time.sleep(3)

    try:
        count_data = rest_get(f"/indexes/{UNIFIED_INDEX}/docs", "&$count=true&$top=0")
        final_count = count_data.get("@odata.count", "?")
        print(f"  Final doc count: {final_count}")
    except Exception as e:
        print(f"  Count check failed: {e} (index may still be indexing)")

    print()
    print("=" * 60)
    print(f"DONE — {total_uploaded} docs migrated to {UNIFIED_INDEX}")
    print()
    print("Next step: update create_direct_search_agent.py to use this index,")
    print("then test in Foundry playground.")
    print("=" * 60)


if __name__ == "__main__":
    main()
