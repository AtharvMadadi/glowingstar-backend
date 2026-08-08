#!/usr/bin/env python3
"""Select 50 judge-friendly seed problems from the Phase 1 LeetCode corpus.

Selection is constrained by what a simple positional-argument judge can
actually evaluate: pure functions, primitive/list arguments, comparable
return values. Problems requiring custom object serialisation, persistent
class state, or in-place mutation are excluded by design, not by accident.
"""

import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path

TARGET = {"Easy": 25, "Medium": 20, "Hard": 5}

EXCLUDED_TAGS = {
    "linked list", "doubly-linked list", "tree", "binary tree",
    "binary search tree", "graph", "design", "trie", "segment tree",
    "binary indexed tree", "interactive", "database", "shell",
    "concurrency", "iterator", "minimum spanning tree", "randomized",
    "reservoir sampling", "rejection sampling", "probability and statistics",
}

EXCLUDED_TITLE = re.compile(
    r"\b(design|implement|iterator|serialize|deserialize|codec|shuffle|"
    r"random|sql|stream|lru|lfu)\b",
    re.I,
)

INPLACE = re.compile(
    r"(in-?place|do not return anything|not be returned by the function|"
    r"stored inside the array|without using extra space|"
    r"the judge will test|modifying .{0,20}input array|nums itself|"
    r"return the array|s itself)",
    re.I,
)


def norm_difficulty(record):
    """Difficulty may be a plain string or a nested dict depending on record."""
    candidates = [record.get("difficulty")]
    rm = record.get("raw_metadata")
    if isinstance(rm, dict):
        detail = rm.get("detail_response")
        if isinstance(detail, dict):
            candidates.append(detail.get("difficulty"))
    for c in candidates:
        if isinstance(c, str) and c.strip().title() in TARGET:
            return c.strip().title()
        if isinstance(c, dict):
            for v in c.values():
                if isinstance(v, str) and v.strip().title() in TARGET:
                    return v.strip().title()
    return None


def norm_tags(record):
    raw = record.get("tags") or []
    out = []
    for t in raw:
        if isinstance(t, dict):
            t = t.get("name") or t.get("slug") or ""
        out.append(str(t).strip().lower())
    return [t for t in out if t]


def likes(record):
    d = record.get("raw_metadata", {}).get("detail_response", {})
    try:
        return int(d.get("likes") or 0)
    except (TypeError, ValueError):
        return 0


def testcases(record):
    d = record.get("raw_metadata", {}).get("detail_response", {})
    return d.get("exampleTestcaseList") or []


def evaluate(record):
    """Return (ok, reason). reason explains the first failed criterion."""
    if record.get("paid_only"):
        return False, "premium"
    if record.get("content_status") != "ok" and not record.get("content_markdown"):
        return False, "no statement"
    if norm_difficulty(record) is None:
        return False, "unknown difficulty"

    tags = norm_tags(record)
    hit = EXCLUDED_TAGS.intersection(tags)
    if hit:
        return False, f"tag: {sorted(hit)[0]}"

    if EXCLUDED_TITLE.search(record.get("title", "")):
        return False, "title pattern (stateful/design)"

    body = record.get("content_markdown") or ""
    if INPLACE.search(body):
        return False, "in-place / void return"

    tc = testcases(record)
    if len(tc) < 2:
        return False, f"only {len(tc)} example testcase(s)"

    ex = record.get("examples") or []
    if len(ex) != len(tc):
        return False, f"example/testcase mismatch ({len(ex)} vs {len(tc)})"
    if any(e.get("output") in (None, "") for e in ex):
        return False, "missing expected output"

    # Multi-line single arguments are usually matrices or nested structures;
    # allowed, but arguments must at least be literal-parseable.
    for case in tc:
        for arg in case.split("\n"):
            if not arg.strip():
                return False, "empty argument"

    return True, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "corpus",
        nargs="?",
        default=str(Path.home() / "corpus/LeetCode-Collector-final-Atharv-Madadi--main/problems_leetcode.jsonl.gz"),
    )
    ap.add_argument("-o", "--out", default="scripts/seed_slugs.json")
    args = ap.parse_args()

    path = Path(args.corpus)
    if not path.exists():
        raise SystemExit(f"corpus not found: {path}")

    opener = gzip.open if path.suffix == ".gz" else open
    total = 0
    passed = []
    reasons = Counter()

    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            rec = json.loads(line)
            ok, why = evaluate(rec)
            if ok:
                passed.append(rec)
            else:
                reasons[why] += 1

    passed.sort(key=likes, reverse=True)

    selected = []
    counts = Counter()
    for rec in passed:
        d = norm_difficulty(rec)
        if counts[d] < TARGET[d]:
            counts[d] += 1
            selected.append(
                {
                    "slug": rec["slug"],
                    "title": rec["title"],
                    "difficulty": d,
                    "tags": norm_tags(rec),
                    "n_example_tests": len(testcases(rec)),
                    "likes": likes(rec),
                }
            )
        if len(selected) == sum(TARGET.values()):
            break

    # Output-comparison strategy. Problems whose statements permit any
    # ordering, or return floats, cannot be judged by exact string match.
    UNORDERED = {
        "two-sum", "generate-parentheses",
        "letter-combinations-of-a-phone-number", "merge-intervals",
        "find-all-numbers-disappeared-in-an-array",
    }
    UNORDERED_NESTED = {"group-anagrams", "3sum", "combination-sum"}
    FLOAT = {"median-of-two-sorted-arrays"}

    for item in selected:
        slug = item["slug"]
        if slug in UNORDERED_NESTED:
            item["comparison"] = "unordered_nested"
        elif slug in UNORDERED:
            item["comparison"] = "unordered"
        elif slug in FLOAT:
            item["comparison"] = "float"
        else:
            item["comparison"] = "exact"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(selected, indent=2))

    print(f"scanned:   {total}")
    print(f"eligible:  {len(passed)}")
    print(f"selected:  {len(selected)}  {dict(counts)}")
    print(f"written:   {out}\n")
    print("top exclusion reasons:")
    for why, n in reasons.most_common(10):
        print(f"  {n:5d}  {why}")
    print("\nselection:")
    for i, s in enumerate(selected, 1):
        print(f"  {i:2d}. [{s['difficulty']:6s}] {s['title']}  ({s['n_example_tests']} tests)")


if __name__ == "__main__":
    main()
