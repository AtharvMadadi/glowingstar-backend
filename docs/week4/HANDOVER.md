# GlowingStar Backend — Handover

Atharv Madadi · August 2026 · written for a reader who has never seen this
codebase and cannot ask me questions.

The service is a headless LeetCode-style API: a problem catalogue, user
accounts, and a sandboxed judge that executes submitted Python and returns a
verdict. There is no front end and none is needed — everything is exercisable
through Swagger at `/docs`, Postman, or cURL.

Start here:

```bash
git clone <repo-url> && cd glowingstar-backend
docker compose up --build
```

Then open <http://localhost:8000/docs>. First boot waits for Postgres, applies
migrations, seeds 50 problems, pulls the judge runtime image, and starts
serving. `README.md` covers the API surface and the sandbox design; this
document covers everything that isn't obvious from reading the code.

---

## 1. Adding a problem

A problem is one row in the `problems` table. Nothing else needs to change —
no code, no migration, no restart. The fields that matter:

| Field | Notes |
|---|---|
| `slug` | unique, URL-safe; the public identifier |
| `title`, `difficulty` | `difficulty` is `Easy` / `Medium` / `Hard` |
| `description`, `constraints` | markdown; both must be non-empty |
| `tags` | JSON array of strings; drives catalogue filtering |
| `code_templates` | dict keyed by language; **`python3` is mandatory** |
| `sample_tests` | visible examples; at least one required |
| `hidden_tests` | optional; used by `submit` when present |
| `comparison` | one of `exact`, `unordered`, `unordered_nested`, `float` |
| `reference_solution` | optional but strongly recommended — see §4 |

### The two things that are easy to get wrong

**The entry-point method name is derived from the Python template, not
stored.** `app/judge.py:method_name()` regexes `def (\w+)\(self` out of
`code_templates["python3"]`. If that template is missing or malformed, every
submission for that problem fails with a `JudgeError` rather than a verdict.
This is why the verification gate checks it explicitly.

**Test cases are positional arguments as raw strings.** Each entry in
`sample_tests` / `hidden_tests` looks like:

```json
{
  "args_raw": ["[2,7,11,15]", "9"],
  "expected": "[0,1]",
  "display_input": "nums = [2,7,11,15], target = 9",
  "explanation": "Because nums[0] + nums[1] == 9, we return [0, 1]."
}
```

`args_raw` is a list of one string per parameter, in declaration order.
`parse_args()` runs each through `ast.literal_eval`, falling back to a stripped
string if that fails. `expected` is a single string parsed the same way. There
is no named-argument support and no type coercion beyond `literal_eval`.
`display_input` and `explanation` are presentation only — the judge ignores
both.

Because input and expected output live in the *same object*, they cannot fall
out of sync by count. That is deliberate: a positional pairing mismatch was one
of the defects found in the Phase 1 corpus, and this schema makes it
unrepresentable rather than merely validated.

### Choosing a comparison mode

The judge compares a parsed return value, not a printed string. Pick the
weakest mode that is still correct — a mode that is too strict rejects correct
submissions, and nothing reports an error when it does.

| Mode | Use when | Behaviour |
|---|---|---|
| `exact` | order is significant | direct equality |
| `unordered` | the statement says "in any order" | outer list sorted before comparing |
| `unordered_nested` | list of lists, order insignificant at both levels | both levels sorted |
| `float` | the answer is a real number | rounded to 5 decimal places |

Two Sum is the canonical case: it says "you can return the answer in any
order", so a correct solution returning `[1,0]` must be Accepted. Under `exact`
it would not be. Conversely, Pascal's Triangle returns a list of lists where
row order *is* significant, so `exact` is correct there despite the shape
suggesting otherwise — the gate raises a warning on that combination rather
than a failure, precisely because the shape alone cannot decide it.

Current distribution across the 50: `exact` 41, `unordered` 5,
`unordered_nested` 3, `float` 1.

