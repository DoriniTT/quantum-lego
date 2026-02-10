---
name: gh-aw-python-workflows
description: Best practices for creating and maintaining GitHub Agentic Workflows (gh-aw) for Python projects. Use this when asked to create, debug, or maintain gh-aw workflows in the quantum-lego project.
---

# GitHub Agentic Workflows - Python Project Best Practices

This skill document captures best practices for creating and maintaining GitHub Agentic Workflows (gh-aw) for Python projects, based on real-world experience with the quantum-lego project.

---

## Quick Reference

### Essential Commands

```bash
# Compile all workflows
gh aw compile

# Compile specific workflow
gh aw compile <workflow-name>

# Run workflow manually (enables if needed, then restores state)
gh aw run <workflow-name> --enable-if-needed

# Watch workflow run
gh run watch <run-id> --exit-status

# Check workflow status
gh run view <run-id> --json status,conclusion

# View workflow run summary
gh run view <run-id>

# View failure logs
gh run view <run-id> --log-failed
```

---

## Critical Requirements

### 1. **Always Include `contents: read` Permission**

**Without this, the workflow will fail with "fatal: not a git repository"**

```yaml
permissions:
  contents: read  # REQUIRED for actions/checkout step in compiled lock.yml
  issues: read    # Add other permissions as needed
  pull-requests: read
```

**Why:** The gh-aw compiler includes an `actions/checkout` step only when `contents: read` is present. Without it, git commands (`git sparse-checkout disable`, `git config`) fail.

### 2. **Include Sparse Checkout Disable Step**

```yaml
steps:
  - name: Disable sparse checkout
    run: |
      git sparse-checkout disable
      git checkout
```

**Why:** The compiled workflow initially checks out only `.github` and `.agents` folders (sparse). This step expands to full repository checkout.

### 3. **Use Local Imports for Shared Files**

```yaml
imports:
- shared/reporting.md  # LOCAL path, not external gh-aw repo
```

**Avoid:** `github/gh-aw/.github/workflows/shared/reporting.md@<SHA>`

**Why:** Keeps workflows self-contained and easier to maintain.

### 4. **Always Include `workflow_dispatch` Trigger**

```yaml
on:
  #schedule:
  #- cron: 0 12 * * 1-5
  workflow_dispatch:  # REQUIRED for manual triggering
```

**Why:** Allows manual testing and on-demand runs.

---

## Frontmatter Template for Python Projects

```yaml
---
name: Workflow Name
description: Brief description of what the workflow does
on:
  #schedule:
  #- cron: 0 12 * * 1-5
  workflow_dispatch:
permissions:
  contents: read
  issues: read
  pull-requests: read
network:
  allowed:
  - defaults
  - github
  - pypi  # Add if workflow needs PyPI access
imports:
- shared/reporting.md
steps:
  - name: Disable sparse checkout
    run: |
      git sparse-checkout disable
      git checkout
engine: copilot
strict: true
timeout-minutes: 20
tools:
  bash:
  - find . -name '*.py' ! -name 'test_*.py' ! -path '*/tests/*' ! -path '*/__pycache__/*' -type f
  - cat **/*.py
  - wc -l **/*.py
  - grep -r 'import|def|class' --include='*.py'
  - "pytest tests/ -m tier1 -v 2>&1 || true"
  - "flake8 quantum_lego/ --max-line-length=120 --ignore=E501,W503,E402,F401 2>&1 || true"
  edit: null  # or omit if editing not needed
  github:
    toolsets:
    - default
  serena:
  - python
safe-outputs:
  create-issue:
    title-prefix: "[workflow-name] "
    labels: [automated-analysis]
    max: 1
tracker-id: workflow-name-tracker
---
```

---

## Python-Specific Configurations

### Bash Tool Commands

**File Finding:**
```yaml
- find . -name '*.py' ! -name 'test_*.py' ! -path '*/tests/*' -type f
- find quantum_lego/ -maxdepth 2 -ls
- cat **/*.py
- wc -l **/*.py
```

**Code Search:**
```yaml
- grep -r 'def |class |import ' --include='*.py'
- grep -r 'print|console|rich' --include='*.py'
```

**Testing:**
```yaml
- "pytest tests/ -m tier1 -v 2>&1 || true"  # Fast pure Python tests
- "pytest tests/ -v 2>&1 || true"           # All tests
```

**Linting:**
```yaml
- "flake8 quantum_lego/ --max-line-length=120 --ignore=E501,W503,E402,F401 2>&1 || true"
```

**Package Management:**
```yaml
- cat pyproject.toml
- pip list
- pip show *
```

### Tools Configuration

**For code analysis workflows:**
```yaml
tools:
  bash:
  - <whitelist specific commands>
  edit: null  # or omit for read-only
  github:
    toolsets:
    - default
  serena:
  - python
```

