"""
Test script: Benchmark graph classifier + overall response timing.
  Phase 1: 20 independent questions (new conversation each) — isolates graph classifier
  Phase 2: 3 multi-turn conversations (4 turns each) — tests follow-up context resolution
"""
import requests
import json
import time
import sys
import statistics

API_BASE = "https://func-davenport-api.azurewebsites.net/api"

# Phase 1: 5 independent questions that should trigger graph classification
INDEPENDENT_QUESTIONS = [
    "How do I adjust the stock reel tension?",
    "My part is coming out short, what should I check?",
    "The cross slide is not advancing properly",
    "I'm getting a burr on the cutoff",
    "The spindle bearings are making noise",
]

# Phase 2: 2 multi-turn conversations — follow-ups that build on prior context
MULTI_TURN_CONVERSATIONS = [
    {
        "name": "Short part diagnosis",
        "turns": [
            "My parts are coming out short",
            "I already checked the cutoff tool, it looks fine",
            "Could it be the stock not feeding far enough?",
            "What about the collet — how tight should it be?",
        ],
    },
    {
        "name": "Spindle noise troubleshooting",
        "turns": [
            "I'm hearing a grinding noise from the headstock area",
            "It gets worse at higher speeds",
            "When was the last time I should have changed the bearings?",
            "What oil viscosity do the bearings need?",
        ],
    },
]


def login():
    """Get an auth token."""
    resp = requests.post(f"{API_BASE}/auth/login", json={
        "username": "testeragent",
        "password": "gent2026"
    })
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    return resp.json()["token"]


def send_question(token, question, conversation_id=None, turn_number=1, recent_messages=None):
    """Send a question via streaming API, parse SSE events, return timing + conversation state."""
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "message": question,
        "conversation_id": conversation_id,
        "reasoning_level": "direct",
        "turn_number": turn_number,
        "recent_messages": recent_messages or [],
    }

    t_start = time.time()
    resp = requests.post(
        f"{API_BASE}/chat/stream",
        json=body,
        headers=headers,
        stream=True,
        timeout=180,
    )

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "question": question}

    # Parse SSE events — timing lives in the 'done' event's trace.timings
    result = {"question": question, "turn_number": turn_number}
    conv_id = conversation_id
    response_text = ""

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])

            if data.get("type") == "session":
                conv_id = data.get("conversation_id", conv_id)

            elif data.get("type") == "done":
                trace = data.get("trace", {})
                timings = trace.get("timings", {})
                result["graph_ms"] = timings.get("graph_context", 0)
                result["agent_ms"] = timings.get("agent_response", 0)
                result["citations_ms"] = timings.get("citations", 0)
                result["total_ms"] = timings.get("total", 0)
                result["graph_ids"] = trace.get("graph_starting_ids", [])
                result["graph_used"] = trace.get("graph_context_used", False)
                response_text = data.get("full_text", "")[:200]

        except json.JSONDecodeError:
            continue

    wall_time = round((time.time() - t_start) * 1000)
    result["wall_ms"] = wall_time
    result["conversation_id"] = conv_id
    result["response_preview"] = response_text
    return result


def print_stats(label, values_ms):
    """Print statistics for a list of millisecond values."""
    if not values_ms:
        print(f"  {label}: no data")
        return
    values_s = [v / 1000 for v in values_ms]
    print(f"  {label} (n={len(values_s)}):")
    print(f"    Mean:   {statistics.mean(values_s):.1f}s")
    print(f"    Median: {statistics.median(values_s):.1f}s")
    print(f"    Min:    {min(values_s):.1f}s")
    print(f"    Max:    {max(values_s):.1f}s")
    if len(values_s) > 1:
        print(f"    StdDev: {statistics.stdev(values_s):.1f}s")


def run_phase1(token):
    """Phase 1: 20 independent questions, new conversation each."""
    print("=" * 80)
    n = len(INDEPENDENT_QUESTIONS)
    print(f"PHASE 1: Independent Questions ({n} new conversations)")
    print("=" * 80)

    results = []
    for i, q in enumerate(INDEPENDENT_QUESTIONS):
        print(f"  [{i+1:2d}/{n}] {q[:55]:<55}", end="", flush=True)
        try:
            r = send_question(token, q)
            results.append(r)
            if "error" in r:
                print(f"  ERROR: {r['error']}")
            else:
                g = r.get("graph_ms", 0)
                a = r.get("agent_ms", 0)
                t = r.get("total_ms", 0) or r.get("wall_ms", 0)
                ids = r.get("graph_ids", [])
                print(f"  g={g/1000:5.1f}s  a={a/1000:5.1f}s  t={t/1000:5.1f}s  nodes={ids}")
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            results.append({"error": str(e), "question": q})

    return results


