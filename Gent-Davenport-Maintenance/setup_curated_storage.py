"""
One-time setup for the curation feedback loop.

Creates:
  - Blob container `curated-qa` in storage account stj6lw7vswhnnhw — durable
    source-of-truth for human-approved Q&A markdown files.
  - Azure Table `curatedqa` in the same account — audit ledger:
    PartitionKey=yyyy-mm, RowKey=curated_chunk_id, with active flag.

Idempotent — safe to re-run. Existing resources are left untouched.

Run: python setup_curated_storage.py

Auth: DefaultAzureCredential (uses your active az login).
"""

import os
from azure.identity import DefaultAzureCredential
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient

STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT", "stj6lw7vswhnnhw")

CURATED_CONTAINER = "curated-qa"
CURATED_TABLE = "curatedqa"  # Azure Table names must be alphanumeric (no underscores/hyphens)


def main():
    credential = DefaultAzureCredential()

    blob_endpoint = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
    table_endpoint = f"https://{STORAGE_ACCOUNT}.table.core.windows.net"

    print("=" * 60)
    print(f"Provisioning curation storage in {STORAGE_ACCOUNT}")
    print("=" * 60)

    # Blob container
    blob_service = BlobServiceClient(account_url=blob_endpoint, credential=credential)
    container = blob_service.get_container_client(CURATED_CONTAINER)
    if container.exists():
        print(f"  Blob container '{CURATED_CONTAINER}' already exists")
    else:
        container.create_container()
        print(f"  Created blob container '{CURATED_CONTAINER}'")

    # Azure Table
    table_service = TableServiceClient(endpoint=table_endpoint, credential=credential)
    table_service.create_table_if_not_exists(CURATED_TABLE)
    print(f"  Table '{CURATED_TABLE}' ready")

    print()
    print("Next steps:")
    print("  1. Deploy the Function App with the new curation endpoints")
    print(f"     The 'feedback' table will gain new fields (review_status, evaluator_*, ...)")
    print(f"     via MERGE — no migration required (Azure Tables is schemaless per row).")
    print("  2. Run the evaluator: POST /api/curation/run-evaluator")
    print("  3. Open the admin UI 'Curation Queue' tab to review proposals")


if __name__ == "__main__":
    main()
