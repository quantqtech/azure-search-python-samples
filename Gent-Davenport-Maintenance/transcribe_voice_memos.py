"""
Batch transcription of voice memos from blob storage.

Voice memos are recorded in the browser and saved to:
  knowledge-gaps/voice-memos/YYYY-MM-DD/HHMMSS_initials_convid.webm

This script:
1. Lists all .webm files in knowledge-gaps/voice-memos/
2. Transcribes each using Azure AI Speech (fast transcription REST API)
3. Saves the transcript as a .md file in knowledge-gaps/ for indexing
4. The scheduled knowledge-gaps indexer picks it up automatically

Run this manually or on a schedule after reviewing flagged sessions with Dave.

Requirements:
  pip install azure-storage-blob azure-identity requests

Usage:
  python transcribe_voice_memos.py
  python transcribe_voice_memos.py --date 2026-02-26   # only that date's memos
  python transcribe_voice_memos.py --dry-run           # list files without transcribing
"""

import argparse
import json
import logging
import os
import sys
import time
import requests
from datetime import datetime, timezone
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Azure resources
STORAGE_ACCOUNT   = "stj6lw7vswhnnhw"
KB_CONTAINER      = "knowledge-gaps"
VOICE_MEMO_PREFIX = "voice-memos/"

# Azure AI Speech — requires SPEECH_KEY and SPEECH_REGION in .env
# Get these from: Azure portal → AI Services (Speech) resource → Keys and Endpoint
SPEECH_KEY    = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION", "eastus2")

# Fast Transcription REST endpoint
SPEECH_FAST_API = (
    f"https://{SPEECH_REGION}.api.cognitive.microsoft.com"
    f"/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
)


def get_blob_client():
    credential = DefaultAzureCredential()
    return BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential
    )


def list_voice_memos(blob_service, date_filter=None):
    """List .webm files in the voice-memos/ prefix, optionally filtered by date."""
    container = blob_service.get_container_client(KB_CONTAINER)
    prefix = VOICE_MEMO_PREFIX
    if date_filter:
        prefix = f"{VOICE_MEMO_PREFIX}{date_filter}/"

    blobs = [
        b for b in container.list_blobs(name_starts_with=prefix)
        if b.name.endswith(".webm")
    ]
    log.info(f"Found {len(blobs)} voice memo(s) under '{prefix}'")
    return blobs


def already_transcribed(blob_service, webm_name):
    """Check if a .md transcript already exists for this voice memo."""
    md_name = webm_name.replace(VOICE_MEMO_PREFIX, "transcripts/").replace(".webm", ".md")
    container = blob_service.get_container_client(KB_CONTAINER)
    try:
        container.get_blob_client(md_name).get_blob_properties()
        return True
    except Exception:
        return False


def download_audio(blob_service, blob_name):
    """Download audio bytes from blob storage."""
    container = blob_service.get_container_client(KB_CONTAINER)
    blob_client = container.get_blob_client(blob_name)
    return blob_client.download_blob().readall()


def transcribe_audio(audio_bytes, filename):
    """
    Transcribe audio using Azure AI Speech Fast Transcription REST API.
    Returns the transcript text, or None on failure.

    Fast Transcription is a synchronous REST call — no polling needed.
    Docs: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/fast-transcription-create
    """
    if not SPEECH_KEY:
        log.error("SPEECH_KEY not set in .env — cannot transcribe")
        return None

    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Accept": "application/json",
    }

    # Multipart form: audio file + JSON definition
    definition = json.dumps({
        "locales": ["en-US"],
        "profanityFilterMode": "None",
        "channels": [0],  # mono
    })

    files = {
        "audio": (filename, audio_bytes, "audio/webm"),
        "definition": (None, definition, "application/json"),
    }

    log.info(f"Transcribing {filename} ({len(audio_bytes)} bytes)...")
    t0 = time.time()

    try:
        resp = requests.post(SPEECH_FAST_API, headers=headers, files=files, timeout=120)
        resp.raise_for_status()
        result = resp.json()

        # Extract combined transcript from all phrases
        phrases = result.get("combinedPhrases", [])
        if phrases:
            text = " ".join(p.get("text", "") for p in phrases).strip()
        else:
            # Fallback: try individual phrases
            text = " ".join(
                p.get("text", "")
                for p in result.get("phrases", [])
            ).strip()

        elapsed = round(time.time() - t0, 1)
        log.info(f"Transcribed in {elapsed}s: '{text[:80]}...' ({len(text)} chars)")
        return text if text else None

    except requests.HTTPError as e:
        log.error(f"Speech API error {e.response.status_code}: {e.response.text[:300]}")
        return None
    except Exception as e:
        log.error(f"Transcription failed: {e}")
        return None


