"""
Self-improving feedback loop for the Davenport KB.

Two stages:
  1. REFRESH (LLM, batch nightly): pull flagged/thumbs_down feedback with notes,
     classify gap/wrong/unclear/not_actionable, draft a clean proposed Q&A pair,
     MERGE result onto the feedback row.
  2. APPROVAL (human, ad-hoc): admin opens the Curation Queue, sees raw history
     side-by-side with the recommended upload, edits if needed, approves. Approval
     writes a markdown blob to curated-qa/, inserts a ledger row, and MERGEs the
     feedback row to review_status='approved'. The nightly unified rebuild reads
     active curated blobs and merges them into davenport-kb-unified.

Self-contained: own table/blob/openai/search clients (no imports from function_app
to avoid circular dependencies).
"""

import json
import logging
import os
import re
import time
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone

from azure.identity import DefaultAzureCredential

# ── Config ────────────────────────────────────────────────────────────────────
STORAGE_ACCOUNT     = os.environ.get("STORAGE_ACCOUNT", "stj6lw7vswhnnhw")
SEARCH_ENDPOINT     = os.environ.get("SEARCH_ENDPOINT", "https://srch-j6lw7vswhnnhw.search.windows.net")
SEARCH_API_VERSION  = "2025-11-01-Preview"
UNIFIED_INDEX       = "davenport-kb-unified"
AOAI_ENDPOINT       = os.environ.get("AOAI_ENDPOINT", "https://aoai-j6lw7vswhnnhw.openai.azure.com")
AOAI_API_VERSION    = "2024-10-21"

FEEDBACK_TABLE     = "feedback"
CURATED_TABLE      = "curatedqa"  # Azure Table names must be alphanumeric only
CURATED_CONTAINER  = "curated-qa"

EVALUATOR_MODEL          = "gpt-5-mini"   # batch job; reasoning useful, latency irrelevant
LOOKBACK_DAYS            = 14
MAX_PROPOSALS_PER_RUN    = 25
LOW_CONFIDENCE_THRESHOLD = 0.55

VALID_VERDICTS = {"gap", "wrong", "unclear_question", "not_actionable"}
VALID_REVIEW_STATUSES = {
    "pending", "proposed", "deferred", "not_actionable", "approved", "rejected"
}

# ── Lazy clients ──────────────────────────────────────────────────────────────
_credential = None
_table_clients = {}
_blob_service = None
_openai_client = None


def _get_credential():
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def _get_table_client(table_name):
    if table_name not in _table_clients:
        from azure.data.tables import TableServiceClient
        endpoint = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"
        service = TableServiceClient(endpoint=endpoint, credential=_get_credential())
        service.create_table_if_not_exists(table_name)
        _table_clients[table_name] = service.get_table_client(table_name)
    return _table_clients[table_name]


def _get_blob_service():
    global _blob_service
    if _blob_service is None:
        from azure.storage.blob import BlobServiceClient
        endpoint = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
        _blob_service = BlobServiceClient(account_url=endpoint, credential=_get_credential())
    return _blob_service


def _get_openai_client():
    """Direct AOAI client for the evaluator (chat.completions)."""
    global _openai_client
    if _openai_client is None:
        from openai import AzureOpenAI
        token = _get_credential().get_token("https://cognitiveservices.azure.com/.default")
        _openai_client = AzureOpenAI(
            azure_endpoint=AOAI_ENDPOINT,
            api_version=AOAI_API_VERSION,
            azure_ad_token=token.token,
        )
    return _openai_client


# ── Azure Search REST (same pattern as build_unified_index.py) ────────────────
def _search_token():
    return _get_credential().get_token("https://search.azure.com/.default").token


def _search_post(path, payload):
    url = f"{SEARCH_ENDPOINT}{path}?api-version={SEARCH_API_VERSION}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {_search_token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _bm25_search(question, top_k=10):
    """Mirror the production agent's retrieval: BM25 simple query, top-K=10."""
    payload = {
        "search":     question,
        "queryType":  "simple",
        "top":        top_k,
        "select":     "chunk_id,snippet,blob_url,source_type,category",
    }
    try:
        data = _search_post(f"/indexes/{UNIFIED_INDEX}/docs/search", payload)
        return data.get("value", [])
    except Exception as e:
        logging.warning(f"BM25 search failed for evaluator: {e}")
        return []


