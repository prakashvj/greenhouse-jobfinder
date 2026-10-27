"""Bulk-check candidate company names against Greenhouse's public Job Board API.

A one-time/occasional maintenance utility, not part of normal app usage - it never runs
during a search or "Refresh jobs". Run it with `python -m jobfinder.discover_boards` to see
which candidates are real Greenhouse boards not already in config.yaml.
"""
import httpx
import yaml
from concurrent.futures import ThreadPoolExecutor

from .greenhouse import API

# Small, labeled candidate lists (not blind guesses) - sourced from companies specifically
# identified elsewhere as Greenhouse customers, plus known infra/SRE/platform-space companies
# worth checking for this project's focus. Extend these lists over time as you find more.
CANDIDATES = {
    "broad_tech_saas": [
        "notion", "linear", "doordash", "plaid", "webflow", "loom", "retool",
        "moderntreasury", "rippling", "mercury", "replit", "cursor", "perplexityai",
        "elevenlabs", "huggingface", "openai", "anysphere",
    ],
    "sre_devops_infra": [
        "hashicorp", "grafanalabs", "honeycomb", "chronosphere", "sentry", "circleci",
        "harness", "snyk", "jfrog", "sumologic", "netlify", "render", "temporal",
        "confluent", "redis", "weightsandbiases", "together", "replicate", "modal",
        "pinecone", "weaviate", "langchain", "teleport", "observeinc", "arize", "whylabs",
    ],
}


def check_board(token, client):
    """Return (token, open_job_count) if the board is real and has jobs, else (token, None)."""
    try:
        r = client.get(API.format(token=token), params={"content": "false"}, timeout=10)
    except httpx.TransportError:
        return token, None
    if r.status_code != 200:
        return token, None
    jobs = r.json().get("jobs", [])
    return token, (len(jobs) if jobs else None)


def discover(candidates, already_configured, client=None, workers=10):
    to_check = [c for c in candidates if c not in already_configured]
    found = {}
    own = client is None
    client = client or httpx.Client()
    try:
        with ThreadPoolExecutor(workers) as ex:
            for token, count in ex.map(lambda t: check_board(t, client), to_check):
                if count:
                    found[token] = count
    finally:
        if own:
            client.close()
    return found


def main():
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    already = set(cfg["boards"])
    all_candidates = [c for group in CANDIDATES.values() for c in group]
    found = discover(all_candidates, already)
    checked = len(set(all_candidates) - already)
    print(f"Checked {checked} candidates not already configured, found {len(found)} real boards:\n")
    for token, count in sorted(found.items()):
        print(f"  {token} ({count} open jobs)")
    skipped = len(all_candidates) - checked
    if skipped:
        print(f"\n({skipped} candidate(s) already in config.yaml's boards list, skipped)")


if __name__ == "__main__":
    main()
