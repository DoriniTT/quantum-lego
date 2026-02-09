# Issue Triage Workflow Fix

## Problem
The workflow was failing with:
```
fatal: not a git repository (or any of the parent directories): .git
Error: Process completed with exit code 128.
```

This happened because the "Configure Git credentials" step was running without first checking out the repository.

## Root Cause
The `gh aw compile` command generates a `.lock.yml` file that includes a git configuration step, but doesn't automatically add a repository checkout step for API-only workflows (like issue triage).

## Solutions Implemented

### Solution 1: Added Checkout Step (CURRENT)
**File**: `.github/workflows/issue-triage-agent.lock.yml` (line 96-99)

Added a checkout step before git configuration:
```yaml
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    persist-credentials: false
```

**Status**: ✅ Implemented
**Pros**: Fixes the immediate error
**Cons**: Manual edit to auto-generated file (will be overwritten if workflow is recompiled)

### Solution 2: Remove Git Config (ALTERNATIVE)
Since this workflow only uses GitHub API through MCP servers and doesn't need to:
- Commit files
- Push changes
- Access repository files

The git configuration step is unnecessary and can be removed entirely.

**To implement**: Comment out or remove lines 100-110 in the `.lock.yml` file.

## How to Maintain This Fix

### Option A: Keep Manual Checkout
After each `gh aw compile`, manually add the checkout step back before the git config step.

### Option B: Remove Git Config
Create a post-compile script:
```bash
#!/bin/bash
# Remove git config step from compiled workflow
sed -i '/Configure Git credentials/,/echo "Git configured/d' .github/workflows/issue-triage-agent.lock.yml
```

### Option C: Update Source Workflow
Investigate if there's a frontmatter option in the `.md` file to:
- Enable automatic repository checkout
- Disable git configuration for API-only workflows

## References
- Official gh-aw repo: https://github.com/github/gh-aw
- Documentation: https://github.github.io/gh-aw/
- Similar workflow: https://github.com/github/gh-aw/blob/main/.github/workflows/auto-triage-issues.lock.yml