def run_phase2(token):
    """Phase 2: Multi-turn conversations that build on each other."""
    print("\n" + "=" * 80)
    print(f"PHASE 2: Multi-Turn Conversations ({len(MULTI_TURN_CONVERSATIONS)} conversations x 4 turns)")
    print("=" * 80)

    all_results = []
    for conv in MULTI_TURN_CONVERSATIONS:
        print(f"\n  --- {conv['name']} ---")
        conv_id = None
        recent = []

        for turn_num, question in enumerate(conv["turns"], 1):
            print(f"    Turn {turn_num}: {question[:50]:<50}", end="", flush=True)
            try:
                r = send_question(token, question, conversation_id=conv_id,
                                  turn_number=turn_num, recent_messages=recent)
                r["conversation_name"] = conv["name"]
                all_results.append(r)

                if "error" in r:
                    print(f"  ERROR: {r['error']}")
                else:
                    conv_id = r.get("conversation_id", conv_id)
                    # Build recent_messages for follow-up context
                    recent.append(question)
                    if len(recent) > 3:
                        recent = recent[-3:]

                    g = r.get("graph_ms", 0)
                    a = r.get("agent_ms", 0)
                    t = r.get("total_ms", 0) or r.get("wall_ms", 0)
                    ids = r.get("graph_ids", [])
                    print(f"  g={g/1000:5.1f}s  a={a/1000:5.1f}s  t={t/1000:5.1f}s  nodes={ids}")
            except Exception as e:
                print(f"  EXCEPTION: {e}")
                all_results.append({"error": str(e), "question": question})

    return all_results


def main():
    print("Logging in...")
    token = login()
    print("Authenticated.\n")

    # Run both phases
    phase1 = run_phase1(token)
    phase2 = run_phase2(token)

    # Combined summary
    all_results = phase1 + phase2
    good = [r for r in all_results if "error" not in r]

    print("\n" + "=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)
    print(f"Total turns: {len(all_results)} ({len(good)} successful)")

    # Phase 1 stats
    p1_good = [r for r in phase1 if "error" not in r]
    p1_graph = [r["graph_ms"] for r in p1_good if r.get("graph_ms", 0) > 0]
    p1_agent = [r["agent_ms"] for r in p1_good if r.get("agent_ms", 0) > 0]
    p1_total = [r.get("total_ms", 0) or r.get("wall_ms", 0) for r in p1_good]

    print("\n  Phase 1 — Independent Questions:")
    print_stats("Graph (classifier + Gremlin)", p1_graph)
    print_stats("Agent (Foundry LLM + search)", p1_agent)
    print_stats("Total (server-side)", p1_total)

    # Phase 2 stats
    p2_good = [r for r in phase2 if "error" not in r]
    p2_graph = [r["graph_ms"] for r in p2_good if r.get("graph_ms", 0) > 0]
    p2_agent = [r["agent_ms"] for r in p2_good if r.get("agent_ms", 0) > 0]
    p2_total = [r.get("total_ms", 0) or r.get("wall_ms", 0) for r in p2_good]

    print("\n  Phase 2 — Multi-Turn Conversations:")
    print_stats("Graph (classifier + Gremlin)", p2_graph)
    print_stats("Agent (Foundry LLM + search)", p2_agent)
    print_stats("Total (server-side)", p2_total)

    # Graph classification accuracy — did the right nodes get picked?
    print("\n  Graph Node Classifications:")
    for r in good:
        if r.get("graph_ids"):
            q = r["question"][:50]
            ids = r["graph_ids"]
            print(f"    {q:<50} -> {ids}")

    # Save raw results
    outfile = "c:/tmp/graph_timing_results.json"
    with open(outfile, "w") as f:
        json.dump({"phase1": phase1, "phase2": phase2, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)
    print(f"\nRaw results saved to {outfile}")


if __name__ == "__main__":
    main()
