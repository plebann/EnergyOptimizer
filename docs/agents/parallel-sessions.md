# Running agent sessions in parallel

Lessons from the Market Window Resolver epic (#69), where tickets #73–#78 and #88 were worked in parallel worktree sessions.

## Before starting a parallel batch

- **Check where PRs must land.** Run `gh pr list --state all --limit 15 --json number,baseRefName,state` and read the last merged PRs. Issue text can name a stale integration branch (here `feature/market-window-resolver`, while the work had moved to `main`). Name the PR base explicitly in every brief.
- **Cut every worktree from the branch the PRs will merge into.** Starting from a side branch (here the adapter branch) sent three PRs to that branch and one to `main`, which needed an extra merge PR with five conflicts.
- **Give each session a disjoint file list** and name the one session that owns any shared module. Say which functions inside a shared file belong to whom when two sessions must touch it.
- **Do not remove shared helpers in feature tickets.** Leave deletion to a single contract ticket after all readers have moved.

## What to put in each brief

- The issue number, the ADR to read, and the files the session may change and must not change.
- Test-first, full `pytest` green, no push of unrelated work, PR to the named base, `Closes #N`.
- Run `code-review` on the PR before reporting. Review caught real regressions in tickets that looked like pure refactors (lost negative sign on rounded averages, a gap computed from rounded prices, a bypassed restore guard, a wrong forecast horizon).
- Open the report with the verdict and any open question; notifications show only the first 400 characters.
- Design questions go to the user; the session must not pick a default and proceed.

## During and after

- Sessions cannot reply to or resolve GitHub review threads when the permission classifier blocks the write. Decide up front who answers threads: the user, or a setting that allows it.
- Merge in dependency order and rerun the full suite after each merge. Two PRs that edit different hunks of one file still need the second one checked for conflicts.
- A follow-up that a session defers (out of its file scope) becomes a GitHub issue before the session is archived.

## Cleanup

- Archive finished sessions first, then delete their worktree folders. On Windows a worktree folder held open by a live session cannot be removed (`Permission denied`), and the branch can be gone while the folder remains.
- Delete a local session branch only after its tip equals the head of its merged PR.
- Do not `cd` into a worktree folder you are about to delete; the shell's working directory then points at it.