# ── Evaluator ─────────────────────────────────────────────────────────────────
EVALUATOR_SYSTEM_PROMPT = """You are an evaluation analyst for a Davenport Model B screw machine technical support RAG system at Gent Machine Company.

A machinist asked a question, the agent gave an answer, and the machinist flagged or thumbs-down'd it with notes. Your job: classify what went wrong and, when actionable, draft a clean canonical Q&A pair that would help the NEXT machinist who has the same problem.

VERDICTS
- gap:              The KB is missing the information needed. Retrieved chunks don't contain the answer.
- wrong:            The KB has the right information, but the agent's answer contradicted it or missed it.
- unclear_question: The original question is so vague/garbled that no answer would have helped — the fix is a jargon mapping or clarification.
- not_actionable:   Test data, off-topic, single-character notes, or feedback the agent actually answered correctly.

CRITICAL: HOW TO WRITE proposed_question
The proposed_question is what a FUTURE machinist with the same problem would naturally type. They don't yet know the diagnosis. Write the question as a SYMPTOM, in machinist language.

✓ GOOD:  "I have a nib (burr) on the cutoff end of my part — what should I do?"
✗ BAD:   "How does cutoff tool center height cause a nib?"  ← leaks the diagnosis from the user's notes; future machinist would never type this

✓ GOOD:  "My machine is jumping during the cycle — what's wrong?"
✗ BAD:   "How do I tighten a loose brake?"  ← presumes diagnosis the user hasn't made yet

The canonical question MUST:
- Stay symptom-focused, in the machinist's natural phrasing
- Fix typos and grammar; expand abbreviations
- Preserve shop-floor jargon (so semantic match works for future flaggers)
- Resolve pronouns ("it" -> "the chuck", etc.)

The canonical question MUST NOT:
- Reference the diagnosis, fix, or part the answer will name
- Pull terminology from user_notes, agent_answer, or retrieved_now into the question text
- Add "on a Davenport Model B" filler — that's implicit context

CRITICAL: HOW TO WRITE proposed_answer
The answer is where ALL the diagnosis and fix detail goes. Synthesize from:
- retrieved_now chunks (KB content the production agent should have found)
- agent_answer (preserve the partially-correct portions)
- user_notes (first-hand shop-floor experience — when the machinist says "I raised it up", that IS the fix)

Structure: brief problem framing -> common causes (most likely first) -> diagnostic steps -> fix. Use markdown. Cite sources with [source: blob_url] for chunks-derived content. Mark machinist-supplied detail with "(From operator experience)" so reviewers know that part is empirical, not from the manual.

Don't fabricate specs (numbers, part numbers, torque values, tolerances) that aren't in the evidence. If a key spec is missing, write `TKTK` or `[verify in manual]` so the human reviewer fills it in.

CONFIDENCE
Reflects how strongly the evidence supports your verdict AND the drafted answer. Be conservative:
- 0.85+: KB chunks + user notes + agent answer all align; you're paraphrasing not synthesizing
- 0.55-0.84: Coherent draft drawing on multiple sources, some interpretation
- <0.55: Weak signal; you're filling gaps the human reviewer should validate

OUTPUT: a single JSON object with this exact shape:
{
  "verdict": "gap" | "wrong" | "unclear_question" | "not_actionable",
  "confidence": 0.0,
  "reasoning": "1-2 sentences explaining your verdict to the human reviewer",
  "proposed_question": "...",
  "proposed_answer": "...",
  "proposed_citations": [{"blob_url": "...", "snippet_id": "..."}]
}

For verdict='not_actionable', proposed_question / proposed_answer / proposed_citations may be empty."""


