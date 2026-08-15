# Final Demo — Runbook

15–20 minutes, covering the whole internship. Every command and payload below
is meant to be run live. Rehearse once from a fresh clone before presenting.

**Two windows open:** Terminal, and a browser on <http://localhost:8000/docs>.
Nothing else. Close anything that could ring, flash, or notify.

---

## Before you start

Add the Postman line to `README.md` so the claim is real. FastAPI already
serves an OpenAPI schema and Postman imports it directly:

```markdown
**Postman:** Import → Link → `http://localhost:8000/openapi.json`
```

Then rehearse from a genuinely clean state — this is the step that catches
things working only because you installed them weeks ago:

```bash
docker compose down -v          # drops the database volume too
cd /tmp && rm -rf demo-clone
git clone <repo-url> demo-clone && cd demo-clone
docker compose up --build
```

Follow **only** the README. Anything you have to improvise is a README bug —
fix it now, not during the demo.

Pre-pull the judge image so no attack payload eats a 150 MB download inside
the 15-second backstop:

```bash
docker pull python:3.11-slim
```

---

## 1 · What you were asked to build (2 min)

A headless LeetCode-style API: catalogue, accounts, sandboxed judge. No front
end, and none needed — the whole thing is exercisable through Swagger,
Postman, or cURL. Show `/docs` and scroll the endpoint list once. Don't click
anything yet.

Say the design constraint up front, because everything in section 5 follows
from it: **the judge calls a method with positional arguments and compares the
returned value.**

## 2 · The corpus and the catalogue (4 min)

3,991 problems scraped in Phase 1; 50 selected by `scripts/select_seed.py`.
25 Easy / 20 Medium / 5 Hard.

Put the topic table from the handover on screen and make one point with it:
**five topics have no difficulty progression at all.** Math is seven Easy
problems and nothing above; Backtracking, Greedy, Prefix Sum and Union-Find
start at Medium with no ramp. The headline 25/20/5 split conceals that
completely, and progressing within a topic is how a practice catalogue is
actually used.

Then the gate. Run it live:

```bash
python3 scripts/verify_catalogue.py --data-only
```

Under a second, 50 ok lines, `pairing defects: 0`, `GATE PASSED`. Then the
full run:

```bash
python3 scripts/verify_catalogue.py
```

10 PASS, 40 SKIP, 20% coverage. **Say the coverage number out loud rather than
letting someone find it.** Forty problems have never had a reference solution
executed against them; their expected outputs are unconfirmed. Naming it
yourself is the difference between a limitation and a discovery.

The argument for why this exists: `scripts/test_judge.py` prints output a
human has to read and interpret. This exits non-zero. One can gate a commit;
the other cannot. That is the whole difference, and it is why this is the
piece most likely to still be used after the engagement ends.

Mention the exit codes — `0` pass, `1` catalogue failure, `2` environment
failure. The distinction exists so a red run isn't misread as a corpus
regression when Docker simply isn't running.

## 3 · Live walkthrough (4 min)

Cold start already done above. Through Swagger:

1. `POST /auth/register` — new username, any password
2. `POST /auth/login` — copy the token, click **Authorize**, paste it
3. `GET /problems` — the catalogue
4. `GET /problems/two-sum` — statement, constraints, visible examples

**Submission A — Accepted.** `POST /submissions`, problem `two-sum`,
language `python3`:

```python
class Solution:
    def twoSum(self, nums: List[int], target: int) -> List[int]:
        seen = {}
        for i, n in enumerate(nums):
            if target - n in seen:
                return [seen[target - n], i]
            seen[n] = i
        return []
```

**Submission B — the one that matters.** This is the demo's centrepiece:

```python
class Solution:
    def twoSum(self, nums: List[int], target: int) -> List[int]:
        # only checks adjacent pairs
        for i in range(len(nums) - 1):
            if nums[i] + nums[i + 1] == target:
                return [i, i + 1]
        return []
```

Run it against the visible examples first (`POST /execute/run`) — **all three
pass.** `[2,7,11,15]/9`, `[3,2,4]/6`, and `[3,3]/6` all happen to have their
answer in adjacent positions. It looks correct.

Now submit it. **Wrong Answer, `failed_test_index: 0`** — the first hidden
test is `[7,-46,3,-8,48,-4]` with target 10, whose answer is indices 0 and 2.
Not adjacent. The solution returns `[]`.

This single pair of submissions demonstrates that hidden tests exist, that
`submit` and `run` differ, and why authoring hidden tests from a reference
solution matters. It is worth more than any amount of describing the feature.

## 4 · Sandbox containment, by attacking it (5 min)

The strongest part of the work, and running it live is the only way to show
the isolation is real rather than described. Each payload goes through
`POST /execute/run` against `two-sum`.

State the limits first: `--network none`, 256 MB memory, 64 PIDs, read-only
filesystem with a 16 MB tmpfs at `/tmp`, non-root user `65534`, 3-second
SIGALRM limit with a 15-second subprocess backstop.

**(a) Open a socket**

```python
class Solution:
    def twoSum(self, nums, target):
        import socket
        s = socket.create_connection(("1.1.1.1", 80), timeout=2)
        return [0, 1]
