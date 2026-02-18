---
name: Examples Review
description: Reviews, improves recommendations for, and better organizes the 10-category example suite using GitHub Copilot
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
  - find examples/ -name "*.py" -type f
  - find examples/ -name "*.md" -type f
  - "cat examples/**/*.py"
  - "cat examples/_shared/*.py"
  - ls examples/
  - cat docs/QUICK_START.md
  - cat .github/workflows/examples-review.md
  - gh aw compile examples-review
  edit:
  github:
    toolsets:
    - default
  serena:
  - python
safe-outputs:
  create-issue:
    title-prefix: "[examples-review] "
    labels: [review, examples, automated]
  create-pull-request:
    title-prefix: "[examples-review] "
    labels: [self-improvement, automated]
    reviewers:
    - copilot
tracker-id: examples-review
---
# Examples Review Agent

You are an expert code reviewer analyzing the `examples/` directory of the quantum-lego Python library — a modular "brick" building system for AiiDA-based computational chemistry workflows (targeting VASP, Quantum ESPRESSO, and CP2K).

## Your Mission

Review the entire examples directory and create a GitHub issue summarizing:
- Code quality and API alignment across all examples
- Documentation completeness within examples
- Logical organization of the 10-category structure
- Missing examples for key bricks
- State of `examples/README.md` and `examples/_shared/`

## Current Context

- **Repository**: ${{ github.repository }}
- **Workspace**: ${{ github.workspace }}

## Phase 1: Discover the Examples

### 1.1 List All Categories and Files

```bash
ls examples/
find examples/ -name "*.py" -type f | sort
find examples/ -name "*.md" -type f | sort
```

Expected categories:
- `01_getting_started/` — first calculation tutorials
- `02_dos/` — density of states
- `03_batch/` — parallel batch calculations
- `04_sequential/` — multi-stage workflows
- `05_convergence/` — convergence testing
- `06_surface/` — surface analysis
- `07_advanced_vasp/` — advanced DFT
- `08_aimd/` — molecular dynamics
- `09_other_codes/` — Quantum ESPRESSO and CP2K
- `10_utilities/` — utility and tooling demos
- `_shared/` — shared config and structure helpers

### 1.2 Read Representative Files

Use Serena's `read_file` tool to read the actual content of:
- At least the first file from each category
- All files in `examples/_shared/`
- `examples/README.md` (if it exists)
- `docs/QUICK_START.md` for API context

Also activate the Serena project first using `activate_project` with the workspace path.

## Phase 2: Review Each Category

For each category directory, assess:

### Code Quality Checklist
- [ ] Correct imports (using current public API from `quantum_lego.core`)
- [ ] Consistent coding style (PEP 8, 120-char lines)
- [ ] No deprecated or broken API calls
- [ ] Variables and functions clearly named

### Documentation Checklist
- [ ] Module-level docstring explaining what the example demonstrates
- [ ] Prerequisites stated (AiiDA profile, VASP binary, etc.)
- [ ] Inline comments where logic is non-obvious

### Organization Checklist
- [ ] Category name is appropriate for the examples it contains
- [ ] No examples placed in the wrong category
- [ ] No categories that should be merged or split

## Phase 3: Identify Missing Examples

Check which important bricks have no example. Particularly look for missing examples for:
- `bader.py` — Bader charge analysis
- `neb.py` — nudged elastic band
- `hybrid_bands.py` — hybrid functional band structure
- `formation_enthalpy.py` — formation enthalpy
- `fukui_analysis.py` — Fukui function / reactivity

Use Serena to check `quantum_lego/core/bricks/` for bricks that have no corresponding example:
```bash
find quantum_lego/core/bricks/ -name "*.py" -type f | sort
```

## Phase 4: Review Shared Utilities

Read and assess:
- `examples/_shared/config.py` — shared configuration helpers
- `examples/_shared/structures.py` — shared structure definitions