def evaluate_feedback_row(row):
    """Run the evaluator on a single feedback row.

    row: an Azure Table entity dict (must have message, response, notes; may have rating).
    Returns a dict with the evaluator's verdict + drafted proposal + status to set.
    """
    question     = row.get("message", "")
    agent_answer = row.get("response", "")
    user_notes   = row.get("notes", "")

    retrieved = _bm25_search(question, top_k=10)
    retrieved_summary = [
        {"snippet": (r.get("snippet") or "")[:1500], "blob_url": r.get("blob_url", "")}
        for r in retrieved
    ]

    user_payload = {
        "question": question,
        "agent_answer": agent_answer,
        "user_notes": user_notes,
        "retrieved_now": retrieved_summary,
    }

    client = _get_openai_client()
    try:
        result = client.chat.completions.create(
            model=EVALUATOR_MODEL,
            messages=[
                {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=2000,
        )
        raw = result.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except Exception as e:
        logging.error(f"Evaluator call failed: {e}")
        return {
            "review_status": "error",
            "evaluator_verdict": "",
            "evaluator_confidence": 0.0,
            "evaluator_reasoning": f"Evaluator error: {str(e)[:200]}",
            "proposed_question": "",
            "proposed_answer": "",
            "proposed_citations": "[]",
        }

    verdict     = parsed.get("verdict", "not_actionable")
    if verdict not in VALID_VERDICTS:
        verdict = "not_actionable"
    confidence  = float(parsed.get("confidence", 0.0) or 0.0)
    reasoning   = (parsed.get("reasoning") or "")[:2000]
    proposed_q  = (parsed.get("proposed_question") or "")[:1000]
    proposed_a  = (parsed.get("proposed_answer") or "")[:16000]
    proposed_c  = parsed.get("proposed_citations") or []

    if verdict == "not_actionable":
        review_status = "not_actionable"
    elif confidence < LOW_CONFIDENCE_THRESHOLD:
        review_status = "deferred"
    else:
        review_status = "proposed"

    # Refuse identical-output trap (failure mode #1): if proposed_answer is the
    # agent's answer verbatim, the evaluator didn't actually fix anything.
    if proposed_a.strip() and proposed_a.strip() == agent_answer.strip():
        review_status = "deferred"
        reasoning = (reasoning + "\n[auto] Proposed answer was identical to agent answer; deferred for manual review.").strip()

    return {
        "review_status":         review_status,
        "evaluator_verdict":     verdict,
        "evaluator_confidence":  round(confidence, 3),
        "evaluator_reasoning":   reasoning,
        "proposed_question":     proposed_q,
        "proposed_answer":       proposed_a,
        "proposed_citations":    json.dumps(proposed_c)[:4000],
    }


def _select_candidates(max_rows):
    """Pull feedback rows that should be evaluated this run.

    Filter:
      - rating in (flagged, thumbs_down)
      - notes != ''
      - review_status is null/empty
      - PartitionKey >= today - LOOKBACK_DAYS
    """
    table = _get_table_client(FEEDBACK_TABLE)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    # Azure Tables can't natively filter on missing properties, so we filter post-fetch.
    query = (
        f"PartitionKey ge '{cutoff}' "
        f"and (rating eq 'flagged' or rating eq 'thumbs_down')"
    )
    rows = []
    for entity in table.query_entities(query_filter=query):
        if entity.get("review_status"):  # already processed
            continue
        if not (entity.get("notes") or "").strip():
            continue
        rows.append(entity)
        if len(rows) >= max_rows:
            break
    return rows


def run_evaluator_batch(max_rows=MAX_PROPOSALS_PER_RUN):
    """Pull candidates, evaluate each, MERGE results back onto feedback rows.

    Returns: {processed, by_status, errors}
    """
    table = _get_table_client(FEEDBACK_TABLE)
    candidates = _select_candidates(max_rows)
    summary = {"processed": 0, "by_status": {}, "errors": 0}

    if not candidates:
        logging.info("Evaluator: no candidates")
        return summary

    logging.info(f"Evaluator: processing {len(candidates)} candidates")

    from azure.data.tables import UpdateMode
    now = datetime.now(timezone.utc).isoformat()

    for row in candidates:
        try:
            verdict = evaluate_feedback_row(row)
            update = {
                "PartitionKey": row["PartitionKey"],
                "RowKey":       row["RowKey"],
                "evaluated_at": now,
                **verdict,
            }
            table.update_entity(update, mode=UpdateMode.MERGE)
            summary["processed"] += 1
            status = verdict["review_status"]
            summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
        except Exception as e:
            logging.error(f"Evaluator failed on {row.get('RowKey')}: {e}")
            summary["errors"] += 1

    logging.info(f"Evaluator done: {summary}")
    return summary


# ── Queue + edit helpers ──────────────────────────────────────────────────────
def list_curation_queue(status_filter=None):
    """Return curation rows for admin display.

    status_filter: 'proposed' | 'deferred' | 'not_actionable' | 'approved' | 'rejected' | 'all'
    Default 'proposed'. Pass 'all' to include everything.
    """
    if status_filter not in (None, "all", *VALID_REVIEW_STATUSES):
        raise ValueError(f"Invalid status filter: {status_filter}")

    table = _get_table_client(FEEDBACK_TABLE)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=60)).strftime("%Y-%m-%d")

    if status_filter and status_filter != "all":
        query = f"PartitionKey ge '{cutoff}' and review_status eq '{status_filter}'"
    else:
        # Show anything with a review_status set in the last 60 days
        query = f"PartitionKey ge '{cutoff}'"

    rows = []
    for entity in table.query_entities(query_filter=query):
        if status_filter is None and not entity.get("review_status"):
            continue  # skip un-evaluated rows when no filter — only curated lifecycle rows
        rows.append(_to_queue_dict(entity))

    # Sort: highest confidence first, then most recent
    rows.sort(key=lambda r: (
        -float(r.get("evaluator_confidence") or 0.0),
        r.get("date") or "",
    ), reverse=False)
    return rows


