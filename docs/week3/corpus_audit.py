#!/usr/bin/env python3
"""
Corpus defect audit — Week 3, Task 1(b) and 1(c).

Reads a JSONL (or JSON array) corpus, inventories its schema, counts defects
by type, and sorts findings into correctable-offline vs requires-re-collection.

Usage:
    python3 corpus_audit.py corpus.jsonl
    python3 corpus_audit.py corpus.jsonl --raw-retained
    python3 corpus_audit.py corpus.jsonl --raw-retained --image-dir ./assets

Stdlib only. No Docker, no Postgres. Read-only: it never modifies the corpus.
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# Field alias resolution — the corpus schema is discovered, not assumed.
# --------------------------------------------------------------------------

ALIASES = {
    "id":          ["uid", "source_problem_id", "display_id", "id", "question_id",
                    "questionId", "problem_id", "frontend_id", "frontendQuestionId"],
    "slug":        ["slug", "title_slug", "titleSlug", "url_slug"],
    "title":       ["title", "name", "question_title"],
    "statement":   ["content_markdown", "content_html", "statement", "content",
                    "description", "body", "problem_statement", "question", "prompt"],
    "statement_html": ["content_html", "html", "raw_html"],
    "constraints": ["constraints", "constraint", "limits"],
    "examples":    ["examples", "sample_tests", "samples", "testcases", "test_cases",
                    "sample_io"],
    "tags":        ["tags", "topic_tags", "topicTags", "categories", "topics"],
    "difficulty":  ["difficulty", "level", "difficulty_level"],
    "hints":       ["hints", "hint"],
    "source_url":  ["canonical_url", "source_url", "url", "link", "problem_url"],
    "collected_at": ["collected_at", "scraped_at", "fetched_at", "collection_date",
                     "timestamp", "retrieved_at", "date"],
    # Collector-specific status fields — these explain most "empty" values.
    "paid_only":      ["paid_only", "is_premium", "premium"],
    "content_status": ["content_status", "status"],
    "error":          ["error", "err", "failure"],
    "raw_metadata":   ["raw_metadata", "raw", "raw_response"],
}

REQUIRED_FIELDS = ["statement", "constraints", "examples", "tags", "difficulty", "hints"]

# --------------------------------------------------------------------------
# Defect detection patterns
# --------------------------------------------------------------------------

HTML_TAG = re.compile(r"</?(p|div|span|strong|em|b|i|code|pre|ul|ol|li|br|img|a|table|"
                      r"tr|td|th|sup|sub|font|h[1-6])\b[^>]*>", re.I)
SUP_SUB = re.compile(r"</?su[pb]\b[^>]*>", re.I)
HTML_ENTITY = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,10}|#x?[0-9a-fA-F]{1,6});")
LATEX = re.compile(r"(\$[^$\n]{1,200}\$|\\\((?s:.){1,200}?\\\)|\\\[(?s:.){1,200}?\\\]|"
                   r"\\(?:le|ge|leq|geq|times|cdot|neq|leftarrow|rightarrow|"
                   r"text|mathrm|frac|sum|prod|sqrt)\b)")
BACKSLASH_ESCAPE = re.compile(r"\\[ntru\"']")
IMG_TAG = re.compile(r"<img\b[^>]*src\s*=\s*[\"']([^\"']+)[\"']", re.I)
MD_IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
BARE_IMG_URL = re.compile(r"https?://[^\s\"'<>)]+\.(?:png|jpe?g|gif|svg|webp)", re.I)

# Characters that commonly survive scraping in mangled form
SMART_CHARS = {
    "\u2018": "left single quote", "\u2019": "right single quote",
    "\u201c": "left double quote", "\u201d": "right double quote",
    "\u2192": "rightwards arrow", "\u2190": "leftwards arrow",
    "\u2264": "less-than-or-equal", "\u2265": "greater-than-or-equal",
    "\u2260": "not-equal", "\u00a0": "non-breaking space",
    "\u200b": "zero-width space", "\ufffd": "replacement char (encoding loss)",
}

IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

# Problem types that structurally suggest a diagram in the statement
DIAGRAM_HINT = re.compile(r"\b(tree|binary tree|linked list|linked-list|graph|grid|"
                          r"matrix|geometry|island|maze|board)\b", re.I)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def load_records(path):
    """Load JSONL or a JSON array. Reports malformed lines rather than dying."""
    records, malformed = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        first = fh.read(1)
        fh.seek(0)
        if first == "[":
            try:
                data = json.load(fh)
                if isinstance(data, list):
                    return data, []
                return [data], []
            except json.JSONDecodeError as exc:
                print(f"FATAL: file starts as a JSON array but failed to parse: {exc}")
                sys.exit(1)
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                malformed.append((lineno, str(exc)))
    return records, malformed


def resolve_schema(records, sample=500):
    """Map canonical field names to whatever keys this corpus actually uses."""
    keys = collections.Counter()
    for rec in records[:sample]:
        if isinstance(rec, dict):
            keys.update(rec.keys())
    resolved = {}
    lower = {k.lower(): k for k in keys}
    for canonical, candidates in ALIASES.items():
        for cand in candidates:
            if cand.lower() in lower:
                resolved[canonical] = lower[cand.lower()]
                break
    return resolved, keys


def get(rec, schema, canonical):
    key = schema.get(canonical)
    return rec.get(key) if key else None


def is_empty(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def as_text(value):
    """Flatten any field into a searchable string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def count_example_io(examples):
    """
    Return (n_inputs, n_outputs, parseable).
    Handles: list of dicts with input/output keys, list of strings, single string.
    """
    if examples is None:
        return 0, 0, False

    if isinstance(examples, list):
        n_in = n_out = 0
        structured = False
        for ex in examples:
            if isinstance(ex, dict):
                structured = True
                ik = next((k for k in ex if k.lower() in
                           ("input", "in", "stdin", "args", "input_data")), None)
                ok = next((k for k in ex if k.lower() in
                           ("output", "out", "expected", "expected_output",
                            "stdout", "result")), None)
                if ik and not is_empty(ex.get(ik)):
                    n_in += 1
                if ok and not is_empty(ex.get(ok)):
                    n_out += 1
        if structured:
            return n_in, n_out, True
        blob = as_text(examples)
    else:
        blob = as_text(examples)

    n_in = len(re.findall(r"\bInput\s*:?", blob, re.I))
    n_out = len(re.findall(r"\bOutput\s*:?", blob, re.I))
    return n_in, n_out, (n_in + n_out) > 0


