---
description: Initialize git repo and push to GitHub for the first time (one-time bootstrap)
---

# GitHub Repository Initialization

One-time workflow to initialize the local git repository and push to a new GitHub remote.
This is the **only** time a direct commit to `main` is permitted (see pr-workflow.md).

## Prerequisites

- The GitHub repository must already exist (created via github.com UI)
- The remote repo should be **empty** (no README, no .gitignore, no license from GitHub)
- You must know the GitHub org/user and repo name (e.g., `tedg-cisco/omnibor-analysis`)

## 1. Confirm with user before proceeding

**Ask the user:**
- What is the GitHub remote URL? (e.g., `https://github.com/tedg-cisco/omnibor-analysis.git`)
- Has the empty repo been created on GitHub?
- Are they ready to make the initial commit?

**Do NOT proceed without explicit user confirmation.**

## 2. Initialize git

```bash
git init
```

## 3. Stage all tracked files

```bash
git add .
```

## 4. Verify what will be committed

```bash
git status
```

**Pause and show the user the staged files list.** Confirm nothing unexpected is staged
(no credentials, no large repo clones, no output artifacts). The .gitignore should
handle this, but verify.

## 5. Create the initial commit

```bash
git commit -m "feat: initial project structure"
```

## 6. Set the default branch to main

```bash
git branch -M main
```

## 7. Add the GitHub remote

```bash
git remote add origin <REMOTE_URL>
```

Replace `<REMOTE_URL>` with the URL confirmed in step 1.

## 8. Push to GitHub

```bash
git push -u origin main
```

## 9. Verify

```bash
git log --oneline -1
git remote -v
```

## After Initialization

From this point forward, **all changes must follow the PR-first workflow**:
- Create a feature branch (`feat/`, `fix/`, `docs/`, `chore/`, `test/`)
- Make changes on the branch
- Push the branch
- Open a PR
- Merge only with explicit user approval

The initial commit to `main` is the only permitted exception.