def _to_queue_dict(entity):
    """Shape a feedback table row for the curation queue API."""
    citations_raw = entity.get("proposed_citations") or "[]"
    try:
        citations = json.loads(citations_raw) if isinstance(citations_raw, str) else citations_raw
    except Exception:
        citations = []

    ts = None
    try:
        md = getattr(entity, "metadata", None) or {}
        t = md.get("timestamp") if isinstance(md, dict) else None
        if t is not None:
            ts = t.isoformat() if hasattr(t, "isoformat") else str(t)
    except Exception:
        ts = None

    return {
        "date":                  entity.get("PartitionKey"),
        "id":                    entity.get("RowKey"),
        "timestamp":             ts,
        # Raw history
        "message":               entity.get("message"),
        "response":              entity.get("response"),
        "notes":                 entity.get("notes"),
        "initials":              entity.get("initials"),
        "username":              entity.get("username"),
        "rating":                entity.get("rating"),
        "conversation_history":  entity.get("conversation_history", "[]"),
        # Evaluator output
        "review_status":         entity.get("review_status"),
        "evaluator_verdict":     entity.get("evaluator_verdict"),
        "evaluator_confidence":  entity.get("evaluator_confidence"),
        "evaluator_reasoning":   entity.get("evaluator_reasoning"),
        "proposed_question":     entity.get("proposed_question"),
        "proposed_answer":       entity.get("proposed_answer"),
        "proposed_citations":    citations,
        # Approval state
        "curated_chunk_id":      entity.get("curated_chunk_id"),
        "curated_blob_url":      entity.get("curated_blob_url"),
        "reviewed_by":           entity.get("reviewed_by"),
        "reviewed_at":           entity.get("reviewed_at"),
        "rejection_reason":      entity.get("rejection_reason"),
    }


