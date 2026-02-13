"""
Split oversized PDFs in blob storage so they can be indexed by Azure AI Search.

Azure AI Search has a 16 MB (16,777,216 bytes) content extraction limit per blob.
This script downloads PDFs that exceed the limit, splits them by page ranges,
uploads the parts back, and deletes the originals.

After running this, reset and run the indexer to pick up the new smaller files.

Usage:
  python split_oversized_pdfs.py
"""

import os
import tempfile
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from pypdf import PdfReader, PdfWriter

# Azure AI Search content extraction limit (16 MB)
MAX_BLOB_SIZE = 16_777_216

# Storage account configuration
STORAGE_ACCOUNT_URL = "https://stj6lw7vswhnnhw.blob.core.windows.net"
CONTAINER_NAME = "maintenance-manuals"


def split_pdf(input_path, output_dir, base_name, target_size_mb=14):
    """Split a PDF into parts that stay under the target size.

    Strategy: estimate pages per chunk based on average page size,
    then write chunks and verify they're under the limit.
    """
    reader = PdfReader(input_path)
    total_pages = len(reader.pages)
    file_size = os.path.getsize(input_path)

    # Estimate pages per chunk (aim for 14 MB to leave margin under 16 MB limit)
    avg_page_size = file_size / total_pages
    pages_per_chunk = max(1, int((target_size_mb * 1024 * 1024) / avg_page_size))

    print(f"    Total pages: {total_pages}")
    print(f"    Avg page size: {avg_page_size / 1024:.0f} KB")
    print(f"    Target pages per chunk: {pages_per_chunk}")

    parts = []
    start_page = 0
    part_num = 1

    while start_page < total_pages:
        end_page = min(start_page + pages_per_chunk, total_pages)

        # Write this chunk to a file
        writer = PdfWriter()
        for page_num in range(start_page, end_page):
            writer.add_page(reader.pages[page_num])

        # Name format: "Original Name - Part 1 of 6.pdf"
        total_parts = -(-total_pages // pages_per_chunk)  # ceiling division
        part_filename = f"{base_name} - Part {part_num} of {total_parts}.pdf"
        part_path = os.path.join(output_dir, part_filename)

        writer.write(part_path)
        part_size = os.path.getsize(part_path)

        # If still over limit, reduce pages and retry this chunk
        if part_size > MAX_BLOB_SIZE and (end_page - start_page) > 1:
            os.remove(part_path)
            # Halve the pages for this chunk and retry
            pages_per_chunk = max(1, (end_page - start_page) // 2)
            print(f"    Part {part_num} too large ({part_size / 1024 / 1024:.1f} MB), retrying with {pages_per_chunk} pages")
            continue

        print(f"    Part {part_num}: pages {start_page + 1}-{end_page} ({part_size / 1024 / 1024:.1f} MB)")
        parts.append((part_filename, part_path))

        start_page = end_page
        part_num += 1

    return parts


def main():
    print("=" * 60)
    print("Split Oversized PDFs in Blob Storage")
    print(f"Max size for indexing: {MAX_BLOB_SIZE / 1024 / 1024:.0f} MB")
    print("=" * 60)

    credential = DefaultAzureCredential()
    blob_service = BlobServiceClient(
        account_url=STORAGE_ACCOUNT_URL,
        credential=credential,
    )
    container_client = blob_service.get_container_client(CONTAINER_NAME)

    # Find oversized blobs
    print(f"\nScanning container '{CONTAINER_NAME}'...")
    oversized = []
    ok_count = 0

    for blob in container_client.list_blobs():
        if blob.size > MAX_BLOB_SIZE:
            oversized.append(blob)
            print(f"  [OVERSIZED] {blob.name} ({blob.size / 1024 / 1024:.1f} MB)")
        else:
            ok_count += 1

    print(f"\n  {ok_count} blobs OK, {len(oversized)} oversized")

    if not oversized:
        print("\nNo oversized blobs found. Nothing to do.")
        return

    # Process each oversized blob
    with tempfile.TemporaryDirectory() as tmp_dir:
        for blob in oversized:
            print(f"\n{'-' * 50}")
            print(f"  Processing: {blob.name} ({blob.size / 1024 / 1024:.1f} MB)")

            # Download the blob
            download_path = os.path.join(tmp_dir, blob.name)
            print(f"  Downloading...")
            blob_client = container_client.get_blob_client(blob.name)
            with open(download_path, "wb") as f:
                stream = blob_client.download_blob()
                stream.readinto(f)

            # Split the PDF - strip .pdf extension for the base name
            base_name = blob.name.rsplit(".", 1)[0]
            parts = split_pdf(download_path, tmp_dir, base_name)

            # Upload the parts
            print(f"\n  Uploading {len(parts)} parts...")
            for part_filename, part_path in parts:
                part_blob = container_client.get_blob_client(part_filename)
                with open(part_path, "rb") as f:
                    part_blob.upload_blob(f, overwrite=True)
                print(f"    [OK] {part_filename}")

            # Delete the original oversized blob
            print(f"\n  Deleting original: {blob.name}")
            blob_client.delete_blob()
            print(f"  [OK] Deleted")

    print(f"\n{'=' * 60}")
    print("DONE! All oversized PDFs have been split and re-uploaded.")
    print("\nNext: Reset and run the indexer to pick up the new files:")
    print("  python setup_knowledge_sources.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
