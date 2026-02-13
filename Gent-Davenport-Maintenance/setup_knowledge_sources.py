"""
Fix Knowledge Source indexing by updating the auto-generated data source connection.

The knowledge sources were created via Foundry portal but their blob data source
connections are broken (indexers show 0/0 docs). This script fixes the data source
to use managed identity auth, then resets and runs the indexer.

The knowledge source API won't let us change connection strings, so we go directly
to the auto-generated data source and update it there.

Uses managed identity auth - the search service's system-assigned identity authenticates
to blob storage. No access keys needed.

PREREQUISITE: Search service managed identity must have 'Storage Blob Data Reader' role
on the storage account. Verify in Azure Portal:
  Storage Account > Access Control (IAM) > Role assignments > Storage Blob Data Reader
  Should show: srch-j6lw7vswhnnhw (Search Service)

Usage:
  python setup_knowledge_sources.py
"""

import time
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexerClient

# Azure resource configuration - matches existing scripts
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"

# Managed identity connection string - tells AI Search to use its managed identity
# instead of access keys to read from blob storage
STORAGE_RESOURCE_ID = (
    "ResourceId=/subscriptions/09d43e37-e7dc-4869-9db4-768d8937df2e"
    "/resourceGroups/rg-gent-foundry-eus2"
    "/providers/Microsoft.Storage/storageAccounts/stj6lw7vswhnnhw;"
)

# Knowledge sources to fix - starting with maintenance-manuals
# Each entry maps to auto-generated resources: {name}-datasource, {name}-indexer
# Add more entries here when ready to fix the other 4
KNOWLEDGE_SOURCES_TO_FIX = [
    "ks-azureblob-maintenance-manuals",
    # Uncomment these when ready to fix the other knowledge sources:
    # "ks-azureblob-engineering-tips",
    # "ks-azureblob-technical-tips",
    # "ks-azureblob-troubleshooting",
    # "ks-azureblob-video-training",
]


def fix_knowledge_source(indexer_client, ks_name):
    """Fix a knowledge source by updating its data source connection and re-running the indexer."""
    datasource_name = f"{ks_name}-datasource"
    indexer_name = f"{ks_name}-indexer"

    # Step 1: Get the existing data source and update its connection string
    print(f"\n  Updating data source '{datasource_name}'...")
    data_source = indexer_client.get_data_source_connection(datasource_name)

    # Show what we're changing from
    old_conn = data_source.connection_string or "(empty/missing)"
    if "AccountKey" in old_conn:
        old_conn = "(access key - redacted)"
    print(f"    Old connection: {old_conn}")
    print(f"    New connection: managed identity (ResourceId)")

    # Update to managed identity connection
    data_source.connection_string = STORAGE_RESOURCE_ID
    indexer_client.create_or_update_data_source_connection(data_source)
    print(f"  [OK] Data source updated to managed identity auth")

    # Step 2: Reset the indexer so it re-processes all blobs from scratch
    # Without reset, it thinks it already attempted these blobs and skips them
    print(f"\n  Resetting indexer '{indexer_name}'...")
    indexer_client.reset_indexer(indexer_name)
    print(f"  [OK] Indexer reset - will re-process all blobs")

    # Step 3: Run the indexer
    print(f"\n  Running indexer '{indexer_name}'...")
    indexer_client.run_indexer(indexer_name)
    print(f"  [OK] Indexer started")

    # Step 4: Wait briefly and check status
    print(f"\n  Waiting 15 seconds for initial results...")
    time.sleep(15)

    status = indexer_client.get_indexer_status(indexer_name)
    if status.last_result:
        result = status.last_result
        print(f"  Status: {result.status}")
        print(f"  Items processed: {result.item_count}")
        print(f"  Items failed: {result.failed_item_count}")

        if result.errors:
            print(f"\n  ERRORS:")
            for error in result.errors[:5]:
                print(f"    - {error.message}")
        if result.warnings:
            print(f"\n  WARNINGS:")
            for warning in result.warnings[:5]:
                print(f"    - {warning.message}")
    else:
        print(f"  (Still running - check portal for results)")


def main():
    print("=" * 60)
    print("Fix Knowledge Source Data Source Connections")
    print("=" * 60)

    # Prerequisite reminder
    print("\nPREREQUISITE CHECK:")
    print("  Search service 'srch-j6lw7vswhnnhw' managed identity must have")
    print("  'Storage Blob Data Reader' role on storage account 'stj6lw7vswhnnhw'")
    print("  (Azure Portal > Storage Account > Access Control (IAM))")
    print()

    credential = DefaultAzureCredential()
    indexer_client = SearchIndexerClient(
        endpoint=SEARCH_ENDPOINT,
        credential=credential,
    )

    print(f"Fixing {len(KNOWLEDGE_SOURCES_TO_FIX)} knowledge source(s)...")

    for ks_name in KNOWLEDGE_SOURCES_TO_FIX:
        fix_knowledge_source(indexer_client, ks_name)

    print("\n" + "=" * 60)
    print("DONE! Next steps:")
    print("  1. Check Azure Portal > AI Search > Indexers for document counts")
    print("     Large PDFs may take a few minutes to process")
    print("  2. If indexer shows 0 docs, verify the RBAC role assignment above")
    print("  3. Upload new documents to blob containers as needed")
    print("  4. Test the agent with a maintenance manual question")
    print("=" * 60)


if __name__ == "__main__":
    main()
