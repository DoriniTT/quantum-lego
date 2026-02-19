---
name: Tests Review
description: Reviews Tier 1, Tier 2, and Tier 3 test coverage, quality, and gaps across all bricks
engine: copilot
strict: true
timeout-minutes: 30
on:
  workflow_dispatch:
permissions:
  contents: read
  issues: read
  pull-requests: read
network:
  allowed:
  - defaults
  - github
imports:
- shared/reporting.md
steps:
  - name: Disable sparse checkout
    run: |
      git sparse-checkout disable
      git checkout
  - name: Install gh-aw for self-compilation
    run: gh extension install github/gh-aw 2>/dev/null || true
tools:
  bash:
  - find tests/ -name "*.py" -type f
  - find tests/ -name "*.json" -type f
  - cat tests/conftest.py
  - cat tests/fixtures/lego_reference_pks.json
  - cat pyproject.toml
  - cat .github/workflows/tests-review.md
  - gh aw compile tests-review
  edit:
  github:
    toolsets:
    - default
  serena:
  - python
safe-outputs:
  create-issue:
    title-prefix: "[tests-review] "
    labels: [review, testing, automated]
  create-pull-request:
    title-prefix: "[tests-review] "
    labels: [self-improvement, automated]
    reviewers:
    - copilot
tracker-id: tests-review
---
# Tests Review Agent

You are an expert test engineer analyzing the test suite of the quantum-lego Python library — a modular "brick" building system for AiiDA-based computational chemistry workflows (targeting VASP, Quantum ESPRESSO, and CP2K).

## Your Mission

Perform a comprehensive audit of all three test tiers:

- **Tier 1** (pure Python, ~420 tests, ~3 s) — unit tests with no AiiDA dependency
- **Tier 2** (AiiDA integration, ~48 tests, ~20 s) — WorkGraph construction with mock database
- **Tier 3** (end-to-end, ~30 tests) — result extraction against pre-computed VASP outputs

For each tier: assess test quality, identify coverage gaps per brick, and flag tests that belong in the wrong tier. Then produce a per-brick coverage matrix and a prioritized list of recommendations.

## Current Context

- **Repository**: ${{ github.repository }}
- **Workspace**: ${{ github.workspace }}

---

## Phase 1: Discover the Test Suite

### 1.1 List all test files and fixture files

```bash
find tests/ -name "*.py" -type f | sort
find tests/ -name "*.json" -type f | sort
```

### 1.2 Read pytest configuration

```bash
cat tests/conftest.py
cat pyproject.toml
```

From `conftest.py` note: registered markers (`tier1`, `tier2`, `tier3`, `requires_aiida`, `slow`, `localwork`, `obelix`), shared fixtures, and the AiiDA availability check pattern.

From `pyproject.toml` note: `[tool.pytest.ini_options]` settings, declared dependencies, and Python version requirements.

### 1.3 Read reference PKs for Tier 3

```bash
cat tests/fixtures/lego_reference_pks.json
```

Note all scenario keys and which brick types they cover.

---

## Phase 2: Read Source Context

Use Serena's `activate_project` tool with the workspace path (`${{ github.workspace }}`), then read:

- **`quantum_lego/core/__init__.py`** — the complete public API (all exported names, functions, classes)
- **`quantum_lego/core/bricks/__init__.py`** — the brick registry and resolver functions

Then list all brick files:

```bash
find quantum_lego/core/bricks/ -name "*.py" -type f | sort
```

Build a master list of all brick module names (e.g., `relax`, `static`, `dos`, `batch`, `aimd`, `neb`, `bader`, etc.). You will use this list throughout the review to check coverage.

---

## Phase 3: Tier 1 Test Review

Read every Tier 1 test file with Serena. The Tier 1 files cover:

- `test_lego_connections.py` — PORT/connection validation system
- `test_lego_bricks.py` — brick registry and `validate_stage()`
- `test_public_api.py` — public API importability
- `test_lego_results.py` — result extraction functions
- `test_lego_validation.py` — `_validate_stages()` orchestrator
- `test_lego_concurrent_and_outputs.py` — `max_concurrent_jobs` and output naming
- `test_workflow_utils.py` — workflow utility helpers
- `test_console.py` — console output and Rich formatting
- `test_eos_enhancements.py` — EOS / Birch-Murnaghan brick validation
- `test_hubbard_u_calculation.py` — Hubbard U LDAU array building (tier1 portion)

