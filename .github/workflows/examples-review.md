---
name: Examples Review
description: Reviews, improves recommendations for, and better organizes the 10-category example suite using GitHub Copilot
engine: copilot
strict: true
timeout-minutes: 20
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
tools:
  bash:
  - find examples/ -name "*.py" -type f
  - find examples/ -name "*.md" -type f
  - "cat examples/**/*.py"
  - "cat examples/_shared/*.py"
  - ls examples/
  - cat docs/QUICK_START.md
  edit: null
  github:
    toolsets:
    - default
  serena:
  - python
safe-outputs:
  create-issue:
    title-prefix: "[examples-review] "
    labels: [review, examples, automated]
    max: 1
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

- **Read-only**: Do not modify any files — only analyze and report
- **Be specific**: Include file paths and line numbers in findings
- **Be actionable**: Every issue should have a clear recommendation
- **Be concise in summaries**: Put details in collapsible `<details>` sections
- If a category directory is empty or missing, note it clearly
- If you cannot read a file, note it but continue the analysis

Begin your analysis now. Discover files, read representative examples, assess each category, and create a comprehensive GitHub issue with your findings.