**For code modification workflows:**
```yaml
tools:
  bash:
  - <whitelist>
  edit:  # Enable editing capability
  github:
    toolsets:
    - default
  serena:
  - python
```

**NEVER use:**
```yaml
bash:
  - "*"  # Security risk - allows arbitrary command execution
```

---

## Common Pitfalls & Solutions

### Issue 1: "fatal: not a git repository"

**Symptom:** Workflow fails in "Disable sparse checkout" or "Configure Git credentials" step

**Solution:** Add `contents: read` to permissions

```yaml
permissions:
  contents: read  # THIS IS REQUIRED
  issues: read
```

### Issue 2: Wrong Directory References

**Problem:** Referencing directories from other projects (`aiida_vasp/`, `src/`)

**Solution:** Use actual project structure

For quantum-lego:
- Package directory: `quantum_lego/`
- Tests directory: `tests/`
- Main modules: `quantum_lego/core/workgraph.py`, `quantum_lego/core/vasp_workflows.py`, etc.

**Wrong:**
```yaml
- find src/ -name '*.py'
- find aiida_vasp/ -name '*.py'
```

**Correct:**
```yaml
- find quantum_lego/ -name '*.py'
- find tests/ -name '*.py'
```

### Issue 3: Multi-Language References

**Problem:** Copy-pasting workflows from Go/JS/TS projects

**Solution:** Remove all non-Python language references

**Wrong:**
```markdown
For Go projects:
- make test-unit
- make build

For JavaScript/TypeScript:
- npm test
- npm run build
```

**Correct:**
```markdown
For quantum-lego (Python):
- pytest tests/ -m tier1 -v
- flake8 quantum_lego/ --max-line-length=120
- python -c 'import quantum_lego'
```

### Issue 4: Non-Workflow .md Files in workflows/ Directory

**Problem:** Compilation fails on documentation files like `WORKFLOW_FIX_NOTES.md`

**Solution:** Move documentation to `.github/` directory

```bash
mv .github/workflows/NOTES.md .github/NOTES.md
```

### Issue 5: Runtime Import of Non-Existent Files

**Problem:** `{{#runtime-import? .github/shared-instructions.md}}`

**Solution:** Remove runtime import directive or ensure file exists

---

## Project-Specific Patterns (quantum-lego)

### Package Structure
```
quantum_lego/              # Package root
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── workgraph.py       # Main workflow builder
│   ├── vasp_workflows.py
│   ├── qe_workflows.py
│   ├── dos_workflows.py
│   ├── results.py
│   ├── utils.py
│   ├── tasks.py
│   ├── console.py         # Rich terminal output
│   ├── bricks/            # 13 brick types
│   ├── calcs/             # Custom AiiDA calculations
│   └── common/            # Shared utilities
tests/                     # Test suite (498 tests)
examples/                  # Example scripts
```

### Import Order (PEP 8 + AiiDA)
```python
# 1. Standard library
import sys
from pathlib import Path

# 2. AiiDA
from aiida import orm
from aiida.engine import WorkChain

# 3. AiiDA-WorkGraph
from aiida_workgraph import WorkGraph, task

# 4. Third-party
import numpy as np
from pymatgen.core import Structure

# 5. quantum_lego
from quantum_lego.core.common.utils import get_logger
from quantum_lego import quick_vasp
```

### Testing
```bash
# Tier1: Pure Python (fast, no AiiDA)
pytest tests/ -m tier1 -v

# Tier2: AiiDA integration (no VASP)
pytest tests/ -m tier2 -v

# Tier3: Real VASP results
pytest tests/ -m tier3 -v

# All tests
pytest tests/ -v
```

### Linting
```bash
flake8 quantum_lego/ --max-line-length=120 --ignore=E501,W503,E402,F401
flake8 tests/ --max-line-length=120 --ignore=E501,W503,E402,F401
```

---

## Workflow Types & Example Configs

### 1. Issue Triage (API-only)

```yaml
permissions:
  contents: read  # Still needed despite being API-only
  issues: read
tools:
  github:
    toolsets: [issues, labels]
safe-outputs:
  add-labels:
    allowed: [bug, feature, enhancement, documentation]
  add-comment: {}
```

### 2. Code Analysis (Read-only)

```yaml
permissions:
  contents: read
  issues: read
tools:
  bash:
  - find . -name '*.py' -type f
  - cat **/*.py
  - grep -r 'pattern' --include='*.py'
  edit: null
  github:
    toolsets: [default]
  serena: [python]
safe-outputs:
  create-issue:
    title-prefix: "[analysis] "
    max: 1
```

### 3. Code Modification (Write access)

