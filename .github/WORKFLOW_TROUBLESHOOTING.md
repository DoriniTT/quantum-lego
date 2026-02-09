# GitHub Agentic Workflows - Troubleshooting Guide

## Issue: "fatal: not a git repository" Error

### Problem Description

When running the issue triage agent workflow, it failed with:

```
Run git config --global user.email "github-actions[bot]@users.noreply.github.com"
fatal: not a git repository (or any of the parent directories): .git
Error: Process completed with exit code 128.
```

Additionally, artifact download failed:
```
Unable to download artifact(s): Artifact not found for name: agent-output
Please ensure that your artifact is not expired and the artifact was uploaded using a compatible version of toolkit/upload-artifact.
```

**Workflow Run**: Manually triggered February 9, 2026 12:44
**Status**: ❌ Failure (1m 1s duration)
**Commit**: `1beca17` on `main` branch

### Root Cause

The `gh aw compile` command generates a `.lock.yml` file that includes a "Configure Git credentials" step (line ~100-110) but **does not automatically add a repository checkout step** for API-only workflows like issue triage.

#### Why This Happens

1. The workflow tries to run `git config --global user.email`
2. Git commands require a `.git` directory to exist
3. No `actions/checkout` step was present before the git config
4. Result: Git fails, workflow exits early
5. Artifact upload never happens (workflow exits before that step)
6. Conclusion job tries to download non-existent artifact

### Understanding .git in GitHub Actions

**Key Concept**: The `.git` directory is local by design:
- **Local repositories**: Have `.git` directory with full history
- **Remote repositories (GitHub)**: Store data differently on server
- **GitHub Actions runners**: Start with empty workspace
- **Requires**: Explicit `actions/checkout` to clone repo and create `.git`

Each GitHub Actions runner is a fresh VM. Without checkout, there's no repository, no `.git` directory, and git commands fail.

---

## Solutions Implemented

### ✅ Solution 1: Added Checkout Step (CURRENT FIX)

**File**: `.github/workflows/issue-triage-agent.lock.yml` (line 96-99)

```yaml
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    persist-credentials: false
- name: Configure Git credentials
  # ... git config commands ...
```

**Status**: ✅ Implemented in commit `395c22b`
**Pros**:
- Fixes the immediate error
- Allows git commands to work
- Matches pattern from official gh-aw workflows

**Cons**:
- Manual edit to auto-generated file
- Will be overwritten if workflow is recompiled with `gh aw compile`

### 🔄 Solution 2: Remove Git Config (ALTERNATIVE)

Since the issue triage workflow:
- Only uses GitHub API through MCP servers
- Doesn't commit files
- Doesn't push changes
- Doesn't need to access repository files

**The git configuration step is unnecessary** and can be removed entirely.

**To implement**:
1. Remove lines 100-110 from `.lock.yml` (the "Configure Git credentials" step)
2. Or create a post-compile script:

```bash
#!/bin/bash
# scripts/fix-workflow-after-compile.sh
sed -i '/Configure Git credentials/,/echo "Git configured/d' \
  .github/workflows/issue-triage-agent.lock.yml
echo "✓ Removed unnecessary git config step"
```

---

## Research Findings

### Official gh-aw Documentation