**Known comparator defect.** `outputs_match()` coerces with `bool()` when
either side is a boolean, so `True` compares equal to `1` and `False` to `0`.
Filed as two `xfail` tests in `tests/test_comparison.py` rather than fixed,
because changing it silently alters verdicts on already-recorded submissions.
Fix it deliberately, with a re-verification run, not as a drive-by.

### Authoring hidden tests

`submit` evaluates against `hidden_tests` when the array is non-empty and falls
back to `sample_tests` otherwise. This is what makes `submit` different from
`run`, and it is the difference a demo should show.

Do **not** hand-write expected outputs. `scripts/generate_hidden_tests.py` is
the pipeline: it holds a reference solution per problem in `REFERENCE_SOURCE`,
`exec()`s it to get a live `Solution` class, generates inputs, and computes
expected outputs by *running* that solution. The same source string is then
stored into `reference_solution`, so the code that computed the expected
answers is byte-for-byte the code the gate later re-submits through the live
judge. There is no second hand-synced copy anywhere.

Generated outputs are round-tripped through the real
`parse_args → parse_expected → outputs_match` path before being written, which
catches stringification mismatches at authoring time rather than at judging
time. The RNG is seeded (`20260807`), so regenerating reproduces identical
tests.

Inputs are generated where the shape permits and hand-constructed for edge
cases: empty, single element, duplicates, boundary values, maximum constraints.
Two Sum's generator additionally brute-forces uniqueness, because its own
constraints promise exactly one valid answer and a naively random array can
violate that.

**The ordering constraint that matters:** a reference solution must pass the
existing visible samples before its generated outputs can be trusted. Samples
are the independent anchor. Without that check you are asserting that a
solution is correct on the grounds that it agrees with itself.

To add a problem end to end:

```bash
# 1. add the record to scripts/seed_data.json
# 2. optionally add a reference solution + generator to generate_hidden_tests.py
python3 scripts/generate_hidden_tests.py     # only if you did step 2
python3 scripts/seed_problems.py             # idempotent, matches on slug
python3 scripts/verify_catalogue.py --slug <your-slug>
```

`seed_problems.py` updates existing rows rather than duplicating, and will not
clobber authored `hidden_tests` with an empty list.

---

## 2. Adding a language harness

Starter templates are served for Python, Java, and C++. **Execution is
implemented for Python 3 only.** Other languages return `400` with an
explanatory message rather than failing opaquely — see `SUPPORTED` in
`app/judge.py` and `_load()` in `app/routers/execute.py`.

The judging, comparison, and persistence layers are already
language-agnostic. What is Python-specific is one thing: the harness.

### What the harness does

`HARNESS` in `app/judge.py` is a Python source template with four
placeholders — `__USER_CODE__`, `__PAYLOAD__`, `__LIMIT__`, `__SENTINEL__`.
Filled in and piped to the container on stdin, it:

1. installs a `SIGALRM` handler and arms it for the time limit,
2. instantiates `Solution` and looks up the entry-point method by name,
3. calls it once per test case with the parsed arguments spread positionally,
4. records the return value and per-case elapsed milliseconds,
5. writes a sentinel line followed by one JSON blob to stdout.

The sentinel matters. User code is free to print whatever it likes; everything
before `___GS_RESULT___` is returned as `stdout` and everything after is the
result payload. Without it, a submission printing JSON could forge a verdict.

### Steps to add a language

1. **Runtime image.** Pick one and make it configurable the way `JUDGE_IMAGE`
   already is. Do not install a toolchain into the API image — the whole point
   is that execution happens in a disposable container.
2. **Write the harness in the target language.** Same contract: read a payload,
   call the entry point once per case, emit `SENTINEL` + JSON with the same
   shape (`{"status": ..., "results": [{"ok": bool, "value": ..., "ms": int}]}`).
   Deserialising the payload and serialising return values is most of the work,
   and it is where the two-level JSON encoding in `run_in_docker()` will bite
   you if you skim it.
