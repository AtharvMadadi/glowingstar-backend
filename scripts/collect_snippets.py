#!/usr/bin/env python3
"""Fetch starter code templates for the 50 seed problems.

Phase 1's collector did not request `codeSnippets`, so this performs a
targeted re-collection for the selected slugs only (50 requests), then
writes the templates into the `problems` table.

Two stages, independently re-runnable:
  --collect   query LeetCode GraphQL -> scripts/code_snippets.json (resumable)
  --apply     load cache -> problems.code_templates
Default runs both.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Problem  # noqa: E402

ENDPOINT = "https://leetcode.com/graphql"
CACHE = Path("scripts/code_snippets.json")
SLUGS = Path("scripts/seed_slugs.json")

# Spec requires Python, Java, C++.
WANTED = {"python3": "python3", "java": "java", "cpp": "cpp"}

QUERY = """
query questionEditorData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    titleSlug
    codeSnippets { lang langSlug code }
  }
}
"""

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

MIN_INTERVAL = 1.5  # seconds between requests
MAX_RETRIES = 4


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2))


def fetch_one(client: httpx.Client, slug: str) -> dict | None:
    backoff = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.post(
                ENDPOINT,
                json={"query": QUERY, "variables": {"titleSlug": slug}},
                headers={**HEADERS, "Referer": f"https://leetcode.com/problems/{slug}/"},
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            print(f"    network error ({exc.__class__.__name__}), retry {attempt}")
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code in (429, 403, 503):
            wait = backoff + random.uniform(0, 1.5)
            print(f"    HTTP {resp.status_code}, backing off {wait:.1f}s")
            time.sleep(wait)
            backoff *= 2
            continue

        if resp.status_code != 200:
            print(f"    HTTP {resp.status_code}, giving up on {slug}")
            return None

        body = resp.json()
        if body.get("errors"):
            print(f"    GraphQL error: {body['errors'][:1]}")
            return None

        question = (body.get("data") or {}).get("question")
        if not question:
            return None

        templates = {}
        for snip in question.get("codeSnippets") or []:
            key = WANTED.get(snip.get("langSlug"))
            if key:
                templates[key] = snip.get("code")
        return templates

    print(f"    exhausted retries for {slug}")
    return None


def collect() -> None:
    slugs = [s["slug"] for s in json.loads(SLUGS.read_text())]
    cache = load_cache()
    todo = [s for s in slugs if s not in cache]

    if not todo:
        print(f"cache already complete ({len(cache)} slugs)")
        return

    print(f"fetching {len(todo)} slug(s), ~{len(todo) * MIN_INTERVAL / 60:.1f} min")
    last = 0.0
    with httpx.Client(http2=False) as client:
        for i, slug in enumerate(todo, 1):
            gap = time.monotonic() - last
            if gap < MIN_INTERVAL:
                time.sleep(MIN_INTERVAL - gap)
            last = time.monotonic()

            print(f"  [{i}/{len(todo)}] {slug}")
            result = fetch_one(client, slug)
            if result:
                cache[slug] = result
                save_cache(cache)
            else:
                print("    -> no templates returned")

    save_cache(cache)
    print(f"cache now holds {len(cache)} slug(s)")


def apply() -> None:
    if not CACHE.exists():
        raise SystemExit("no cache file — run with --collect first")

    cache = json.loads(CACHE.read_text())
    updated = 0
    partial = []

    with SessionLocal() as db:
        for slug, templates in cache.items():
            problem = db.scalar(select(Problem).where(Problem.slug == slug))
            if problem is None:
                print(f"  not in db: {slug}")
                continue
            problem.code_templates = templates
            updated += 1
            missing = set(WANTED.values()) - set(templates)
            if missing:
                partial.append((slug, sorted(missing)))
        db.commit()

    print(f"updated {updated} problem(s)")
    if partial:
        print(f"incomplete language coverage on {len(partial)}:")
        for slug, missing in partial[:10]:
            print(f"  {slug}: missing {missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    do_all = not (args.collect or args.apply)
    if args.collect or do_all:
        collect()
    if args.apply or do_all:
        apply()


if __name__ == "__main__":
    main()