**Sources**:
- [GitHub Agentic Workflows Documentation](https://github.github.io/gh-aw/)
- [gh-aw Repository](https://github.com/github/gh-aw)
- [GitHub Next Project](https://githubnext.com/projects/agentic-workflows/)

**Key Points**:
- Workflows transform natural language markdown into GitHub Actions
- AI agents run in containerized, sandboxed environments
- Default permissions are read-only
- Write operations require explicit safe-outputs configuration

### Official Workflow Comparison

**File**: `github/gh-aw/.github/workflows/auto-triage-issues.lock.yml`

The official auto-triage workflow includes this sequence:
1. ✅ Checkout actions folder (sparse)
2. Setup Scripts
3. ✅ **Checkout repository** (full)
4. Create gh-aw temp directory
5. Configure Git credentials

Our workflow was missing step #3.

---

## Maintenance Guide

### When Recompiling Workflows

After running `gh aw compile .github/workflows/issue-triage-agent.md`, you must:

#### Option A: Re-add Checkout (Recommended)
```bash
# After compile, manually edit .lock.yml to add checkout before git config
# See line 96-99 in the current version
```

#### Option B: Use Post-Compile Script
```bash
# Create scripts/post-compile-fix.sh
#!/bin/bash
set -e

WORKFLOW_FILE=".github/workflows/issue-triage-agent.lock.yml"

# Check if workflow was just compiled
if [ -f "$WORKFLOW_FILE" ]; then
  # Add checkout step before git config
  # This uses sed to insert the checkout step

  # Find line with "Configure Git credentials"
  LINE=$(grep -n "Configure Git credentials" "$WORKFLOW_FILE" | cut -d: -f1)

  if [ -n "$LINE" ]; then
    # Insert checkout step before it
    sed -i "${LINE}i\\      - name: Checkout repository\\n        uses: actions/checkout@v4\\n        with:\\n          persist-credentials: false" "$WORKFLOW_FILE"
    echo "✓ Added checkout step to $WORKFLOW_FILE"
  fi
fi
```

#### Option C: Remove Git Config Entirely
```bash
# If you don't need git operations, remove the step after compile
scripts/fix-workflow-after-compile.sh
```

### Workflow Configuration Best Practices

#### Current `.md` Configuration
```yaml
---
timeout-minutes: 5
strict: true
engine: claude
on:
  schedule: "0 14 * * 1-5"
  workflow_dispatch:
permissions:
  issues: read
imports:
  - shared/reporting.md
  - shared/mood.md
tools:
  github:
    toolsets: [issues, labels]
safe-outputs:
  add-labels:
    allowed: [bug, feature, enhancement, documentation, question, help-wanted, good-first-issue]
  add-comment: {}
---
```

**Engine Options**:
- `claude` - Uses Anthropic Claude (requires `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`)
- `copilot` - Uses GitHub Copilot (requires GitHub Copilot subscription)
- `openai` - Uses OpenAI (requires `OPENAI_API_KEY`)

---

## Files Structure

```
.github/
├── workflows/
│   ├── issue-triage-agent.md          # Source workflow definition
│   ├── issue-triage-agent.lock.yml    # Compiled workflow (auto-generated)
│   ├── WORKFLOW_FIX_NOTES.md          # Quick reference for this fix
│   └── shared/
│       ├── reporting.md                # Shared reporting guidelines
│       └── mood.md                     # Shared mood/tone guidelines
├── WORKFLOW_TROUBLESHOOTING.md        # This file
└── scripts/                            # (optional) Post-compile scripts
    └── post-compile-fix.sh
```

---

## Testing the Fix

### Manual Test
```bash
# Push changes
git push origin main

# Manually trigger workflow
gh workflow run issue-triage-agent.lock.yml

# Watch the run
gh run watch
```

### Check Workflow Status
```bash
# List recent runs
gh run list --workflow=issue-triage-agent.lock.yml

# View specific run details
gh run view <run-id>
```

### Expected Success Output
```
✓ Checkout repository
✓ Configure Git credentials
✓ Validate CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY secret
✓ Execute Claude Code CLI
✓ Upload agent artifacts
```

---

## Secrets Required

Ensure these secrets are configured in repository settings:

| Secret Name | Required | Purpose |
|------------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes (if using Claude) | Anthropic Claude API access |
| `CLAUDE_CODE_OAUTH_TOKEN` | Alternative | Claude Code OAuth token |
| `GITHUB_TOKEN` | Auto-provided | GitHub API access (read-only) |
| `GH_AW_GITHUB_TOKEN` | Optional | GitHub API access (write permissions) |

**Check secrets**:
```bash
gh secret list
```

---

## Common Issues & Solutions

### Issue: Artifact Not Found
**Cause**: Workflow fails before artifact upload
**Solution**: Fix the underlying workflow error (like missing checkout)

### Issue: Permission Denied
**Cause**: Insufficient permissions in workflow
**Solution**: Check `permissions:` in frontmatter, add `contents: read`

### Issue: MCP Server Timeout
**Cause**: Network issues or rate limiting
**Solution**: Check `MCP_TIMEOUT` and `MCP_TOOL_TIMEOUT` env vars

### Issue: No Issues Triaged
**Cause**: No unlabeled issues, or issues already assigned
**Solution**: Normal behavior - workflow skips labeled/assigned issues

---

## Additional Resources

### Documentation
- [GitHub Actions Checkout Action](https://github.com/actions/checkout)
- [GitHub Agentic Workflows Guide](https://github.github.io/gh-aw/)
- [Claude Code Documentation](https://docs.anthropic.com/claude/docs/claude-code)

### Example Workflows
- [Official Issue Triage](https://github.com/github/gh-aw/blob/main/.github/workflows/issue-triage-agent.md)
- [Auto-Triage Issues](https://github.com/github/gh-aw/blob/main/.github/workflows/auto-triage-issues.md)
- [PR Triage Agent](https://github.com/github/gh-aw/blob/main/.github/workflows/pr-triage-agent.md)

### Community
- [gh-aw GitHub Issues](https://github.com/github/gh-aw/issues)
- [GitHub Community Discussions](https://github.com/orgs/community/discussions)

---

## Changelog

### 2026-02-09 - Initial Fix
- **Problem**: Workflow failing with "fatal: not a git repository"
- **Solution**: Added checkout step before git configuration
- **Commit**: `395c22b` - "Fix issue triage workflow git repository error"
- **Files Modified**:
  - `.github/workflows/issue-triage-agent.lock.yml` (added checkout)
  - `.github/workflows/issue-triage-agent.md` (updated format, added Claude engine)
  - Created `.github/workflows/shared/` directory
  - Created `.github/workflows/WORKFLOW_FIX_NOTES.md`
  - Created `.github/WORKFLOW_TROUBLESHOOTING.md` (this file)

---

## Quick Reference Commands

```bash
# Compile workflow from markdown
gh aw compile .github/workflows/issue-triage-agent.md

# After compile, verify checkout step exists
grep -A3 "Checkout repository" .github/workflows/issue-triage-agent.lock.yml

# If missing, re-add manually at line ~96-99 before "Configure Git credentials"

# Test workflow
gh workflow run issue-triage-agent.lock.yml
gh run watch

# Check logs if failed
gh run view --log-failed
```

---

**Last Updated**: 2026-02-09
**Maintained By**: Project Team
**Related Issues**: GitHub Actions workflow failures, gh-aw compilation
