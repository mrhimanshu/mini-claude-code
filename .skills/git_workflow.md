---
description: Git workflow conventions and commit practices
---

# Git Workflow Skill

## Commit Messages
- Use conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- First line: imperative mood, max 72 chars
- Body: explain WHY, not WHAT

## Branch Naming
- Feature: `feat/short-description`
- Fix: `fix/issue-number-description`
- Refactor: `refactor/what-changed`

## Before Committing
1. Run `git status` to review changes
2. Run `git diff` to verify all changes are intentional
3. Stage only related changes together
4. Never commit `.env`, credentials, or secrets
5. Run tests if available

## Pull Requests
- Title matches the primary commit message
- Description includes: Summary, What Changed, How to Test
- Keep PRs small and focused
