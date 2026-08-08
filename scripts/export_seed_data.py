#!/usr/bin/env python3
"""Bundle the 50 selected problems into a self-contained seed file.

The Phase 1 corpus (~4k records) and the snippet cache live outside this
repository. This flattens exactly what the database needs into
scripts/seed_data.json so that `seed_problems.py` has no external
dependencies and the migration+seed path is reproducible from a clone.
"""

import gzip
import json
from pathlib import Path

CORPUS = Path.home() / "corpus/LeetCode-Collector-final-Atharv-Madadi--main/problems_leetcode.jsonl.gz"
SLUGS = Path("scripts/seed_slugs.json")
SNIPPETS = Path("scripts/code_snippets.json")
OUT = Path("scripts/seed_data.json")

DIFFICULTIES = {"Easy", "Medium", "Hard"}


def norm_difficulty(rec):
    cands = [rec.get("difficulty")]
    rm = rec.get("raw_metadata")
    if isinstance(rm, dict) and isinstance(rm.get("detail_response"), dict):
        cands.append(rm["detail_response"].get("difficulty"))
    for c in cands:
        if isinstance(c, str) and c.strip().title() in DIFFICULTIES:
            return c.strip().title()
        if isinstance(c, dict):
            for v in c.values():
                if isinstance(v, str) and v.strip().title() in DIFFICULTIES:
                    return v.strip().title()
    return "Unknown"


def norm_tags(rec):
    out = []
    for t in rec.get("tags") or []:
        if isinstance(t, dict):
            t = t.get("name") or t.get("slug") or ""
        t = str(t).strip()
        if t:
            out.append(t)
    return out


def sample_tests(rec):
    detail = rec.get("raw_metadata", {}).get("detail_response", {})
    raw = detail.get("exampleTestcaseList") or []
    ex = rec.get("examples") or []
    tests = []
    for i, r in enumerate(raw):
        if i >= len(ex):
            break
        tests.append({
            "args_raw": r.split("\n"),
            "expected": ex[i].get("output"),
            "display_input": ex[i].get("input"),
            "explanation": ex[i].get("explanation"),
        })
    return tests


def main():
    selection = {s["slug"]: s for s in json.loads(SLUGS.read_text())}
    snippets = json.loads(SNIPPETS.read_text()) if SNIPPETS.exists() else {}

    found = {}
    with gzip.open(CORPUS, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("slug") in selection:
                found[rec["slug"]] = rec
            if len(found) == len(selection):
                break

    missing = set(selection) - set(found)
    if missing:
        raise SystemExit(f"missing from corpus: {sorted(missing)}")

    bundle = []
    for slug, meta in selection.items():
        rec = found[slug]
        bundle.append({
            "slug": slug,
            "title": rec.get("title") or meta["title"],
            "difficulty": norm_difficulty(rec),
            "description": rec.get("content_markdown") or "",
            "constraints": rec.get("constraints"),
            "tags": norm_tags(rec),
            "code_templates": snippets.get(slug, {}),
            "sample_tests": sample_tests(rec),
            "hidden_tests": [],
            "comparison": meta.get("comparison", "exact"),
        })

    OUT.write_text(json.dumps(bundle, indent=2))
    size_kb = OUT.stat().st_size / 1024
    n_tmpl = sum(1 for b in bundle if b["code_templates"])
    n_tests = sum(len(b["sample_tests"]) for b in bundle)
    print(f"wrote {OUT}  ({len(bundle)} problems, {size_kb:.0f} KB)")
    print(f"  templates: {n_tmpl}/{len(bundle)}   sample tests: {n_tests}")


if __name__ == "__main__":
    main()