3. **Compiled languages need a build step inside the container.** Python's
   `python -` reads a program from stdin; `javac` and `g++` do not. You will
   need to write to the tmpfs at `/tmp` (16 MB, `exec` enabled) and compile
   there, and you must distinguish compile failure from runtime failure to
   keep the `Compile Error` verdict meaningful. Budget for the compile in the
   backstop: `BACKSTOP_S` is `TIME_LIMIT_S + 12`, which is sized for container
   start-up alone.
4. **Entry-point derivation.** `method_name()` regexes the *Python* template.
   Generalise it per language, or store the method name as a column. The
   column is the better answer; the regex was a shortcut.
5. **Widen `SUPPORTED`** in `app/judge.py`. The router's 400 disappears on its
   own once the language is in that set.
6. **Verify before believing it.** Add the language to the gate and run every
   reference solution through it.

The isolation flags in `run_in_docker()` are language-independent and should
not be relaxed for a new runtime. If a language appears to need more memory or
more PIDs, treat that as a claim to be tested, not a given.

---

## 3. What the catalogue contains

50 problems, selected from a 3,991-record Phase 1 corpus by
`scripts/select_seed.py` and bundled into `scripts/seed_data.json`.

### Difficulty split

25 Easy / 20 Medium / 5 Hard. Quota-filled by design after filtering; the
remaining candidates were ranked by popularity.

### Topic distribution

26 distinct tags. Difficulty by topic:

| Topic | Easy | Medium | Hard | Total |
|---|---:|---:|---:|---:|
| Array | 14 | 16 | 4 | 34 |
| Hash Table | 10 | 5 | 1 | 16 |
| Dynamic Programming | 6 | 6 | 1 | 13 |
| String | 7 | 5 | 1 | 13 |
| Two Pointers | 4 | 4 | 1 | 9 |
| Binary Search | 3 | 4 | 1 | 8 |
| Sorting | 5 | 3 | 0 | 8 |
| Math | 7 | 0 | 0 | 7 |
| Bit Manipulation | 4 | 1 | 0 | 5 |
| Stack | 2 | 0 | 2 | 4 |
| Backtracking | 0 | 3 | 0 | 3 |
| Divide and Conquer | 1 | 1 | 1 | 3 |
| Monotonic Stack | 1 | 0 | 2 | 3 |
| Sliding Window | 0 | 1 | 2 | 3 |
| Greedy | 0 | 2 | 0 | 2 |
| Prefix Sum | 0 | 2 | 0 | 2 |
| Union-Find | 0 | 2 | 0 | 2 |
| Breadth-First Search | 0 | 1 | 0 | 1 |
| Counting | 1 | 0 | 0 | 1 |
| Depth-First Search | 0 | 1 | 0 | 1 |
| Heap (Priority Queue) | 0 | 0 | 1 | 1 |
| Matrix | 0 | 1 | 0 | 1 |
| Memoization | 1 | 0 | 0 | 1 |
| Monotonic Queue | 0 | 0 | 1 | 1 |
| Queue | 0 | 0 | 1 | 1 |
| Simulation | 1 | 0 | 0 | 1 |

Problems carry multiple tags, so the column totals exceed 50.

**The headline 25/20/5 split conceals the thing that actually limits this
catalogue as a practice tool: five topics have no difficulty progression at
all.** Math is seven Easy problems and nothing above. Backtracking, Greedy,
Prefix Sum and Union-Find start at Medium with no ramp. Progressing *within* a
topic is how a practice catalogue is used, and only Array supports it with real
depth. Nine further tags have exactly one problem, so filtering on them returns
a single result.

The tag vocabulary was audited for near-duplicates from inconsistent
capitalisation or pluralisation (`array` / `Array` / `arrays`). **There are
none** — tags come through from LeetCode's `topicTags` already canonical. No
normalisation migration was needed, so none was written.

### Topics that are absent

