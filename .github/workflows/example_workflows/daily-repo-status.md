---
name: Daily Repo Status
description: |
  Creates daily repo status reports with productivity insights,
  community highlights, and project recommendations.
engine: copilot
strict: true
timeout-minutes: 15
on:
  #schedule:
  #- cron: 0 8 * * 1-5
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
  github:
    toolsets:
    - default
safe-outputs:
  create-issue:
    title-prefix: "[repo-status] "
    labels: [report, daily-status]
    max: 1
tracker-id: daily-repo-status
---

# Daily Repo Status

Create an upbeat daily status report for the repo as a GitHub issue.

## What to include

- Recent repository activity (issues, PRs, discussions, releases, code changes)
- Progress tracking, goal reminders and highlights
- Project status and recommendations
- Actionable next steps for maintainers

## Style

- Be positive, encouraging, and helpful 🌟
- Use emojis moderately for engagement
- Keep it concise - adjust length based on actual activity

## Process

1. Gather recent activity from the repository
2. Study the repository, its issues and its pull requests
3. Create a new GitHub issue with your findings and insights
