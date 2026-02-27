"""
Direct MCP endpoint latency test.

Bypasses Foundry entirely and calls the Azure AI Search MCP endpoint directly.
This tells us whether the 43s in the Foundry trace is:
  - In the MCP endpoint itself (search side)
  - In Foundry's agent runtime wrapping it (orchestration overhead)

Run:  python test_mcp_latency.py
"""
import subprocess
import json
import time
import urllib.request

# ── Auth ────────────────────────────────────────────────────────────────────
# The MCP knowledge-base endpoint authenticates with the same Azure AI token
result = subprocess.run(
    ["az.cmd", "account", "get-access-token",
     "--resource", "https://search.azure.com",
     "--query", "accessToken", "-o", "tsv"],
    capture_output=True, text=True, shell=True
)
token = result.stdout.strip()
if not token:
    # Fallback: try the AI resource token (used by Foundry)
    result = subprocess.run(
        ["az.cmd", "account", "get-access-token",
         "--resource", "https://ai.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True
    )
    token = result.stdout.strip()

print(f"Token obtained: {token[:20]}...\n")

# ── MCP endpoint (same URL the Foundry agent uses) ───────────────────────────
MCP_BASE = (
    "https://srch-j6lw7vswhnnhw.search.windows.net"
    "/knowledgebases/davenport-machine-kb/mcp"
    "?api-version=2025-11-01-Preview"
)

QUERY = "How do I adjust the brake on a Davenport Model B?"

# ── Test 1: MCP initialize (tool discovery) ──────────────────────────────────
# The MCP protocol starts with an initialize handshake, then tools/list
# This is the mcp_list_tools step we see in Foundry traces

def mcp_post(path_suffix, payload):
    """POST to the MCP endpoint and return (response_dict, elapsed_seconds)."""
    url = MCP_BASE + (f"&{path_suffix}" if path_suffix else "")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            elapsed = time.perf_counter() - t0
            # MCP responses may be SSE (text/event-stream) or plain JSON
            content_type = resp.headers.get("Content-Type", "")
            if "event-stream" in content_type:
                # Parse SSE — extract data lines
                text = raw.decode("utf-8")
                data_lines = [
                    line[6:] for line in text.splitlines()
                    if line.startswith("data: ")
                ]
                parsed = [json.loads(d) for d in data_lines if d.strip()]
                return parsed, elapsed
            else:
                return json.loads(raw), elapsed
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {"error": str(e)}, elapsed


# ── Run the same query 3 times (matches the cold-start test) ─────────────────
print("=" * 60)
print(f"Query: {QUERY}")
print("=" * 60)

# MCP protocol: initialize → tools/list → tools/call
# We're testing tools/call (knowledge_base_retrieve) which is the slow step

for run in range(1, 4):
    print(f"\n-- Run {run} ----------------------------------------------------")

    # Step A: initialize
    t_init_start = time.perf_counter()
    init_payload = {
        "jsonrpc": "2.0",
        "id": run * 10,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "latency-test", "version": "1.0"}
        }
    }
    init_resp, init_elapsed = mcp_post("", init_payload)
    print(f"  initialize:      {init_elapsed:.2f}s  =>  {str(init_resp)[:80]}")

    # Step B: tools/list
    list_payload = {
        "jsonrpc": "2.0",
        "id": run * 10 + 1,
        "method": "tools/list",
        "params": {}
    }
    list_resp, list_elapsed = mcp_post("", list_payload)
    print(f"  tools/list:      {list_elapsed:.2f}s  =>  {str(list_resp)[:80]}")

    # Step C: tools/call  ← this is the 43s step
    call_payload = {
        "jsonrpc": "2.0",
        "id": run * 10 + 2,
        "method": "tools/call",
        "params": {
            "name": "knowledge_base_retrieve",
            "arguments": {"query": QUERY}
        }
    }
    call_resp, call_elapsed = mcp_post("", call_payload)

    # How much content came back?
    resp_str = str(call_resp)
    content_size = len(resp_str)
    print(f"  tools/call:      {call_elapsed:.2f}s  =>  {content_size:,} chars returned")
    if isinstance(call_resp, list):
        print(f"  (SSE events: {len(call_resp)})")
    elif isinstance(call_resp, dict) and "error" in call_resp:
        print(f"  ERROR: {call_resp['error']}")

    total = init_elapsed + list_elapsed + call_elapsed
    print(f"  -- Total MCP:    {total:.2f}s")

print("\n" + "=" * 60)
print("INTERPRETATION:")
print("  If tools/call ~= 43s  => bottleneck IS the MCP endpoint (search side)")
print("  If tools/call ~= 1-2s => bottleneck is Foundry agent runtime overhead")
print("=" * 60)