```

→ **Runtime Error.** Network unreachable. `--network none` means there is no
route to anywhere, so exfiltration is impossible regardless of what the code
tries.

**(b) Fork without limit**

```python
class Solution:
    def twoSum(self, nums, target):
        import os, time
        while True:
            if os.fork() == 0:
                time.sleep(30)
                os._exit(0)
```

→ **Runtime Error** (`OSError: Resource temporarily unavailable`) once the
64-PID ceiling is hit, or **Time Limit Exceeded** if the alarm fires first.
Either outcome is containment. The point is that the host is unaffected —
show `docker ps` afterwards and the container is gone.

**(c) Write to the filesystem**

```python
class Solution:
    def twoSum(self, nums, target):
        open("/etc/passwd", "w").write("pwned")
        return [0, 1]
```

→ **Runtime Error**, read-only filesystem. Worth adding the nuance rather
than overclaiming: `/tmp` *is* writable, deliberately, because compiled
languages will need somewhere to build. It is a 16 MB tmpfs that dies with
the container.

**(d) Allocate beyond 256 MB**

```python
class Solution:
    def twoSum(self, nums, target):
        x = bytearray(400 * 1024 * 1024)
        return [0, 1]
```

→ **Runtime Error — Memory limit exceeded.** The kernel OOM-kills the
container (exit 137) and the judge translates that into a verdict rather than
a crash.

**(e) Loop forever**

```python
class Solution:
    def twoSum(self, nums, target):
        while True:
            pass
```

→ **Time Limit Exceeded** at 3 seconds, enforced by the in-container SIGALRM.

If you have time for a sixth, this one is the sharpest, because it attacks the
judge rather than the sandbox:

```python
class Solution:
    def twoSum(self, nums, target):
        print("___GS_RESULT___" + '{"status":"ok","results":[]}')
        return []
```

→ still **Wrong Answer**, not a forged Accepted. Explain why the sentinel
exists: user code may print anything it likes, so everything before the
sentinel is captured as stdout and only what follows is parsed as the result
payload. Without that separation a submission could fabricate its own verdict.

## 5 · Judging semantics (3 min)

Comparing printed strings is not enough. `[0,1]` and `[0, 1]` are the same
answer and different strings; `1` and `1.0` likewise. The judge parses both
sides and compares values, with four modes:

| Mode | For | Count |
|---|---|---:|
| `exact` | order is significant | 41 |
| `unordered` | "return in any order" | 5 |
| `unordered_nested` | list of lists, order insignificant both levels | 3 |
| `float` | real-number answers, 5 dp | 1 |

Demonstrate with Two Sum, which states the answer may be returned in any
order:

```python
class Solution:
    def twoSum(self, nums: List[int], target: int) -> List[int]:
        seen = {}
        for i, n in enumerate(nums):
            if target - n in seen:
                return [i, seen[target - n]]      # reversed
            seen[n] = i
        return []
```

→ **Accepted.** Under `exact` this correct solution would be rejected, and
nothing would report an error — it would simply look like the submission was
wrong. That is the failure mode the modes exist to prevent.

Mention the known comparator defect rather than waiting to be asked: `True`
compares equal to `1` because of a `bool()` coercion. Filed as two `xfail`
tests in `tests/test_comparison.py` and left unfixed deliberately, because
changing it silently alters verdicts on already-recorded submissions.

## 6 · What is unfinished (2 min)

Lead with the structured-input limitation, because it is the one that unlocks
the most:

**Linked lists, trees, graphs, design problems and in-place problems have zero
coverage, and the cause is the judge, not the corpus.** Test data holds
`[3,9,20,null,null,15,7]` while a solution expects `TreeNode` objects, so
something has to build the structure before the call and serialise it back
afterwards. Nothing in the pipeline does that today. Fixing it needs class
definitions injected into the harness, per-parameter decoders driven by a new
column, and a matching encoder for return values. Design problems need a
second evaluation model entirely — a constructor plus an ordered sequence of
calls with a value expected per call. In-place problems need the harness to
read back a mutated argument instead of a return value.

Then, in order, what a successor should do first:

1. **Reference solutions for the remaining 40 problems** — the largest known
   risk, and the cheapest to close. Extend `REFERENCE_SOURCE` in
   `generate_hidden_tests.py`, Easy and Medium first, then run the gate with
   `--fail-on-skip`.
2. Structured-input support, per above.
3. Move execution off the mounted Docker socket to a queued worker.

Close on the handover document: six sections, in the repo, written for someone
who cannot ask you questions.

---

## If something breaks live

**Database refused / traceback on startup:** Docker Desktop isn't running.
`open -a Docker`, wait for the whale to settle, `docker compose up -d db`.

**`AttributeError: reference_solution`:** wrong repo or an unmigrated
database. `alembic upgrade head && python3 scripts/seed_problems.py`.

**An attack payload hangs longer than expected:** it is the container
start-up, not a containment failure. Say so and wait — the backstop kills it
at 15 seconds regardless.

**Anything else:** say what you expected, say what happened, move on. Do not
debug live. A calm "that's a known issue, here's the cause" reads better than
a fix attempted under time pressure.