**Linked lists, trees, graphs, design/iterator problems, and in-place
problems have zero coverage.** Between them that is a large share of what
technical interviews actually cover.

The cause is the judge, not the corpus. `select_seed.py` filtered these out
because the judge passes positional arguments and compares a return value, and
none of these categories fit that shape. The Phase 1 corpus contains plenty of
all five. **This is not a data-sourcing problem and re-scraping will not fix
it** — §5 explains what would.

---

## 4. Data quality

### The command

```bash
python3 scripts/verify_catalogue.py
```

Two passes. **Data validation** checks, per problem: statement, constraints and
examples populated; at least one visible test; every test carrying both an
input and an expected output; a valid comparison mode consistent with the shape
of the expected output; and a derivable entry point. **Execution** loads each
problem's stored `reference_solution` and runs it through the live judge —
real Docker container, real comparator — against its hidden tests, falling back
to samples where no hidden tests exist.

It exits **non-zero if anything fails**, so it can gate a commit or a deploy
rather than requiring someone to read output. Exit codes: `0` pass, `1`
catalogue failure, `2` environment failure (database unreachable, etc.) — the
distinction exists so a red run isn't misread as a corpus regression when
Docker simply isn't running.

Useful invocations:

```bash
python3 scripts/verify_catalogue.py --data-only          # seconds, no judge containers
python3 scripts/verify_catalogue.py --slug two-sum       # one problem, repeatable flag
python3 scripts/verify_catalogue.py --difficulty Easy
python3 scripts/verify_catalogue.py --fail-on-skip       # coverage becomes mandatory
```

Requires Postgres up and seeded. `--data-only` still needs the database — what
it skips is launching a judge container per problem.

### The two design decisions

**Problems with no reference solution are skipped, not failed.** Ten of fifty
have one. Failing on the other forty would make the gate red from its first run
and it would be ignored inside a week. Skips are counted and reported as a
coverage figure instead. `--fail-on-skip` is the switch to throw once the set
is complete — that is the intended end state, not a permanent exemption.

**Subset runs are supported.** The execution pass costs roughly a second of
container start-up per problem, which is slow enough that nobody runs it while
iterating. `--data-only` takes under a second and catches most authoring
mistakes. A gate is only useful if it is cheap enough to run often.

### What it found

| | |
|---|---|
| Data validation passed | 50 / 50 |
| Input / expected-output pairing defects | **0** |
| Data warnings | 1 |
| Verified against a reference solution | **10 / 50 (20%)** |
| Execution failures | 0 |
| Skipped for want of a reference solution | 40 |

The pairing-defect count is zero for two independent reasons, both worth
knowing: `select_seed.py` filtered mismatched candidates out of the corpus at
selection time, and the schema stores input and expected output in the same
object, which makes a count mismatch unrepresentable. The defect named in the
exclusion criteria does not survive into the seeded set.

The single warning is `pascals-triangle`: `comparison=exact` on a
list-of-lists output. Reviewed and correct — row order is significant. The
warning exists because shape alone cannot decide it and a human should confirm.

### What was fixed, and what remains unverified

Fixed: the `reference_solution` column and migration `15692071288d` landed,
`generate_hidden_tests.py` was committed (previously only its output was), and
`verify_task5.py` was rewritten to read reference solutions from the database
rather than carrying a duplicated hardcoded copy.

**Unverified: 40 of 50 problems have never had a reference solution executed
against them.** Their statements, tests and metadata are structurally valid,
but nothing has confirmed that their expected outputs are actually correct. A
wrong expected output produces a Wrong Answer verdict on a correct submission
and nothing reports an error. **This is the largest known risk in the
catalogue and closing it is the highest-value next task.** Extend
`REFERENCE_SOURCE` in `generate_hidden_tests.py`, staying with Easy and Medium
problems — Hard ones turn the work into an algorithm exercise rather than a
verification one.

The comparator boolean-coercion defect (§1) also remains open by choice.

---

## 5. Why the catalogue is 50 problems

