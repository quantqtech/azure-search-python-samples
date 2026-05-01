"""
Merge 5 Foundry knowledge-source indexes + curated Q&A blobs into 1 unified BM25 index.

Lives inside func-api/ so the Function App's timer trigger and the manual rebuild
endpoint can import it directly. The repo-root build_unified_index.py is a thin
CLI shim around this module — runs the same logic locally for CI/manual rebuilds.

What this does:
  1. Creates davenport-kb-unified with a simple searchable schema (BM25, no vectors)
  2. Reads all docs from each of the 5 Foundry source indexes (paginated)
  3. Reads active curated Q&A from the curated-qa blob container
     (cross-referenced against the curatedqa Azure Table — only active rows)
  4. Uploads everything to the unified index with source_type + category tags

Re-runnable: uses mergeOrUpload, so re-running overwrites existing docs in-place.
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

STORAGE_ACCOUNT     = "stj6lw7vswhnnhw"
CURATED_CONTAINER   = "curated-qa"
CURATED_TABLE       = "curatedqa"  # Azure Table names must be alphanumeric only

# Source indexes — order matters: biggest first so we see progress early
SOURCE_INDEXES = [
    {"name": "ks-azureblob-maintenance-manuals-index", "source_type": "document", "category": "maintenance-manuals"},
    {"name": "ks-azureblob-video-training-index",      "source_type": "video",    "category": "video-training"},
    {"name": "ks-azureblob-engineering-tips-index",    "source_type": "document", "category": "engineering-tips"},
    {"name": "ks-azureblob-technical-tips-index",      "source_type": "document", "category": "technical-tips"},
    {"name": "ks-azureblob-troubleshooting-index",     "source_type": "document", "category": "troubleshooting"},
]

# ── Auth ──────────────────────────────────────────────────────────────────────
# DefaultAzureCredential picks up your active az login session (locally) or
# the Function App's managed identity (in-process timer).
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
    url  = f"{SEARCH_ENDPOINT}{path}?api-version={API_VERSION}"
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, method="PUT", headers=headers())
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def rest_get(path, params=""):
    url = f"{SEARCH_ENDPOINT}{path}?api-version={API_VERSION}{params}"
    req = urllib.request.Request(url, headers=headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def rest_post(path, payload):
    url  = f"{SEARCH_ENDPOINT}{path}?api-version={API_VERSION}"
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, method="POST", headers=headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ── Step 1: Create the unified index ─────────────────────────────────────────
def create_unified_index(verbose=True):
    if verbose:
        print(f"Creating index: {UNIFIED_INDEX}")

    index_def = {
        "name": UNIFIED_INDEX,
        "fields": [
            {"name": "chunk_id",          "type": "Edm.String", "key": True,  "searchable": False, "filterable": True,  "retrievable": True},
            {"name": "snippet",           "type": "Edm.String", "key": False, "searchable": True,  "filterable": False, "retrievable": True, "analyzer": "en.microsoft"},
            {"name": "blob_url",          "type": "Edm.String", "key": False, "searchable": False, "filterable": False, "retrievable": True},
            {"name": "snippet_parent_id", "type": "Edm.String", "key": False, "searchable": False, "filterable": True,  "retrievable": True},
            {"name": "source_type",       "type": "Edm.String", "key": False, "searchable": False, "filterable": True,  "retrievable": True, "facetable": True},
            {"name": "category",          "type": "Edm.String", "key": False, "searchable": False, "filterable": True,  "retrievable": True, "facetable": True},
        ],
        "similarity": {"@odata.type": "#Microsoft.Azure.Search.BM25Similarity"},
    }

    result = rest_put(f"/indexes/{UNIFIED_INDEX}", index_def)
    if verbose:
        name   = result.get("name", UNIFIED_INDEX)
        fields = result.get("fields", index_def["fields"])
        print(f"  Index ready: {name} ({len(fields)} fields)")
    return result


def read_all_docs(index_name, verbose=True):
    """Read every doc from a source index using $skip pagination."""
    all_docs = []
    skip = 0
    page_size = 1000

    while True:
        params = f"&$top={page_size}&$skip={skip}&$select=uid,snippet,blob_url,snippet_parent_id&$count=true"
        data   = rest_get(f"/indexes/{index_name}/docs", params)

        batch = data.get("value", [])
        all_docs.extend(batch)

        if skip == 0 and verbose:
            total = data.get("@odata.count", "?")
            print(f"    Expected total: {total}")

        if len(batch) < page_size:
            break
        skip += page_size

    return all_docs


def map_doc(raw_doc, source_type, category):
    """Map a Foundry-generated source doc to the unified index schema.

    Foundry's azure_ai_search tool only passes snippet text to the agent —
    metadata fields like blob_url are NOT visible to the agent. Prefixing the
    URL into the snippet is the only way to give the agent a clickable citation.
    """
    blob_url = raw_doc.get("blob_url", "")
    snippet  = raw_doc.get("snippet", "")
    snippet_with_source = f"[source: {blob_url}]\n{snippet}" if blob_url else snippet

    return {
        "@search.action": "mergeOrUpload",
        "chunk_id":          raw_doc.get("uid", ""),
        "snippet":           snippet_with_source,
        "blob_url":          blob_url,
        "snippet_parent_id": raw_doc.get("snippet_parent_id", ""),
        "source_type":       source_type,
        "category":          category,
    }


def upload_batch(docs, index_name=UNIFIED_INDEX, verbose=True):
    payload = {"value": docs}
    result  = rest_post(f"/indexes/{index_name}/docs/index", payload)

    results = result.get("value", [])
    failed  = [r for r in results if not r.get("status", False)]
    if failed and verbose:
        print(f"    WARNING: {len(failed)} docs failed to upload:")
        for f in failed[:5]:
            print(f"      {f.get('key', '?')}: {f.get('errorMessage', '?')}")

    return len(results) - len(failed)


# ── Curated Q&A pass ──────────────────────────────────────────────────────────
def _split_front_matter(text):
    """Parse a markdown file with YAML front matter delimited by '---' lines."""
    import yaml
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        front_matter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        front_matter = {}
    body = parts[2].lstrip("\n")
    return front_matter, body


def read_curated_blobs(verbose=True, force_reindex=False):
    """Read active curated Q&A entries that need (re)indexing.

    Skip logic: a chunk is skipped if it has already been indexed since its
    last approval — i.e. last_indexed_at >= approved_at (both ISO strings,
    lexicographic comparison works). Pass force_reindex=True to bypass the
    skip and re-process every active row (e.g. after a schema change).

    Yields dicts with {chunk_id, blob_url, body, front_matter, ledger_pk,
    source_feedback_pk, source_feedback_rk}.

    Skips ledger rows where active is explicitly False.
    """
    from azure.data.tables import TableServiceClient
    from azure.storage.blob import BlobServiceClient

    table_endpoint = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"
    blob_endpoint  = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"

    try:
        table_service = TableServiceClient(endpoint=table_endpoint, credential=credential)
        table_client = table_service.get_table_client(CURATED_TABLE)
        active_rows = list(table_client.query_entities(query_filter="active eq true"))
    except Exception as e:
        if verbose:
            print(f"  No curatedqa ledger or query failed ({e}); skipping curated pass")
        return

    if not active_rows:
        if verbose:
            print("  No active curated rows in ledger; skipping curated pass")
        return

    blob_service = BlobServiceClient(account_url=blob_endpoint, credential=credential)
    container = blob_service.get_container_client(CURATED_CONTAINER)

    skipped_already_indexed = 0
    for row in active_rows:
        chunk_id = row.get("RowKey", "")
        blob_url = row.get("blob_url", "")
        if not chunk_id or not blob_url:
            continue

        # Skip if already indexed since last approval — saves an upload + a MERGE
        if not force_reindex:
            last_indexed = row.get("last_indexed_at") or ""
            approved_at  = row.get("approved_at") or ""
            if last_indexed and approved_at and last_indexed >= approved_at:
                skipped_already_indexed += 1
                continue

        marker = f"/{CURATED_CONTAINER}/"
        idx = blob_url.find(marker)
        if idx == -1:
            if verbose:
                print(f"    WARN: blob_url for {chunk_id} doesn't reference container '{CURATED_CONTAINER}'")
            continue
        blob_path = blob_url[idx + len(marker):]

        try:
            blob_client = container.get_blob_client(blob_path)
            text = blob_client.download_blob().readall().decode("utf-8")
        except Exception as e:
            if verbose:
                print(f"    WARN: failed to download {blob_path}: {e}")
            continue

        front_matter, body = _split_front_matter(text)
        yield {
            "chunk_id":            chunk_id,
            "blob_url":            blob_url,
            "body":                body,
            "front_matter":        front_matter,
            "ledger_pk":           row.get("PartitionKey", ""),
            "source_feedback_pk":  row.get("source_feedback_pk", ""),
            "source_feedback_rk":  row.get("source_feedback_rk", ""),
        }

    if verbose and skipped_already_indexed > 0:
        print(f"  Skipped {skipped_already_indexed} curated chunks already indexed since approval")


def map_curated_doc(parsed_blob):
    """Build a unified-index record from a parsed curated-qa markdown blob.

    Prepends a [source: blob_url] line to match the existing convention so the
    agent's citation pipeline handles it identically to other source types.
    """
    blob_url = parsed_blob["blob_url"]
    body     = parsed_blob["body"].strip()
    snippet  = f"[source: {blob_url}]\n{body}"

    return {
        "@search.action":    "mergeOrUpload",
        "chunk_id":          parsed_blob["chunk_id"],
        "snippet":           snippet,
        "blob_url":          blob_url,
        "snippet_parent_id": "",
        "source_type":       "curated",
        "category":          "user-curated",
    }


# ── Indexed-at stamping ──────────────────────────────────────────────────────
def _stamp_indexed_at(curated_meta, verbose=True):
    """After a successful curated upload, MERGE indexed_at onto:
      - the curatedqa ledger row (last_indexed_at)
      - the source feedback row (indexed_at)
    so the admin UI can distinguish 'approved & live' from 'approved, awaiting rebuild'.

    Best-effort: a stamping failure logs a warning but doesn't break the rebuild.
    """
    from datetime import datetime, timezone
    from azure.data.tables import TableServiceClient, UpdateMode

    now_iso = datetime.now(timezone.utc).isoformat()
    table_endpoint = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"

    try:
        ts = TableServiceClient(endpoint=table_endpoint, credential=credential)
        ledger = ts.get_table_client(CURATED_TABLE)
        feedback = ts.get_table_client("feedback")
    except Exception as e:
        if verbose:
            print(f"    WARN: could not open tables for indexed_at stamping: {e}")
        return

    stamped_ledger = 0
    stamped_feedback = 0
    for meta in curated_meta:
        chunk_id   = meta.get("chunk_id", "")
        ledger_pk  = meta.get("ledger_pk", "")
        fb_pk      = meta.get("source_feedback_pk", "")
        fb_rk      = meta.get("source_feedback_rk", "")

        if chunk_id and ledger_pk:
            try:
                ledger.update_entity(
                    {"PartitionKey": ledger_pk, "RowKey": chunk_id, "last_indexed_at": now_iso},
                    mode=UpdateMode.MERGE,
                )
                stamped_ledger += 1
            except Exception as e:
                if verbose:
                    print(f"    WARN: ledger stamp failed for {chunk_id}: {e}")

        if fb_pk and fb_rk:
            try:
                feedback.update_entity(
                    {"PartitionKey": fb_pk, "RowKey": fb_rk, "indexed_at": now_iso},
                    mode=UpdateMode.MERGE,
                )
                stamped_feedback += 1
            except Exception as e:
                if verbose:
                    print(f"    WARN: feedback stamp failed for {fb_pk}/{fb_rk}: {e}")

    if verbose:
        print(f"    Stamped indexed_at: {stamped_ledger} ledger rows, {stamped_feedback} feedback rows")


# ── Main rebuild ──────────────────────────────────────────────────────────────
def rebuild_unified_index(verbose=True, force_reindex_curated=False):
    """Build/refresh the unified BM25 index from all 5 source indexes + curated Q&A.

    force_reindex_curated: if True, re-upload every active curated chunk even
    if its last_indexed_at >= approved_at (which would normally skip it).
    Use after a schema change or when you suspect drift between blobs and
    the index. Default False.

    Returns a summary dict: {total_uploaded, by_source, final_count}.
    """
    def log(msg):
        if verbose:
            print(msg)

    log("=" * 60)
    log("Building davenport-kb-unified index")
    log("=" * 60)

    create_unified_index(verbose=verbose)
    log("")

    summary = {"by_source": {}, "total_uploaded": 0}

    # Pass 1-5: existing source indexes
    for src in SOURCE_INDEXES:
        index_name  = src["name"]
        source_type = src["source_type"]
        category    = src["category"]

        log(f"Processing: {index_name}")
        log(f"  source_type={source_type}, category={category}")

        raw_docs = read_all_docs(index_name, verbose=verbose)
        log(f"  Read {len(raw_docs)} docs")

        if not raw_docs:
            log("  Skipping (no docs found)")
            summary["by_source"][index_name] = 0
            continue

        mapped_docs = [map_doc(d, source_type, category) for d in raw_docs]

        uploaded = 0
        for i in range(0, len(mapped_docs), BATCH_SIZE):
            batch   = mapped_docs[i : i + BATCH_SIZE]
            success = upload_batch(batch, verbose=verbose)
            uploaded += success
            log(f"  Batch {i // BATCH_SIZE + 1}: uploaded {success}/{len(batch)}")

        log(f"  Done: {uploaded}/{len(raw_docs)} docs uploaded")
        summary["by_source"][index_name] = uploaded
        summary["total_uploaded"] += uploaded
        log("")

    # Pass 6: curated Q&A from blob
    log("Processing: curated Q&A (blob -> unified, no Foundry knowledge source)")
    curated_records = []
    curated_meta = []  # parallel list to curated_records — for indexed_at stamping
    for parsed in read_curated_blobs(verbose=verbose, force_reindex=force_reindex_curated):
        curated_records.append(map_curated_doc(parsed))
        curated_meta.append(parsed)

    if not curated_records:
        log("  No new/changed curated records to upload" if not force_reindex_curated else "  No active curated records to upload")
        summary["by_source"]["curated-qa"] = 0
    else:
        log(f"  {len(curated_records)} active curated records")
        uploaded = 0
        for i in range(0, len(curated_records), BATCH_SIZE):
            batch   = curated_records[i : i + BATCH_SIZE]
            success = upload_batch(batch, verbose=verbose)
            uploaded += success
            log(f"  Batch {i // BATCH_SIZE + 1}: uploaded {success}/{len(batch)}")
        log(f"  Done: {uploaded}/{len(curated_records)} curated docs uploaded")
        summary["by_source"]["curated-qa"] = uploaded
        summary["total_uploaded"] += uploaded

        # Stamp indexed_at on the ledger row + source feedback row so the admin
        # UI can show "Indexed: <date>" vs "Awaiting next rebuild" per row.
        _stamp_indexed_at(curated_meta, verbose=verbose)
    log("")

    # Verification
    log("Verifying unified index...")
    if verbose:
        time.sleep(3)
    final_count = "?"
    try:
        count_data = rest_get(f"/indexes/{UNIFIED_INDEX}/docs", "&$count=true&$top=0")
        final_count = count_data.get("@odata.count", "?")
        log(f"  Final doc count: {final_count}")
    except Exception as e:
        log(f"  Count check failed: {e} (index may still be indexing)")
    summary["final_count"] = final_count

    log("")
    log("=" * 60)
    log(f"DONE - {summary['total_uploaded']} docs migrated to {UNIFIED_INDEX}")
    log("=" * 60)

    return summary