def save_transcript(blob_service, webm_name, transcript_text, blob_metadata):
    """
    Save transcript as a Markdown file in the knowledge-gaps container.

    The indexer will pick this up and add it to the knowledge base.
    File goes in: knowledge-gaps/transcripts/YYYY-MM-DD/filename.md
    """
    md_name = webm_name.replace(VOICE_MEMO_PREFIX, "transcripts/").replace(".webm", ".md")

    # Build a markdown doc that gives context for the knowledge base
    timestamp = blob_metadata.get("last_modified", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    initials = extract_initials_from_blob_name(webm_name)

    content = f"""# Voice Memo Transcript

**Date**: {timestamp}
**Submitted by**: {initials or 'unknown'}
**Source file**: {webm_name}
**Type**: Technician voice note — knowledge gap or correction

---

{transcript_text}

---

*This transcript was recorded by a Gent Machine technician and added to the knowledge base.*
*It may describe a scenario, repair, or tip not yet documented in the official manuals.*
"""

    container = blob_service.get_container_client(KB_CONTAINER)
    container.get_blob_client(md_name).upload_blob(content.encode("utf-8"), overwrite=True)
    log.info(f"Saved transcript: {md_name}")
    return md_name


def extract_initials_from_blob_name(blob_name):
    """Extract initials from blob filename pattern: HHMMSS_initials_convid.webm"""
    try:
        filename = blob_name.rsplit("/", 1)[-1].replace(".webm", "")
        parts = filename.split("_")
        if len(parts) >= 2:
            return parts[1].upper()
    except Exception:
        pass
    return ""


def main():
    parser = argparse.ArgumentParser(description="Transcribe Davenport voice memos to text")
    parser.add_argument("--date", help="Only process memos from this date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="List files without transcribing")
    args = parser.parse_args()

    if not args.dry_run and not SPEECH_KEY:
        log.error("SPEECH_KEY is not set in .env")
        log.error("Add SPEECH_KEY=<your-key> and SPEECH_REGION=eastus2 to your .env file")
        log.error("Get the key from: Azure portal → AI Services resource → Keys and Endpoint")
        sys.exit(1)

    blob_service = get_blob_client()
    blobs = list_voice_memos(blob_service, date_filter=args.date)

    if not blobs:
        log.info("No voice memos to process.")
        return

    if args.dry_run:
        log.info("--- DRY RUN: files that would be transcribed ---")
        for b in blobs:
            already = already_transcribed(blob_service, b.name)
            log.info(f"  {'[SKIP - exists]' if already else '[PENDING]'} {b.name}")
        return

    processed = 0
    skipped = 0
    failed = 0

    for blob in blobs:
        if already_transcribed(blob_service, blob.name):
            log.info(f"[SKIP] Already transcribed: {blob.name}")
            skipped += 1
            continue

        # Download audio
        audio = download_audio(blob_service, blob.name)

        # Transcribe
        filename = blob.name.rsplit("/", 1)[-1]
        transcript = transcribe_audio(audio, filename)

        if not transcript:
            log.warning(f"[FAIL] Could not transcribe: {blob.name}")
            failed += 1
            continue

        # Save transcript markdown
        save_transcript(blob_service, blob.name, transcript, {"last_modified": blob.last_modified})
        processed += 1

    log.info(f"\nDone: {processed} transcribed, {skipped} skipped, {failed} failed")
    if processed > 0:
        log.info("Transcripts saved to knowledge-gaps/transcripts/")
        log.info("The knowledge-gaps indexer will pick them up within 30 minutes.")


if __name__ == "__main__":
    main()
