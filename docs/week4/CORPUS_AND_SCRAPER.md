# Corpus and Scraper

Where the problem data came from, how to reproduce it, and how to repair or
extend it. Written because the scraper is the least transferable part of this
work: documented, the corpus can be rebuilt; undocumented, it becomes a fixed
artifact nobody can add to.

> **TODO before handover — Atharv.** The sections marked `[VERIFY]` describe the
> Phase 1 collector, which lives in a separate repository and is not something
> this document's author can inspect. Fill in or correct each one from the
> collector source before this is handed over. Everything not marked has been
> checked against the code in this repository.

---

## 1. What exists

| Artifact | Location | Notes |
|---|---|---|
| Raw corpus | `~/corpus/LeetCode-Collector-final-Atharv-Madadi--main/problems_leetcode.jsonl.gz` | 3,991 records, gzipped JSONL, one problem per line |
| Collector source | separate repository `[VERIFY: name and URL]` | not vendored here |
| Selected slugs | `scripts/seed_slugs.json` | the 50 chosen for seeding |
| Code templates | `scripts/code_snippets.json` | per-language starter templates |
| Flattened seed file | `scripts/seed_data.json` | self-contained; what actually seeds the database |

**The corpus is not in this repository and does not need to be for normal
operation.** `seed_data.json` is self-contained, so a clone can migrate and
seed with no external dependency. The corpus is only needed to rebuild that
file or to extend the catalogue past 50 problems.

### Corpus record shape

Each line is one problem. Fields relied on by `select_seed.py` and
`export_seed_data.py`:

| Field | Use |
|---|---|
| `slug`, `title` | identity |
| `difficulty` | may be a plain string or nested under `raw_metadata.detail_response`; `norm_difficulty()` handles both |
| `tags` | list of strings or of `{name, slug}` dicts; `norm_tags()` handles both |
| `description`, `constraints` | statement text |
| `examples` | list of `{input, output, explanation}` |
| `raw_metadata.detail_response.exampleTestcaseList` | the machine-readable inputs; paired positionally with `examples` to build test cases |
| `permission_status` | provenance — `"pending"` throughout, see §5 |

The dual-shape handling in both scripts is not defensive padding. The corpus
genuinely contains both shapes, because `[VERIFY: two collection passes, or a
mid-run API change?]`.

## 2. Running the scraper

`[VERIFY — every line in this section.]`

```
Location:        [VERIFY: repo URL / local path]
Entry point:     [VERIFY: e.g. python3 collect.py --out problems.jsonl.gz]
Dependencies:    [VERIFY: requirements.txt contents, Python version]
Auth:            [VERIFY: session cookie needed for premium metadata? where set?]
Rate limiting:   [VERIFY: requests/sec, sleep between calls, backoff on 429]
Runtime:         [VERIFY: wall clock for a full 3,991-record run]
Resumability:    [VERIFY: does an interrupted run resume, or restart?]
Output:          JSONL, one record per line, gzipped
```

**What breaks** `[VERIFY, but these are the ones to check]`:

- **Rate limiting.** LeetCode throttles aggressively. Too fast and you get 429s;
  the collector `[VERIFY: backs off / fails / retries]`.
- **GraphQL schema drift.** The problem detail comes from a GraphQL endpoint
  whose field names change without notice. A rename surfaces as records missing
  a field rather than as an error, which is why `norm_difficulty()` and
  `norm_tags()` accept multiple shapes.
- **Premium problems.** 776 of the 3,991 records are metadata-only — the
  statement is paywalled. They are excluded from seeding by
  `[VERIFY: which filter]`.
- **HTML flattening.** Statements arrive as HTML and are flattened to text.
  This is where both defects in §4 come from. Anything relying on markup
  (`<sup>`, `<code>`, tables) degrades silently.

## 3. Rebuilding `seed_data.json`

```bash
# 1. choose the 50 (only if changing the selection)
python3 scripts/select_seed.py

# 2. flatten corpus + snippets into the seed file
python3 scripts/export_seed_data.py

# 3. repair known text defects (see §4)
python3 scripts/fix_corpus_defects.py --apply

# 4. load into the database
python3 scripts/seed_problems.py

# 5. confirm nothing broke
python3 scripts/verify_catalogue.py
```