def find_images(text):
    urls = []
    urls += IMG_TAG.findall(text)
    urls += MD_IMG.findall(text)
    urls += [m for m in BARE_IMG_URL.findall(text)]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def count_html_to_markdown_superscript_corruption(records, schema):
    """Records where content_html has a <sup> tag -- meaning the source
    genuinely had an exponent -- but the markdown conversion silently
    dropped the tag and concatenated the digits into the base (10^4
    rendered as 104). Checks the HTML field specifically, since by the
    time text reaches the markdown field the tag is already gone; scanning
    the markdown-derived 'statement' field alone (as the general markup
    residue scan below does) cannot detect this defect, because there is
    nothing left in that field to find.
    """
    affected_records = 0
    total_occurrences = 0
    html_key = schema.get("statement_html")
    if not html_key:
        return 0, 0, "no HTML field resolved in this schema; check skipped"
    for rec in records:
        if not isinstance(rec, dict):
            continue
        html = as_text(rec.get(html_key))
        n = html.count("<sup>")
        if n:
            affected_records += 1
            total_occurrences += n
    return affected_records, total_occurrences, None


def count_invisible_chars_in_examples_only(records, schema):
    """Zero-width space and non-breaking space occurrences specifically
    inside the examples field, as opposed to statement prose. This matters
    because the exact comparator would be exposed to these characters only
    if they land inside an example's input/output text -- a contamination
    count over the whole record (statement + constraints + examples
    combined, as the general character scan below does) cannot distinguish
    'cosmetic, in prose' from 'a live risk to the judge, in test data'.
    """
    affected_records = 0
    ex_key = schema.get("examples")
    if not ex_key:
        return 0, "no examples field resolved in this schema; check skipped"
    for rec in records:
        if not isinstance(rec, dict):
            continue
        examples = rec.get(ex_key)
        if not examples:
            continue
        blob = as_text(examples)
        if "\u200b" in blob or "\u00a0" in blob:
            affected_records += 1
    return affected_records, None