The judge does exactly one thing: it calls a method with positional arguments
and compares the returned value. Everything the catalogue is missing follows
from that single design choice, and this section exists so a successor starts
from the explanation rather than inferring it from the code.

### How would a linked list or tree get into the judge?

The test data holds a flat array — `[3,9,20,null,null,15,7]` — while the
solution signature expects `Optional[TreeNode]`. Something has to build the
structure before the call and, for problems that return a structure, turn it
back into an array afterwards.

Nothing in the current pipeline can do that. `parse_args()` runs
`ast.literal_eval` and hands the result straight to the method; it produces a
Python list, and a list is not a `TreeNode`. There is also no `TreeNode` or
`ListNode` class anywhere — on LeetCode those are ambient in the execution
environment, and this judge has no equivalent.

Where would the code sit? Inside the harness, before and after the call — that
is the only place with access to both the parsed arguments and the live class
definitions. Concretely it needs three things:

1. **Class definitions injected into the harness**, alongside the `typing` and
   `collections` imports already there. They must match LeetCode's exactly,
   because user code will construct and traverse them.
2. **Per-parameter deserialisers**, driven by a new column. `args_raw` is
   currently untyped strings; the harness would need to know that argument 0 of
   this problem is a level-order tree encoding and argument 1 is a plain
   integer. Level-order-with-nulls, linked list, and array-of-lists are each a
   distinct decoder.
3. **A matching serialiser for return values**, because a returned `TreeNode`
   has to become `[3,9,20,null,null,15,7]` again before the comparator can
   touch it. `outputs_match()` compares parsed JSON-ish values and would
   otherwise be handed an object with an unstable `repr`.

That is a schema change plus a harness rewrite, and it multiplies per language:
every harness needs its own copy of the classes and both codecs. It is the
single change that would unlock the most problems — linked lists, trees, and
graphs together are a large fraction of the interview canon and of the
excluded corpus.

### How would a design problem be judged?

A design problem's test is not one call. It is a constructor plus an ordered
sequence of method calls with an expected value for each:

```
["LRUCache", "put", "put", "get", "put", "get"]
[[2],        [1,1], [2,2], [1],   [3,3], [2]]
→ [null, null, null, 1, null, -1]
```

This is a different evaluation model, not a variation on the current one. The
current harness resolves one method by name and calls it once per case; here
the object persists across calls, the method varies per call, and the verdict
is a per-call comparison over a sequence.

What it needs: a second test-case shape carrying parallel operation and
argument arrays, a second harness path that constructs the object once and
dispatches by name in order, and a comparator that walks two sequences and
reports the *first* divergent index — since "returned the right thing on call
7 but wrong on call 3" is the useful failure message. `null` for void-returning
methods needs to compare successfully rather than being treated as a missing
value.

None of that is unreasonable, but it is a parallel judging path with its own
comparator semantics. It should be built as a second mode with explicit
dispatch, not bolted onto the existing one — trying to make one code path serve
both is how you get a judge nobody trusts.

### How would an in-place problem be judged?

Here the solution returns nothing. `removeDuplicates(nums)` mutates its
argument and returns a length; the answer lives in the caller's array
afterwards, sometimes only in its first `k` positions.

The judge has no way to see this. The harness records `_fn(*_args)` — the
return value — and a `None` return compares equal to nothing useful. The mutated
argument is never read back.

The fix is small in principle and awkward in practice. The harness would need
to capture the argument list *after* the call and compare that instead of, or
alongside, the return value. That requires a per-problem declaration of what to
check: which argument index holds the answer, and whether only a prefix of it
counts. The prefix case is the awkward part — for these problems the expected
output is "the first `k` elements, where `k` is what you returned", so the
check depends on the submission's own return value. That is a genuinely
different assertion shape, and encoding it needs its own field rather than
being inferable from the data.

`select_seed.py` filters these under `void-return`, which is the right call for
the current judge: a problem whose answer the judge cannot observe would
silently accept every submission.