For each file, assess:

### Tier 1 Quality Checklist

- [ ] All test functions are decorated with `@pytest.mark.tier1`
- [ ] Test function names are descriptive (`test_<what>_<condition>_<expected>`)
- [ ] Assertions use specific values, not just truthiness
- [ ] Both happy paths and failure/edge cases are tested
- [ ] No AiiDA imports or fixtures that would make these tier2 tests
- [ ] No duplicated tests that are also present in tier2

### Tier 1 Coverage Gaps

For each brick in the master list, check whether its pure-Python logic is tested at tier1:
- `validate_stage()` called with valid and invalid inputs?
- Port type constants used in connections validated?
- Any pure parsing functions (e.g., Bader ACF parser) tested?

---

## Phase 4: Tier 2 Test Review

Read every Tier 2 test file with Serena:

- `test_lego_vasp_integration.py` — VASP brick WorkGraph construction
- `test_lego_dos_integration.py` — DOS brick WorkGraph construction
- `test_lego_batch_integration.py` — Batch brick WorkGraph construction
- `test_lego_aimd_integration.py` — AIMD brick calcfunctions and WorkGraph
- `test_lego_sequential_integration.py` — multi-stage pipeline construction
- `test_lego_aimd_trajectory_concatenation.py` — AIMD trajectory merging
- `test_hubbard_u_calculation.py` — Hubbard U tier2 portion

For each file, assess:

### Tier 2 Quality Checklist

- [ ] All test functions are decorated with `@pytest.mark.tier2` (or `pytestmark` at module level)
- [ ] `@pytest.mark.requires_aiida` is set where AiiDA profile access is required
- [ ] Tests use AiiDA mock fixtures (not real VASP runs) — no code labels or submission
- [ ] WorkGraph construction is tested (`.build()` or equivalent), not just object creation
- [ ] Intentional failure cases (e.g., exit code 302) are clearly commented as expected failures
- [ ] Fixtures clean up or use isolated AiiDA profiles

### Tier 2 Coverage Gaps

For each brick in the master list, check:
- Does a tier2 test exercise WorkGraph construction for this brick?
- Are all parameter combinations (e.g., `structure='input'` vs `structure_from`) tested?
- Are multi-brick sequential scenarios (brick A → brick B) tested?

---

## Phase 5: Tier 3 Test Review

Read every Tier 3 test file with Serena:

- `test_aimd_velocity_injection.py` — velocity injection with real VASP AIMD outputs
- `test_aimd_lvel_fix.py` — LVEL file handling regression

Also cross-check `tests/fixtures/lego_reference_pks.json`:

### Tier 3 Quality Checklist

- [ ] All test functions are decorated with `@pytest.mark.tier3`
- [ ] `@pytest.mark.localwork` or `@pytest.mark.obelix` set to indicate which compute resource
- [ ] Each test calls `load_node_or_skip(pk)` — never hard-fails if the PK is absent
- [ ] Reference PK descriptions in `lego_reference_pks.json` accurately describe the calculation (code label, INCAR settings)

### Tier 3 Coverage Gaps