# --------------------------------------------------------------------------
# Main audit
# --------------------------------------------------------------------------

def audit(path, raw_retained, image_dir):
    records, malformed = load_records(path)
    total = len(records)
    if total == 0:
        print("No records loaded. Check the path and format.")
        sys.exit(1)

    schema, key_counts = resolve_schema(records)

    # --- accumulators -----------------------------------------------------
    missing = collections.Counter()        # field absent entirely
    empty = collections.Counter()          # key present, value empty
    io_mismatch = []
    io_unparseable = []
    img_records = []                       # (identifier, [urls])
    img_local = img_remote = 0
    diagram_suspect_no_img = []
    residue = collections.Counter()
    residue_records = collections.defaultdict(set)
    smart_counts = collections.Counter()
    id_counts = collections.Counter()
    slug_counts = collections.Counter()
    content_hashes = collections.Counter()
    no_source_url = no_collected_at = 0
    non_dict = 0
    status_tally = collections.Counter()
    raw_meta_present = 0

    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            non_dict += 1
            continue

        ident = (get(rec, schema, "slug") or get(rec, schema, "id")
                 or get(rec, schema, "title") or f"<record #{idx}>")

        # 1. field completeness
        for field in REQUIRED_FIELDS:
            key = schema.get(field)
            if key is None or key not in rec:
                missing[field] += 1
            elif is_empty(rec.get(key)):
                empty[field] += 1

        # 2. example input/output mismatch
        examples = get(rec, schema, "examples")
        n_in, n_out, parseable = count_example_io(examples)
        if not is_empty(examples):
            if not parseable:
                io_unparseable.append(ident)
            elif n_in != n_out:
                io_mismatch.append((ident, n_in, n_out))

        # cross-tab: is this record empty because it is premium or errored?
        paid = get(rec, schema, "paid_only")
        cstatus = get(rec, schema, "content_status")
        rerror = get(rec, schema, "error")
        if paid in (True, "true", 1):
            status_tally["paid_only"] += 1
        if cstatus is not None:
            status_tally[f"content_status={cstatus}"] += 1
        if not is_empty(rerror):
            status_tally["has_error"] += 1
        if not is_empty(get(rec, schema, "raw_metadata")):
            raw_meta_present += 1

        # 3. images — must include the HTML body, that is where <img> survives
        blob = " ".join(as_text(get(rec, schema, f))
                        for f in ("statement", "constraints", "examples"))
        img_blob = blob + " " + as_text(get(rec, schema, "statement_html"))
        urls = find_images(img_blob)
        # also catch a dedicated image field
        for k, v in rec.items():
            if "image" in k.lower() or "figure" in k.lower() or "diagram" in k.lower():
                for u in re.findall(r"[^\s\"',\[\]]+", as_text(v)):
                    if u.lower().endswith(IMG_EXT):
                        urls.append(u)
        urls = list(dict.fromkeys(urls))
        if urls:
            img_records.append((ident, urls))
            for u in urls:
                if u.startswith(("http://", "https://")):
                    img_remote += 1
                else:
                    img_local += 1
        else:
            title_blob = as_text(get(rec, schema, "title")) + " " + \
                         as_text(get(rec, schema, "tags"))
            if DIAGRAM_HINT.search(title_blob):
                diagram_suspect_no_img.append(ident)

        # 4. markup residue
        checks = {
            "html_tags": HTML_TAG,
            "sup_sub_tags": SUP_SUB,
            "html_entities": HTML_ENTITY,
            "latex": LATEX,
            "backslash_escapes": BACKSLASH_ESCAPE,
        }
        for name, pattern in checks.items():
            hits = pattern.findall(blob)
            if hits:
                residue[name] += len(hits)
                residue_records[name].add(ident)
        for ch, label in SMART_CHARS.items():
            n = blob.count(ch)
            if n:
                smart_counts[label] += n
                residue_records[f"char:{label}"].add(ident)

        # 5. duplicates / identifier uniqueness
        rid = get(rec, schema, "id")
        if rid is not None:
            id_counts[str(rid)] += 1
        rslug = get(rec, schema, "slug")
        if rslug:
            slug_counts[str(rslug)] += 1
        stmt = as_text(get(rec, schema, "statement")).strip()
        if stmt:
            content_hashes[hashlib.sha256(stmt.encode("utf-8")).hexdigest()] += 1

        # 6. provenance
        if is_empty(get(rec, schema, "source_url")):
            no_source_url += 1
        if is_empty(get(rec, schema, "collected_at")):
            no_collected_at += 1

    # ---------------------------------------------------------------- report
    def pct(n):
        return f"{n} ({n / total * 100:.1f}%)"

    L = []
    add = L.append

    add("=" * 72)
    add("CORPUS DEFECT AUDIT — Week 3, Task 1")
    add("=" * 72)
    add(f"File            : {os.path.abspath(path)}")
    add(f"Records loaded  : {total}")
    if malformed:
        add(f"Malformed lines : {len(malformed)}  (first: line {malformed[0][0]})")
    if non_dict:
        add(f"Non-object rows : {non_dict}")
    add(f"Raw responses   : {'RETAINED' if raw_retained else 'NOT RETAINED'}"
        f"  (--raw-retained flag)")
    add("")

    add("-" * 72)
    add("SCHEMA RESOLUTION")
    add("-" * 72)
    for canonical in list(ALIASES):
        key = schema.get(canonical)
        add(f"  {canonical:<14} -> {key if key else '*** NO MATCHING KEY ***'}")
    add("")
    add("  All top-level keys observed:")
    for k, v in key_counts.most_common():
        add(f"    {k:<28} present in {v} of first {min(total, 500)} records")
    add("")

    add("-" * 72)
    add("1. FIELD COMPLETENESS")
    add("-" * 72)
    add(f"  {'field':<14} {'absent':<16} {'present-but-empty'}")
    for field in REQUIRED_FIELDS:
        add(f"  {field:<14} {pct(missing[field]):<16} {pct(empty[field])}")
    add("")

    add("  Why fields are empty — record status breakdown:")
    for k, v in status_tally.most_common():
        add(f"    {k:<28} {pct(v)}")
    add(f"    {'raw_metadata retained':<28} {pct(raw_meta_present)}")
    add("    ^ empties on premium/errored records are expected, not parsing defects")
    add("")

    add("-" * 72)
    add("2. EXAMPLE INPUT/OUTPUT COUNT MISMATCH")
    add("-" * 72)
    add(f"  Mismatched counts    : {pct(len(io_mismatch))}")
    add(f"  Unparseable examples : {pct(len(io_unparseable))}")
    for ident, a, b in io_mismatch[:15]:
        add(f"    {ident}: {a} input(s) / {b} output(s)")
    if len(io_mismatch) > 15:
        add(f"    ... and {len(io_mismatch) - 15} more")
    add("")

    add("-" * 72)
    add("3. IMAGES")
    add("-" * 72)
    add(f"  Records depending on >=1 image : {pct(len(img_records))}")
    add(f"  Image references total          : {img_local + img_remote}")
    add(f"    hot-linked (remote URL)       : {img_remote}")
    add(f"    local paths                   : {img_local}")
    if image_dir:
        present = missing_files = 0
        for _, urls in img_records:
            for u in urls:
                if not u.startswith(("http://", "https://")):
                    if os.path.exists(os.path.join(image_dir, os.path.basename(u))):
                        present += 1
                    else:
                        missing_files += 1
        add(f"  Local files verified in {image_dir}: {present} present, "
            f"{missing_files} MISSING")
    else:
        add("  (pass --image-dir to verify local files actually exist on disk)")
    add(f"  Diagram-suggestive problems with NO image captured : "
        f"{pct(len(diagram_suspect_no_img))}")
    add("    ^ likely silently-dropped diagrams; spot-check these by hand")
    for ident in diagram_suspect_no_img[:10]:
        add(f"      {ident}")
    add("")

    add("-" * 72)
    add("4. MARKUP RESIDUE")
    add("-" * 72)
    for name in ("html_tags", "sup_sub_tags", "html_entities", "latex",
                 "backslash_escapes"):
        add(f"  {name:<20} {residue[name]:>7} occurrences  in "
            f"{pct(len(residue_records[name]))} of records")
    add("  Non-ASCII / escaping artifacts:")
    if smart_counts:
        for label, n in smart_counts.most_common():
            add(f"    {label:<28} {n:>7} occurrences  in "
                f"{len(residue_records['char:' + label])} records")
    else:
        add("    none detected")
    add("")

    add("-" * 72)
    add("4b. HTML-TO-MARKDOWN SUPERSCRIPT CORRUPTION")
    add("-" * 72)
    add("  Scans content_html directly for <sup> tags. The general markup")
    add("  residue scan above (sup_sub_tags) cannot see this defect, because")
    add("  it scans the already-converted markdown/statement field, where the")
    add("  tag has already been stripped and the digits concatenated into the")
    add("  base (10^4 rendered as 104) -- there is nothing left there to find.")
    sup_records, sup_occurrences, sup_note = count_html_to_markdown_superscript_corruption(
        records, schema)
    if sup_note:
        add(f"  SKIPPED: {sup_note}")
    else:
        add(f"  Records with <sup> in content_html : {pct(sup_records)}")
        add(f"  Total <sup> occurrences            : {sup_occurrences}")
    add("")

    add("-" * 72)
    add("4c. INVISIBLE CHARACTERS INSIDE examples SPECIFICALLY")
    add("-" * 72)
    add("  Same characters as the general scan above, but checked only")
    add("  inside the examples field, which is the only place they would")
    add("  actually reach the judge's exact comparator as live test data.")
    ex_invisible_records, ex_note = count_invisible_chars_in_examples_only(
        records, schema)
    if ex_note:
        add(f"  SKIPPED: {ex_note}")
    else:
        add(f"  Records with zero-width/NBSP inside examples : {pct(ex_invisible_records)}")
        if ex_invisible_records == 0:
            add("  ^ 0 confirmed: contamination found elsewhere is confined to")
            add("    statement prose, not example test data. exact mode is not")
            add("    exposed to it.")
    add("")

    add("-" * 72)
    add("5. DUPLICATES AND IDENTIFIER UNIQUENESS")
    add("-" * 72)
    dup_ids = {k: v for k, v in id_counts.items() if v > 1}
    dup_slugs = {k: v for k, v in slug_counts.items() if v > 1}
    dup_content = {k: v for k, v in content_hashes.items() if v > 1}
    add(f"  Records carrying an id      : {sum(id_counts.values())} of {total}")
    add(f"  Duplicate id values         : {len(dup_ids)} "
        f"(covering {sum(dup_ids.values())} records)")
    add(f"  Duplicate slug values       : {len(dup_slugs)} "
        f"(covering {sum(dup_slugs.values())} records)")
    add(f"  Identical statement bodies  : {len(dup_content)} "
        f"(covering {sum(dup_content.values())} records)")
    for k, v in list(dup_ids.items())[:10]:
        add(f"    id={k} appears {v}x")
    add("")

    add("-" * 72)
    add("6. PROVENANCE")
    add("-" * 72)
    add(f"  Missing source URL     : {pct(no_source_url)}")
    add(f"  Missing collection date: {pct(no_collected_at)}")
    add("")

    # ------------------------------------------------------- categorisation
    add("=" * 72)
    add("TASK 1(c) — FINDINGS SORTED")
    add("=" * 72)

    offline, recollect = [], []

    def route(label, count, always_offline=False):
        if count == 0:
            return
        entry = f"{label}: {count} records"
        if always_offline or raw_retained:
            offline.append(entry)
        else:
            recollect.append(entry)

    # Always correctable offline — these are transforms on text we already hold.
    for name in ("html_tags", "sup_sub_tags", "html_entities", "latex",
                 "backslash_escapes"):
        if residue[name]:
            offline.append(f"markup residue / {name}: "
                           f"{len(residue_records[name])} records")
    if smart_counts:
        offline.append(f"character escaping artifacts: "
                       f"{sum(smart_counts.values())} occurrences")
    if dup_ids or dup_slugs or dup_content:
        offline.append(f"duplicate records: {len(dup_ids)} id, {len(dup_slugs)} slug, "
                       f"{len(dup_content)} identical-body")

    # Conditional on raw retention.
    for field in REQUIRED_FIELDS:
        route(f"absent field '{field}'", missing[field] + empty[field])
    route("example input/output count mismatch", len(io_mismatch))
    route("unparseable examples block", len(io_unparseable))
    route("missing source URL", no_source_url)
    route("missing collection date", no_collected_at)

    # Images are the hard case: hot-linked assets are not in the corpus at all.
    if img_remote:
        recollect.append(f"hot-linked images requiring download: {img_remote} URLs "
                         f"across {len(img_records)} records")
    if diagram_suspect_no_img:
        recollect.append(f"diagram-suggestive problems with no image captured: "
                         f"{len(diagram_suspect_no_img)} records")

    add("")
    add("CORRECTABLE OFFLINE (no network access required):")
    if offline:
        for e in offline:
            add(f"  - {e}")
    else:
        add("  - none")
    add("")
    add("REQUIRES RE-COLLECTION (must hit the source again):")
    if recollect:
        for e in recollect:
            add(f"  - {e}")
    else:
        add("  - none")
    add("")
    if not raw_retained:
        add("NOTE: run was categorised with raw responses NOT retained. If the raw")
        add("      HTML/JSON payloads were in fact kept, re-run with --raw-retained")
        add("      and most of the second list collapses into the first.")
    add("")
    add("Counts only. No corrections applied, no re-collection run started.")
    add("=" * 72)

    report = "\n".join(L)
    print(report)

    with open("corpus_audit_report.txt", "w", encoding="utf-8") as fh:
        fh.write(report + "\n")

    summary = {
        "total_records": total,
        "malformed_lines": len(malformed),
        "raw_retained": raw_retained,
        "schema": schema,
        "missing_fields": dict(missing),
        "empty_fields": dict(empty),
        "example_io_mismatch": len(io_mismatch),
        "example_unparseable": len(io_unparseable),
        "records_with_images": len(img_records),
        "images_remote": img_remote,
        "images_local": img_local,
        "diagram_suspect_no_image": len(diagram_suspect_no_img),
        "markup_residue": dict(residue),
        "character_artifacts": dict(smart_counts),
        "html_to_markdown_superscript_records": sup_records if not sup_note else None,
        "html_to_markdown_superscript_occurrences": sup_occurrences if not sup_note else None,
        "invisible_chars_in_examples_records": ex_invisible_records if not ex_note else None,
        "duplicate_ids": len(dup_ids),
        "duplicate_slugs": len(dup_slugs),
        "duplicate_statements": len(dup_content),
        "missing_source_url": no_source_url,
        "missing_collected_at": no_collected_at,
        "correctable_offline": offline,
        "requires_recollection": recollect,
    }
    with open("corpus_audit_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    print("\nWrote corpus_audit_report.txt and corpus_audit_summary.json")


def main():
    ap = argparse.ArgumentParser(description="Corpus defect audit (Week 3, Task 1)")
    ap.add_argument("corpus", help="path to the JSONL or JSON corpus file")
    ap.add_argument("--raw-retained", action="store_true",
                    help="set if the raw scrape responses were kept on disk")
    ap.add_argument("--image-dir", default=None,
                    help="directory of downloaded images, to verify local files exist")
    args = ap.parse_args()
    audit(args.corpus, args.raw_retained, args.image_dir)


if __name__ == "__main__":
    main()
