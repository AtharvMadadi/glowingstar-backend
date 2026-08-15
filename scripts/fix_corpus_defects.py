#!/usr/bin/env python3
"""Week 4, Task 3 -- repair the offline-correctable defects in the seed corpus.

Two defects, both introduced when LeetCode's HTML was flattened to text during
Phase 1 scraping. Neither can be fixed by re-running the scraper without also
changing the parser, and both are correctable offline from data already in the
repository.

DEFECT 1 -- collapsed exponents
    LeetCode marks up powers as <sup>: 10<sup>4</sup>. Stripping tags without
    substituting the exponent leaves "104", so a constraint reading
    "2 <= nums.length <= 10^4" becomes "2 <= nums.length <= 104" -- off by
    three orders of magnitude and silently plausible.

    The repair is evidence-based rather than a guess. Each problem's separate
    `constraints` array survived with the correct "10^4" form intact, so this
    script only rewrites "10N" -> "10^N" in the description when "10^N"
    actually appears in that same problem's constraints. A number the
    constraints do not vouch for is left alone.

DEFECT 2 -- non-breaking spaces
    U+00A0 survives the flattening and renders identically to a space. Harmless
    in prose, but it would be a false-failure source under `exact` comparison
    if it appeared in test data. It does not -- verified: zero occurrences
    across every args_raw and expected field in all 50 problems. Normalised in
    descriptions anyway so the text is byte-predictable.

Judge impact: none. Both defects live in presentation fields the judge never
reads. This is a correctness fix for the human reading the problem, not for
the comparator.

Usage:
    python3 scripts/fix_corpus_defects.py            # dry run, prints changes
    python3 scripts/fix_corpus_defects.py --apply    # writes seed_data.json

After --apply:
    python3 scripts/seed_problems.py
    python3 scripts/verify_catalogue.py --data-only
"""

import argparse
import json
import re
from pathlib import Path

SEED = Path(__file__).resolve().parent / "seed_data.json"

# "10" followed by a single digit, as a standalone token. Word boundaries stop
# it matching inside a longer literal such as 1042.
COLLAPSED = re.compile(r"\b10(\d)\b")

NBSP = "\u00a0"
ZWSP = "\u200b"


def constraint_text(problem):
    c = problem.get("constraints")
    if isinstance(c, list):
        return " ".join(str(x) for x in c)
    return str(c or "")


def repair_exponents(problem):
    """Rewrite collapsed exponents the constraints array can vouch for."""
    vouched = set(re.findall(r"10\^(\d)", constraint_text(problem)))
    if not vouched:
        return problem["description"], []

    changes = []

    def sub(m):
        digit = m.group(1)
        if digit not in vouched:
            return m.group(0)
        changes.append(f"10{digit} -> 10^{digit}")
        return f"10^{digit}"

    return COLLAPSED.sub(sub, problem["description"]), changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the changes back to seed_data.json")
    args = ap.parse_args()

    data = json.loads(SEED.read_text())

    exp_problems = exp_total = nbsp_problems = nbsp_total = 0

    for p in data:
        before = p["description"]
        after, changes = repair_exponents(p)
        if changes:
            exp_problems += 1
            exp_total += len(changes)
            print(f"{p['slug']}")
            for c in sorted(set(changes)):
                n = changes.count(c)
                print(f"    {c}   x{n}")

        n_nbsp = after.count(NBSP) + after.count(ZWSP)
        if n_nbsp:
            nbsp_problems += 1
            nbsp_total += n_nbsp
            after = after.replace(NBSP, " ").replace(ZWSP, "")

        if after != before:
            p["description"] = after

    # The claim this script makes about test data being clean is checked here
    # rather than asserted, so it stays true if the corpus changes.
    dirty_tests = [
        p["slug"] for p in data
        for t in (p.get("sample_tests") or []) + (p.get("hidden_tests") or [])
        if any(ch in "".join(t.get("args_raw") or []) + str(t.get("expected"))
               for ch in (NBSP, ZWSP))
    ]

    print()
    print(f"collapsed exponents  : {exp_total} in {exp_problems} problems")
    print(f"nbsp / zwsp in prose : {nbsp_total} in {nbsp_problems} problems")
    print(f"invisible chars in test data: {len(dirty_tests)}"
          f"{' -- ' + ', '.join(dirty_tests) if dirty_tests else ' (clean)'}")

    if args.apply:
        SEED.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwritten: {SEED}")
        print("next: python3 scripts/seed_problems.py"
              " && python3 scripts/verify_catalogue.py --data-only")
    else:
        print("\ndry run -- nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