```yaml
permissions:
  contents: read
  issues: read
  pull-requests: read
tools:
  bash:
  - find . -name '*.py' -type f
  - "pytest tests/ -v 2>&1 || true"
  - "flake8 . 2>&1 || true"
  edit:  # Enable file editing
  github:
    toolsets: [default]
  serena: [python]
safe-outputs:
  create-pull-request:
    title-prefix: "[refactor] "
    labels: [refactoring, automated]
```

### 4. Package Analysis (Network access)

```yaml
permissions:
  contents: read
network:
  allowed:
  - defaults
  - github
  - pypi  # For PyPI package metadata
tools:
  bash:
  - cat pyproject.toml
  - pip show *
  - grep -r 'import|from' --include='*.py'
safe-outputs:
  create-discussion:
    category: general
    max: 1
```

---

## Shared Import Files

### shared/reporting.md

Standard formatting guidelines for issues/discussions:

```markdown
## Report Structure Guidelines

### 1. Header Levels
Use h3 (###) or lower for all headers in reports.

### 2. Progressive Disclosure
Wrap detailed content in <details><summary><b>Section</b></summary> tags.

### 3. Report Structure Pattern
1. Overview (visible)
2. Critical Information (visible)
3. Details (collapsible)
4. Context (collapsible)
```

### shared/mood.md

Team mode configuration:

```markdown
## Team Mood

We are in release mode, focusing on quality and stability. 
Skip any work that does not directly improve quality or stability.
```

---

## Verification Checklist

Before committing a new workflow:

- [ ] `name` and `description` fields present
- [ ] `contents: read` in `permissions`
- [ ] `workflow_dispatch` in `on` triggers
- [ ] `network` configured (if needed)
- [ ] Local `imports` (not external gh-aw repo)
- [ ] `steps` includes sparse checkout disable
- [ ] `timeout-minutes` set appropriately
- [ ] `strict: true` enabled
- [ ] `tracker-id` included (for cache/state tracking)
- [ ] Bash commands whitelisted (not `bash: ["*"]`)
- [ ] Python-specific commands (not Go/JS/TS)
- [ ] Correct directory references for quantum-lego
- [ ] No references to non-existent files
- [ ] `edit` tool included only if needed
- [ ] `safe-outputs` configured appropriately
- [ ] Compiles with `gh aw compile` (0 errors, 0 warnings)
- [ ] Runs successfully with `gh aw run --enable-if-needed`

---

## Testing Workflow

1. **Create/Edit .md file** in `.github/workflows/`
2. **Compile:** `gh aw compile <workflow-name>`
3. **Check compilation:** Look for 0 errors, 0 warnings
4. **Commit and push:**
   ```bash
   git add .github/workflows/<workflow-name>.{md,lock.yml}
   git commit -m "feat: add <workflow-name> workflow"
   git push
   ```
5. **Run workflow:**
   ```bash
   gh aw run <workflow-name> --enable-if-needed
   ```
6. **Monitor:**
   ```bash
   gh run watch <run-id>
   # or
   sleep 120 && gh run view <run-id> --json status,conclusion
   ```
7. **Verify success:**
   ```bash
   gh run view <run-id>
   ```
8. **Check logs if failed:**
   ```bash
   gh run view <run-id> --log-failed
   ```

---

## Working Examples from quantum-lego

All 8 workflows verified successfully:

| Workflow | Type | Duration | Key Features |
|----------|------|----------|--------------|
| issue-triage-agent | API + labels | ~1m15s | Issue labels, comments |
| daily-repo-status | GitHub API | ~2m2s | Repo activity reports |
| daily-file-diet | Serena + analysis | ~3m19s | File size analysis |
| semantic-function-refactor | Serena + issues | ~5m33s | Function clustering |
| terminal-stylist | Serena + analysis | ~5m14s | Console output patterns |
| typist | Serena + type analysis | ~6m23s | Type hint coverage |
| python-fan | PyPI + analysis | ~6m45s | Package usage review |
| code-simplifier | Edit + PR | ~4m10s | Code simplification |

---

## References

- **Project:** https://github.com/DoriniTT/quantum-lego
- **gh-aw Documentation:** https://github.github.io/gh-aw/
- **gh-aw Repository:** https://github.com/github/gh-aw
- **Troubleshooting:** `.github/WORKFLOW_TROUBLESHOOTING.md`

---

## Maintenance Notes

- Workflows are typically **disabled** by default
- Use `--enable-if-needed` flag to temporarily enable during manual runs
- The `depth` annotation warning in runs is benign (gh-aw internal issue)
- Permission denied errors for `/tmp/gh-aw/mcp-logs/` files are benign
- Frontmatter warnings in runtime imports are benign
- Always verify workflows compile before committing

---

**Last Updated:** 2026-02-10  
**Status:** All 8 workflows operational  
**Success Rate:** 100% (8/8)