---

## 6. Known limitations

Each with the intended fix.

**Docker socket mount.** `docker-compose.yml` mounts `/var/run/docker.sock`
into the API container so it can launch judge containers, which grants the API
effective root on the host. Fine for a locally-run MVP, unacceptable anywhere
else. *Fix:* move execution to a dedicated worker service with a queue between
it and the API, or use gVisor/Firecracker isolation, so the API never touches
the daemon.

**~1 second of container start-up per execution.** Every submission pays it.
*Fix:* a warm pool of pre-started containers, or a persistent worker that
forks per submission behind the same isolation flags.

**SIGALRM timeout with a subprocess backstop.** The 3-second limit is enforced
inside the container by a signal handler that user code can catch and swallow;
`BACKSTOP_S` (15s) exists to kill the container when it does. Two mechanisms
where one would be better. *Fix:* enforce the limit externally via the
container runtime and drop the in-process alarm.

**No concurrency ceiling or rate limiting on the execute endpoints.** Any
authenticated user can trigger unbounded concurrent container launches; enough
of them will exhaust host memory regardless of the per-container cap. *Fix:* a
semaphore around `run_in_docker()` plus per-user rate limiting at the router.

**No pagination or search on the catalogue endpoint.** `GET /problems` returns
all matching rows. Harmless at 50, not at 4,000. *Fix:* limit/offset with a
default page size, and a text search parameter over title and slug.

**Re-seeding cascades into submission history.** `submissions` has
`ON DELETE CASCADE` on `problem_id`; deleting and re-creating a problem takes
its submission history with it, and solved state is derived from that history,
so users silently lose progress. `seed_problems.py` updates in place and avoids
this, but nothing prevents a destructive reseed. *Fix:* soft-delete problems
instead of removing rows.

**Python-only execution.** Templates for Java and C++ are served; only
`python3` executes. *Fix:* §2.

**40 of 50 problems unverified.** No reference solution has been executed
against them, so their expected outputs are unconfirmed. *Fix:* extend
`REFERENCE_SOURCE` in `generate_hidden_tests.py`, Easy and Medium first, then
run the gate with `--fail-on-skip`.

**Hidden tests exist for 10 problems.** The other 40 fall back to visible
samples on `submit`, which means `submit` and `run` are equivalent for them and
a submission that overfits the examples passes. *Fix:* same as above — the
generator produces both from one reference solution.

**Comparator coerces booleans.** `True` compares equal to `1`. Two `xfail`
tests in `tests/test_comparison.py` document it. *Fix:* compare types before
values, and re-run the gate afterwards, since it can change recorded verdicts.

**The gate's execution pass does not run in CI.** `.github/workflows/tests.yml`
runs the data half only; the execution half needs a mounted Docker socket,
which a hosted runner should not be given — and giving it one would contradict
the first limitation in this list. *Fix:* run the full gate locally before
tagging a release, or stand up a self-hosted runner if that becomes routine.

---

## Appendix — running things

```bash
# local development
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db
alembic upgrade head
python3 scripts/seed_problems.py
fastapi dev app/main.py

# verification
python3 scripts/verify_catalogue.py            # the gate
python3 scripts/test_judge.py                  # judge smoke test, all verdicts
pytest tests/ -v                               # comparator unit tests

# regenerating data
python3 scripts/export_seed_data.py            # corpus -> seed_data.json
python3 scripts/generate_hidden_tests.py       # reference solutions -> hidden tests
```

Postman: **Import → Link → `http://localhost:8000/openapi.json`**

`export_seed_data.py` expects the Phase 1 corpus outside the repository, at
`~/corpus/LeetCode-Collector-final-Atharv-Madadi--main/problems_leetcode.jsonl.gz`.
Adjust the `CORPUS` path at the top of that file if it lives elsewhere. It is
only needed to rebuild `seed_data.json` from scratch; normal operation does
not touch the corpus.
