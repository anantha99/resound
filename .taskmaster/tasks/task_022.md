# Task ID: 22

**Title:** Squash and Clean Git Commit History

**Status:** pending

**Dependencies:** 16, 18, 19, 20

**Priority:** medium

**Description:** Clean the git commit history to present a professional, reviewable history without 'wip', 'fix', or 'ugh' commits as required by PRD §3.2.

**Details:**

Per PRD §3.2: "Commit history is presentable. Squash any 'wip', 'fix', 'ugh' commits before sharing."

1. **Audit current history:**
```bash
git log --oneline -50
```
Identify commits to squash or rename.

2. **Interactive rebase to clean history:**
```bash
git rebase -i HEAD~N  # where N is number of commits to review
```

Targeted commit structure:
- `feat: Initial Resound scaffold - pipeline, sources, classifier`
- `feat: Add Liquid Death brand bundle`
- `feat: Add Streamlit dashboard`
- `feat: Add OpenRouter classifier support`
- `feat: Add Ridge brand bundle`
- `docs: Add architecture diagrams and PRDs`
- `chore: Polish README for demo`

3. **Commit message style:**
- Use conventional commits: `feat:`, `fix:`, `docs:`, `chore:`
- Keep subject line under 72 chars
- No WIP, fix typo, or iterative commits visible

4. **Verify no sensitive data:**
```bash
git log -p | grep -i "api_key\|password\|secret"
```
If found, use `git filter-branch` or BFG to remove.

5. **Force push to private branch:**
```bash
git push origin main --force-with-lease
```

Note: Only do this on a private repo with no collaborators.

**Test Strategy:**

Verification:
- `git log --oneline` shows clean, professional commit messages
- No commits contain 'wip', 'fix typo', 'ugh', 'temp', 'asdf'
- Commit subjects are descriptive of changes
- No API keys or secrets in git history
- Total commit count is reasonable (5-15 commits)