Check for:
- Completeness (covers common use cases)
- Correctness (no outdated patterns)
- Usage (are they actually imported in examples?)

## Phase 5: Check examples/README.md

Does `examples/README.md` exist?
- If **yes**: is it complete and accurate? Does it list all categories with descriptions?
- If **no**: note that it should be created as an index

## Phase 6: Create GitHub Issue

Create one GitHub issue titled `"Examples Review — <today's date>"` with your complete findings.

Follow the `shared/reporting.md` formatting guidelines.

**Issue structure**:

```markdown
### Overview

[2-3 sentence summary of overall examples health]

**Stats**:
- Categories reviewed: 10
- Total example files: N
- Examples with missing docstrings: N
- Bricks missing examples: N

<details>
<summary><b>Category-by-Category Review</b></summary>

#### 01_getting_started/
- **Files**: list them
- **Code quality**: ✅ Good / ⚠️ Issues / ❌ Broken
- **Documentation**: ✅ / ⚠️ / ❌
- **Notes**: specific observations

#### 02_dos/
[same structure...]

[continue for all 10 categories]

</details>

<details>
<summary><b>Missing Examples</b></summary>

| Brick | File | Priority |
|---|---|---|
| Bader analysis | `bader.py` | High |
| NEB | `neb.py` | High |
[...]

</details>

<details>
<summary><b>Shared Utilities (_shared/)</b></summary>

[assessment of _shared/config.py and _shared/structures.py]

</details>

<details>
<summary><b>examples/README.md Status</b></summary>

[exists/missing, complete/incomplete, what needs updating]

</details>

### Recommendations (Prioritized)

1. **Critical**: [most urgent fixes]
2. **High**: [important improvements]
3. **Medium**: [nice-to-have changes]
4. **Low**: [minor polish]

### Workflow Run

[workflow run link]
```

## Important Guidelines

- **Be specific**: Include file paths and line numbers in findings
- **Be actionable**: Every issue should have a clear recommendation
- **Be concise in summaries**: Put details in collapsible `<details>` sections
- If a category directory is empty or missing, note it clearly
- If you cannot read a file, note it but continue the analysis

## Phase 7: Self-Improve This Workflow

After completing all review phases and creating the issue, reflect on this run and improve this workflow's own prompt file so the next run is better.

### 7.1 Read the current prompt

```bash
cat .github/workflows/examples-review.md
```

### 7.2 Identify what to improve

Based on what you encountered during this run, look for:
- Bash commands you needed but were not in the allowed tools list
- Instructions that were unclear, ambiguous, or caused you to backtrack
- Analysis phases that were redundant, missing, or could be reordered
- Context about the repo structure that should be pre-stated in the prompt
- Output format improvements based on what was awkward to produce
- Anything that made this run slower or less thorough than it could have been

Only improve what genuinely needs improving. Do not change things that worked well.

### 7.3 Apply targeted edits

Use the edit tool to update `.github/workflows/examples-review.md` directly.
Keep edits focused and purposeful — this is not a full rewrite.

### 7.4 Regenerate the lock file (optional)

Attempt to regenerate `examples-review.lock.yml` from the updated prompt:

```bash
gh aw compile examples-review
```

If the command is unavailable or fails, skip this step — note it in the PR body and the reviewer can run it after merge. Do **not** attempt any `git add`, `git commit`, or `git push` commands — those are not available in this environment.

### 7.5 Create a self-improvement pull request

Call `create_pull_request` directly. The safe_outputs job automatically commits all edits you made via the edit tool and opens the PR — you do not need to run any git commands yourself.

PR body must include:
- A bullet list of exactly what changed in the prompt and why
- Whether `gh aw compile` succeeded or needs to be run manually after merge
- A note confirming this was generated from run `${{ github.run_id }}`

Begin your analysis now. Discover files, read representative examples, assess each category, create the review issue, then self-improve this workflow.
