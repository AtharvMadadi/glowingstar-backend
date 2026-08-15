# Corpus and Scraper

Where the problem data came from, how to reproduce it, and how to repair or
extend it. Written because the scraper is the least transferable part of this
work: documented, the corpus can be rebuilt; undocumented, it becomes a fixed
artifact nobody can add to.

Two values are marked `[TODO]` — fill them from `collect.py` before handover.
Everything else has been read off the source.

---

## 1. What exists

| Artifact | Location | Notes |
|---|---|---|
| Raw corpus | `~/corpus/LeetCode-Collector-final-Atharv-Madadi--main/problems_leetcode.jsonl.gz` | 3,991 records, gzipped JSONL, one problem per line |
| Collector source | same directory | not vendored into this repo |
| Run manifest | `run_manifest_leetcode.json` | provenance for the collection run |
| Checkpoint | `checkpoint_leetcode.json` | resume state for an interrupted run |
| Audit outputs | `corpus_audit_report.txt`, `corpus_audit_summary.json`, `coverage_report_leetcode.md` | Week 3 corpus audit |
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

Both scripts accept two shapes for `difficulty` and `tags` because the corpus
genuinely contains both — LeetCode's GraphQL responses are not uniform across
the record set. The dual handling is deliberate, not defensive padding.

## 2. Running the scraper

### Layout

| File | Responsibility |
|---|---|
| `collect.py` | orchestration; walks the problem list, fetches, normalises, writes JSONL |
| `graphql_client.py` | LeetCode GraphQL calls |
| `ratelimit.py` | pacing, retry, and backoff policy |
| `normalize.py` | HTML → text flattening, error-record construction |
| `schema_validate.py` + `coding_problem.schema.json` | per-record validation |
| `checkpoint.py` | resume state so an interrupted run continues |
| `manifest.py` | run provenance |
| `test_collector.py` | pytest suite, including rate-limiter behaviour |

### Dependencies

```
requests>=2.31
beautifulsoup4>=4.12
markdownify>=0.13
jsonschema>=4.21
pytest>=8.0
```

Python 3.12. No system packages, no browser driver, no headless Chrome.

### Running it

```bash
cd ~/corpus/LeetCode-Collector-final-Atharv-Madadi--main
pip install -r requirements.txt
python3 collect.py    # [TODO: paste the exact argument list from `python3 collect.py --help`]
```

Expected wall-clock for a full ~4,000-record run: **[TODO: from the run
manifest or your notes]**. It is deliberately slow — see pacing below.

### Authentication

**None.** `graphql_client.py` states plainly that it uses no session cookie, no
auth token, and no bypass of any kind. Everything collected is what an
unauthenticated visitor can see. This is why 776 records are metadata-only:
those problems are premium, their statements are paywalled, and the collector
does not attempt to reach them. Keep it that way — the absence of credentials
is what makes the provenance defensible.

### Rate limiting and retry

`ratelimit.py` implements conservative pacing with bounded retry:

- **Minimum interval** enforced between requests — one `RateLimitedClient`
  instance is one pacing lane.
- **Finite exponential backoff with jitter**, `base_backoff_seconds = 1.0`,
  `max_backoff_seconds = 60.0`. Finite, not unbounded: hitting the ceiling
  means stop and escalate, not push through.
- **`Retry-After` honoured** on 429 responses.
- **Retries only transient failures:** `{429, 500, 502, 503, 504}`, plus
  network errors and timeouts.
- **Never retries permanent access restrictions** — `401`, `403`, `404`, `410`
  raise immediately rather than being hammered. This is the distinction that
  keeps a scraper polite: a 403 means *you are not allowed*, and retrying it is
  the behaviour that gets a collector blocked.

Failures are recorded as structured error records (`normalize.py`) carrying
`stage`, `code`, `http_status`, `retryable`, and `attempts`, rather than being
silently dropped — so a partial run is auditable.

### Resumability

`checkpoint.py` writes `checkpoint_leetcode.json` as the run progresses. An
interrupted run resumes from the checkpoint rather than restarting. Delete the
checkpoint to force a clean run.

### What breaks

- **GraphQL schema drift.** Field names change without notice, and a rename
  surfaces as records missing a field rather than as an error. This is why
  `norm_difficulty()` and `norm_tags()` accept multiple shapes downstream.
- **Rate limiting.** LeetCode throttles. The client backs off and honours
  `Retry-After`, but a sustained 429 storm exhausts the finite backoff and the
  run stops — by design.
- **Premium problems.** 776 records are metadata-only and always will be
  without credentials.
- **HTML flattening.** Statements arrive as HTML and are flattened via
  BeautifulSoup + markdownify. This is where both defects in §4 come from.
  Anything relying on markup (`<sup>`, tables) degrades silently.

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
object, which makes the mismatch unrepresentable.

**Fix these upstream if the corpus is ever re-scraped.** Both are flattening
bugs in `normalize.py`, not data problems: substitute `<sup>` contents as `^N`
before stripping tags, and normalise U+00A0 to U+0020 at parse time. Fixing
them there makes `fix_corpus_defects.py` unnecessary for future runs.

## 5. Provenance and permissions

Every corpus record carries `permission_status: "pending"`. This is accurate
and should stay that way until it isn't: **no permission was sought or granted
to redistribute LeetCode problem statements.** The corpus was assembled for an
internal engineering exercise, without credentials, from publicly visible
pages only.

Practical consequences for whoever inherits this:

- **Keep the repository private.** `scripts/seed_data.json` contains 50 full
  problem statements.
- **Do not publish the corpus** or ship it in a public artifact.
- If this ever becomes a product, the statements need replacing with
  originals or licensing — the pipeline is reusable, the text is not.

Do not change the field to `"granted"` without an actual grant to point at.

## 6. Archiving

The corpus is the expensive part to reproduce — a long, deliberately throttled
scrape against an API that changes. Everything else in this project rebuilds
from source in minutes.

Archive created 14 August 2026:

```
file:   glowingstar-corpus-20260814.tar.gz
size:   7.5 MB
sha256: 3c9567ddbd83f3afccafef92d0ee98717ee051dc197153706d2ccf02ba64d671
stored: [PASTE DRIVE FOLDER LINK — private only, see §5]
```

Contents: the full collector directory — source, raw and gzipped JSONL,
checkpoint, run manifest, audit reports, and schema.

To verify a downloaded copy:

```bash
shasum -a 256 glowingstar-corpus-20260814.tar.gz
# must match the sha256 above
```

To create a fresh archive:

```bash
cd ~/corpus
tar czf glowingstar-corpus-$(date +%Y%m%d).tar.gz \
    LeetCode-Collector-final-Atharv-Madadi--main/
shasum -a 256 glowingstar-corpus-*.tar.gz > glowingstar-corpus-SHA256.txt
```