`export_seed_data.py` expects the corpus at the path in its `CORPUS` constant.
Change it there if the archive lives elsewhere.

### Selection criteria

`select_seed.py` filters to what a positional-argument judge can evaluate, then
quota-fills 25 Easy / 20 Medium / 5 Hard by popularity. Excluded by design:

- **`EXCLUDED_TAGS`** — linked list, tree, binary tree, BST, graph, design,
  trie, segment tree, BIT, interactive, database, shell, concurrency, iterator,
  minimum spanning tree, randomized, reservoir/rejection sampling, probability
- **`EXCLUDED_TITLE`** — titles matching design, implement, iterator,
  serialize, deserialize, codec, shuffle, random, sql, stream, lru, lfu
- **`INPLACE`** — statements promising in-place mutation or a void return

These are judge limitations, not corpus gaps. The corpus has plenty of all of
them. Handover §5 explains what each would need.

## 4. Known corpus defects

Run `python3 scripts/fix_corpus_defects.py` (dry run) to see current counts.

**Collapsed exponents — 79 occurrences across 37 of 50 problems.** LeetCode
marks powers up as `10<sup>4</sup>`; the flattener dropped the tags without
substituting, so `10^4` became `104`. A constraint reading
`2 <= nums.length <= 104` is wrong by three orders of magnitude and looks
entirely plausible.

The repair is evidence-based, not a guess: each problem's separate
`constraints` array kept the correct `10^4` form, so the script only rewrites
`10N` → `10^N` in the description when `10^N` appears in that same problem's
constraints. Unvouched numbers are left alone. Verified idempotent — a second
run reports zero.

**Non-breaking spaces — 41 occurrences across 14 problems.** U+00A0 survived
the flattening and renders identically to a space. Normalised to plain spaces.

**Neither defect affects judging.** Both live in presentation fields the judge
never reads. This was worth checking rather than assuming, because invisible
whitespace inside a test case *would* cause `exact` comparison to reject
correct submissions — so the script asserts the test data is clean rather than
claiming it: **zero invisible characters across every `args_raw` and `expected`
field in all 50 problems.**

**Not fixed:** input/expected count mismatches. There are none in the seeded 50,
for two independent reasons — `select_seed.py` filtered mismatched candidates
at selection time, and the schema stores input and expected output in the same
object, which makes the mismatch unrepresentable. The defect named in the
exclusion criteria does not survive into the seed file.

## 5. Provenance and permissions

Every corpus record carries `permission_status: "pending"`. This is accurate
and should stay that way until it isn't: **no permission was sought or granted
to redistribute LeetCode problem statements.** The corpus was assembled for an
internal engineering exercise.

Practical consequences for whoever inherits this:

- **Keep the repository private.** `scripts/seed_data.json` contains 50 full
  problem statements.
- **Do not publish the corpus** or ship it in a public artifact.
- If this ever becomes a product, the statements need replacing with
  originals or licensing — the pipeline is reusable, the text is not.

The field exists so nobody has to guess later what the status was. Do not
change it to `"granted"` without an actual grant to point at.

## 6. Archiving

The corpus is the expensive part to reproduce — it is a long throttled scrape
against an API that changes. Everything else in this project can be rebuilt
from source in minutes. **It currently exists on one laptop.**

Archive raw responses where they exist, the parsed records, and the provenance
fields, to storage independent of any single machine:

```bash
cd ~/corpus
tar czf glowingstar-corpus-$(date +%Y%m%d).tar.gz \
    LeetCode-Collector-final-Atharv-Madadi--main/

shasum -a 256 glowingstar-corpus-*.tar.gz > glowingstar-corpus-SHA256.txt
cat glowingstar-corpus-SHA256.txt
```

Upload the archive and the checksum file to `[VERIFY: Drive folder / bucket]`,
somewhere the next person can reach without asking. Record the checksum here
so a future download can be verified:

```
sha256: [PASTE AFTER ARCHIVING]
file:   glowingstar-corpus-YYYYMMDD.tar.gz
size:   [PASTE]
stored: [PASTE LOCATION]
```

Private storage only — see §5.