def edit_proposal(pk, rk, edits):
    """Update editable fields on a proposed row (proposed_question, proposed_answer,
    proposed_citations). MERGE only — leaves review_status alone."""
    table = _get_table_client(FEEDBACK_TABLE)
    update = {"PartitionKey": pk, "RowKey": rk}
    if "proposed_question" in edits:
        update["proposed_question"] = (edits.get("proposed_question") or "")[:1000]
    if "proposed_answer" in edits:
        update["proposed_answer"] = (edits.get("proposed_answer") or "")[:16000]
    if "proposed_citations" in edits:
        cits = edits.get("proposed_citations") or []
        update["proposed_citations"] = json.dumps(cits)[:4000]
    if len(update) == 2:  # only PK+RK present
        return {"status": "noop"}
    from azure.data.tables import UpdateMode
    table.update_entity(update, mode=UpdateMode.MERGE)
    return {"status": "updated"}


# ── Approval pipeline ─────────────────────────────────────────────────────────
def _render_curated_markdown(curated_chunk_id, question, answer, citations,
                             approved_by, approved_at, source_pk, source_rk):
    """Build the markdown blob body for a curated Q&A entry."""
    front_matter = (
        "---\n"
        f"chunk_id: {curated_chunk_id}\n"
        "source_type: curated\n"
        "category: user-curated\n"
        f"approved_by: {approved_by}\n"
        f"approved_at: {approved_at}\n"
        f"source_feedback_pk: {source_pk}\n"
        f"source_feedback_rk: {source_rk}\n"
        "---\n\n"
    )
    body = f"# Q: {question.strip()}\n\n{answer.strip()}\n"
    if citations:
        sources_lines = []
        for c in citations:
            url = c.get("blob_url") if isinstance(c, dict) else None
            if url:
                sources_lines.append(f"- [source: {url}]")
        if sources_lines:
            body += "\n## Sources\n" + "\n".join(sources_lines) + "\n"
    return front_matter + body


def approve_proposal(pk, rk, edited_payload, admin_user):
    """Approve a proposal. Writes blob + ledger row + MERGEs feedback row.

    edited_payload may include: proposed_question, proposed_answer, proposed_citations
    (these override what's currently on the row, allowing inline edits at approve time).

    Returns: {status, curated_chunk_id, curated_blob_url}
    """
    fb_table = _get_table_client(FEEDBACK_TABLE)

    # Read current state
    try:
        row = fb_table.get_entity(partition_key=pk, row_key=rk)
    except Exception as e:
        return {"status": "error", "error": f"Feedback row not found: {e}"}

    if row.get("review_status") not in ("proposed", "deferred"):
        return {"status": "error", "error": f"Cannot approve from review_status='{row.get('review_status')}'"}

    # Apply inline edits if provided
    question = (edited_payload.get("proposed_question") or row.get("proposed_question") or "").strip()
    answer   = (edited_payload.get("proposed_answer")   or row.get("proposed_answer")   or "").strip()
    citations_raw = edited_payload.get("proposed_citations")
    if citations_raw is None:
        citations_raw = row.get("proposed_citations") or "[]"
    if isinstance(citations_raw, str):
        try:
            citations = json.loads(citations_raw)
        except Exception:
            citations = []
    else:
        citations = citations_raw or []

    if not question or not answer:
        return {"status": "error", "error": "proposed_question and proposed_answer are required"}

    now = datetime.now(timezone.utc)
    approved_at = now.isoformat()
    yyyy = now.strftime("%Y")
    mm   = now.strftime("%m")
    yyyymm = now.strftime("%Y-%m")

    curated_chunk_id = f"curated-{uuid.uuid4().hex[:8]}"
    blob_path = f"{yyyy}/{mm}/{curated_chunk_id}.md"
    blob_url  = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CURATED_CONTAINER}/{blob_path}"

    markdown = _render_curated_markdown(
        curated_chunk_id, question, answer, citations,
        approved_by=admin_user,
        approved_at=approved_at,
        source_pk=pk,
        source_rk=rk,
    )

    # 1. Write blob (abort cleanly on failure — no partial state)
    try:
        blob_service = _get_blob_service()
        container = blob_service.get_container_client(CURATED_CONTAINER)
        container.upload_blob(name=blob_path, data=markdown.encode("utf-8"), overwrite=False)
    except Exception as e:
        logging.error(f"approve_proposal: blob write failed for {curated_chunk_id}: {e}")
        return {"status": "error", "error": f"Blob write failed: {str(e)[:200]}"}

    # 2. Insert ledger row (best-effort retry once)
    ledger_row = {
        "PartitionKey":          yyyymm,
        "RowKey":                curated_chunk_id,
        "proposed_question":     question[:1000],
        "proposed_answer":       answer[:32000],
        "source_feedback_pk":    pk,
        "source_feedback_rk":    rk,
        "blob_url":              blob_url,
        "approved_by":           admin_user,
        "approved_at":           approved_at,
        "active":                True,
    }
    led_table = _get_table_client(CURATED_TABLE)
    try:
        led_table.create_entity(ledger_row)
    except Exception as e:
        # Blob already written; surface to admin so they can retry. The blob is
        # idempotent because we used overwrite=False — if they retry, blob write
        # will fail (good — prevents duplicates) and they'll need ledger insert
        # via a separate path. V1.5 reconciliation job will surface mismatches.
        logging.error(f"approve_proposal: ledger insert failed for {curated_chunk_id}: {e}")
        return {
            "status": "partial",
            "error": f"Blob written but ledger insert failed: {str(e)[:200]}",
            "curated_chunk_id": curated_chunk_id,
            "curated_blob_url": blob_url,
        }

    # 3. MERGE feedback row
    from azure.data.tables import UpdateMode
    update = {
        "PartitionKey":          pk,
        "RowKey":                rk,
        "review_status":         "approved",
        "curated_chunk_id":      curated_chunk_id,
        "curated_blob_url":      blob_url,
        "reviewed_by":           admin_user,
        "reviewed_at":           approved_at,
        "proposed_question":     question[:1000],
        "proposed_answer":       answer[:16000],
        "proposed_citations":    json.dumps(citations)[:4000],
    }
    try:
        fb_table.update_entity(update, mode=UpdateMode.MERGE)
    except Exception as e:
        logging.error(f"approve_proposal: feedback merge failed for {pk}/{rk}: {e}")
        return {
            "status": "partial",
            "error": f"Blob+ledger written but feedback merge failed: {str(e)[:200]}",
            "curated_chunk_id": curated_chunk_id,
            "curated_blob_url": blob_url,
        }

    logging.info(f"Approved proposal {pk}/{rk} -> {curated_chunk_id}")
    return {
        "status":             "approved",
        "curated_chunk_id":   curated_chunk_id,
        "curated_blob_url":   blob_url,
    }