Compare the scenario keys in `lego_reference_pks.json` against the master brick list:
- Which brick types have pre-computed reference calculations? (`vasp`, `dos`, `batch`, `aimd`, `sequential`)
- Which brick types have **no** tier3 reference at all (e.g., `neb`, `bader`, `hybrid_bands`)?
- Are the existing PKs still relevant to current brick interfaces? (Check that the fixture's `stage_types`, `stage_names`, and `stage_namespaces` match what the bricks currently produce)

---

## Phase 6: Cross-Tier Coverage Matrix

Build a table covering every brick in the master list against all three tiers:

| Brick | Tier 1 | Tier 2 | Tier 3 | Notes |
|---|---|---|---|---|
| `relax` | ✅ | ✅ | ✅ | Full coverage |
| `static` | ✅ | ✅ | ✅ | |
| `dos` | ⚠️ | ✅ | ✅ | Missing edge-case tier1 |
| `neb` | ❌ | ❌ | ❌ | No tests at any tier |
| ... | | | | |

Legend: ✅ covered · ⚠️ partial · ❌ missing

Identify:
- Bricks with **zero coverage** across all tiers (highest priority)
- Bricks covered only at tier1 but not validated in AiiDA context (tier2 gap)
- Bricks covered at tier1+tier2 but without an end-to-end reference calculation (tier3 gap)

---

## Phase 7: Self-Improvement Analysis

Before creating the issue, reflect on this run and identify what would make this workflow better on the next run. Your suggestions will be included in the issue body — **do not edit any files or create any pull requests**.

### 7.1 Read the current prompt

```bash
cat .github/workflows/tests-review.md
```

### 7.2 Identify what to improve

Based on what you encountered during this run, look for:
- Bash commands you needed but were not in the allowed tools list
- Instructions that were unclear, ambiguous, or caused you to backtrack
- Analysis phases that were redundant, missing, or could be reordered
- Context about the tier system or conftest fixtures that should be pre-stated
- Output format improvements based on what was awkward to produce

Only flag what genuinely needs improving. Do not suggest changing things that worked well.

Write your suggestions as a concise, actionable bullet list. You will include this list in the issue in Phase 8.

---

## Phase 8: Create GitHub Issue

Create one GitHub issue titled `"Tests Review — <today's date>"` with your complete findings.

Follow the `shared/reporting.md` formatting guidelines.

**Issue structure**:

```markdown
### Overview

[2-3 sentence summary of overall test suite health across all three tiers]

**Stats**:
- Tier 1 tests reviewed: ~420 (N test files)
- Tier 2 tests reviewed: ~48 (N test files)
- Tier 3 tests reviewed: ~30 (N test files)
- Bricks with zero coverage: N
- Bricks missing Tier 2: N
- Bricks missing Tier 3: N

### Coverage Matrix

| Brick | Tier 1 | Tier 2 | Tier 3 | Notes |
|---|---|---|---|---|
[... all bricks from master list ...]

<details>
<summary><b>Tier 1 Review</b></summary>

#### Quality Findings
[Per-file assessment: marker hygiene, naming, assertion quality, edge cases]

#### Coverage Gaps
[List of pure-Python logic paths with no tier1 test, with file:line references]

</details>

<details>
<summary><b>Tier 2 Review</b></summary>

#### Quality Findings
[Per-file assessment: AiiDA fixture usage, expected failures documented, WorkGraph coverage]

#### Coverage Gaps
[Bricks missing WorkGraph construction tests; parameter combinations not exercised]

</details>

<details>
<summary><b>Tier 3 Review</b></summary>

#### Quality Findings
[Assessment of load_node_or_skip usage, marker hygiene, PK descriptions]

#### Coverage Gaps
[Brick types with no reference PK; stale fixture entries that no longer match current interfaces]

</details>

<details>
<summary><b>Marker & Configuration Issues</b></summary>

[Tests missing tier markers; conftest fixtures that could be improved;
pyproject.toml test configuration suggestions]

</details>

### Recommendations (Prioritized)

1. **Critical**: [bricks with zero test coverage; broken tier3 fixtures]
2. **High**: [bricks covered only at tier1 with no AiiDA integration test]
3. **Medium**: [partial coverage, missing edge cases, unclear failure comments]
4. **Low**: [naming conventions, minor marker hygiene]

<details>
<summary><b>Workflow Self-Improvement Suggestions</b></summary>

[The bullet list you prepared in Phase 7 — specific, actionable suggestions for improving
`.github/workflows/tests-review.md` so the next run is faster and more thorough]

</details>

### Workflow Run

[workflow run link: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}]
```

## Important Guidelines

- **Be specific**: Include file paths and line numbers in all findings
- **Be actionable**: Every gap should have a concrete suggestion for what test to add
- **Be concise in summaries**: Put detail in collapsible `<details>` sections
- A brick with zero coverage at any tier is a gap, not necessarily a bug — state the risk clearly
- If you cannot read a file, note it clearly but continue the analysis

Begin your analysis now. Discover all test files, read the source context, review each tier, build the coverage matrix, analyze self-improvement opportunities, then create the review issue.