def reject_proposal(pk, rk, reason, admin_user):
    """Mark a proposal rejected with a 1-line reason."""
    if not (reason or "").strip():
        return {"status": "error", "error": "rejection_reason is required"}

    table = _get_table_client(FEEDBACK_TABLE)
    from azure.data.tables import UpdateMode
    table.update_entity(
        {
            "PartitionKey":     pk,
            "RowKey":           rk,
            "review_status":    "rejected",
            "rejection_reason": reason.strip()[:500],
            "reviewed_by":      admin_user,
            "reviewed_at":      datetime.now(timezone.utc).isoformat(),
        },
        mode=UpdateMode.MERGE,
    )
    return {"status": "rejected"}


def defer_proposal(pk, rk, admin_user):
    """Send a proposal back to the deferred queue (no commitment yet)."""
    table = _get_table_client(FEEDBACK_TABLE)
    from azure.data.tables import UpdateMode
    table.update_entity(
        {
            "PartitionKey":  pk,
            "RowKey":        rk,
            "review_status": "deferred",
            "reviewed_by":   admin_user,
            "reviewed_at":   datetime.now(timezone.utc).isoformat(),
        },
        mode=UpdateMode.MERGE,
    )
    return {"status": "deferred"}


# ── Validators (used by function_app.py route handlers) ───────────────────────
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_pk_rk(pk, rk):
    """Return None if valid, else an error string (mirrors update_feedback's checks)."""
    if not DATE_RE.match(pk or ""):
        return "Invalid partition_key"
    if not rk or len(rk) > 200:
        return "Invalid row_key"
    return None
