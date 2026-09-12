---
name: github-pr-workflow
description: >
  Use this skill when creating a GitHub pull request, preparing a PR description,
  reviewing an existing PR, processing review comments, applying requested changes,
  replying to comments, resolving addressed review threads, or preparing a PR for merge.
compatibility: Requires git and GitHub CLI (gh) authenticated for the repository. Resolving review threads requires GitHub API permissions to update pull request review threads.
---

# GitHub pull request workflow

## General rules

- Work only in the current repository and current PR branch.
- Inspect repository conventions before changing files.
- Never push, create a PR, submit a review, post a comment, or resolve a review thread without explicit user approval.
- Never claim that CI or tests passed unless the command was actually executed.
- Keep replies factual, concise, and tied to the requested change.
- Do not expose tokens, credentials, private URLs, or local filesystem paths.
- Treat every review comment as unresolved until it has been classified and handled explicitly.
- Never resolve a thread classified as `disagreement`.
- Resolve a non-disagreement thread only after the requested change or explanation is complete and verified.
- If classification is uncertain, classify the thread as `disagreement` and leave it unresolved.

## Before creating a PR

1. Check the current branch and working tree:
   - `git status --short --branch`
   - `git diff`
   - `git diff --cached`
2. Inspect recent commit style:
   - `git log -8 --oneline`
3. Identify the base branch:
   - `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`
4. Run focused tests, lint, formatting, and type checking.
5. Review the final diff.
6. Prepare:
   - concise title;
   - summary of behavior change;
   - test commands and results;
   - breaking changes;
   - follow-up risks.

## Creating a PR

- Do not create the PR until the user approves the final title and body.
- Prefer a focused PR with one logical change.
- Use `gh pr create` only after approval.
- Include exact tests that were run.
- Do not include claims about tests that were not run.

## Reviewing a PR

1. Identify the PR:
   - `gh pr view <number> --json title,body,baseRefName,headRefName,author,files,reviews,statusCheckRollup`
2. Fetch the branch or inspect the PR diff:
   - `gh pr diff <number>`
3. Read relevant files and tests, not only the diff.
4. Run relevant tests if the workspace allows it.
5. Classify findings:
   - blocker;
   - correctness;
   - regression;
   - test gap;
   - maintainability;
   - documentation.
6. Report findings with:
   - severity;
   - file and line;
   - problem;
   - impact;
   - concrete fix.
7. Do not submit `APPROVE` or `REQUEST_CHANGES` without explicit approval.

## Processing review comments

1. Fetch review comments:
   - `gh api repos/{owner}/{repo}/pulls/{number}/comments`
2. Fetch general review bodies:
   - `gh api repos/{owner}/{repo}/pulls/{number}/reviews`
3. Fetch review-thread metadata, including whether each thread is resolved, when available.
4. Group every thread into exactly one category:
   - `actionable` — a concrete requested change that should be implemented;
   - `question` — a question requiring an answer or clarification;
   - `already addressed` — the current code already satisfies the comment;
   - `obsolete` — the comment no longer applies because the code or diff changed;
   - `disagreement` — a reasonable technical or design difference where the proposed change is not clearly required or the author chooses not to implement it.
5. For each non-disagreement thread:
   - inspect the current code and the full thread;
   - implement the smallest correct fix or provide a direct explanation;
   - add or update tests where applicable;
   - run targeted checks;
   - prepare a reply;
   - after the reply is posted and the result is verified, resolve the thread.
6. For each `disagreement` thread:
   - do not change the implementation merely to silence the comment;
   - do not resolve the thread;
   - write a reply explaining the exact point of disagreement;
   - state the current implementation and the requested alternative;
   - explain the technical reasoning, trade-offs, evidence, or project convention supporting the chosen approach;
   - if useful, invite a decision or ask the reviewer for additional constraints.
7. Do not post replies, resolve threads, push commits, or submit reviews without explicit user approval.

## Resolution policy

Use this policy after the requested implementation and verification:

| Category | Implement change | Reply | Resolve automatically after approval |
|---|---:|---:|---:|
| `actionable` | Usually yes | Required | Yes |
| `question` | Only if needed | Required | Yes |
| `already addressed` | No | Required | Yes |
| `obsolete` | No or only if needed | Required | Yes |
| `disagreement` | No, unless separately agreed | Required with reasoning | Never |

A thread is eligible for resolution only when:

- its category is not `disagreement`;
- the implementation or explanation is complete;
- relevant checks were run;
- the proposed reply accurately describes the result;
- the user approved posting the reply and resolving the thread.

If the GitHub API cannot resolve a particular thread, report the exact failure and leave it unresolved. Do not simulate resolution by claiming it was completed.

## Reply format

For an implemented change:

> Addressed in `<short commit or file reference>`. I changed `<what changed>` and verified it with `<exact command>`. Resolving this thread.

For a question:

> Good point. `<direct answer>`. I `<changed / did not change>` `<area>` because `<reason>`. Resolving this thread.

For an already addressed comment:

> This is already covered by `<file, behavior, or test>`. I verified it with `<exact command>`. Resolving this thread.

For an obsolete comment:

> This is no longer applicable because `<current code or diff change>`. The current behavior is covered by `<test or implementation>`. Resolving this thread.

For a disagreement:

> I understand the concern about `<reviewer’s proposal>`. The current implementation uses `<current approach>`, while the suggested alternative is `<alternative approach>`. I kept the current approach because `<technical reasoning, project convention, evidence, or trade-off>`. The main trade-off is `<trade-off>`. I am leaving this thread open because this is a design disagreement rather than an addressed action item.

Do not write `Resolving this thread` in a disagreement reply.

## Publishing and resolving

Before any external action, prepare a review package containing:

1. PR number and repository.
2. Commit or files changed.
3. One proposed reply per thread.
4. The selected category for each thread.
5. Exact test and validation results.
6. Threads that will be resolved.
7. Threads classified as disagreement and intentionally left open.
8. Any push, review, comment, or API operation requiring approval.

After explicit approval:

1. Push the changes if approved.
2. Post replies using the exact approved text.
3. Resolve only threads whose category is not `disagreement`.
4. Verify the resulting thread state through the GitHub API.
5. Report any failed or skipped operation.

Do not use a blanket resolve operation. Resolve threads individually after validating their category.

## Final report

Return:

1. PR or comment context.
2. Files changed.
3. Review comments addressed.
4. Category assigned to every thread.
5. Replies posted.
6. Threads resolved.
7. Disagreement threads left open, including the reason for each.
8. Tests and checks run.
9. Unresolved comments or risks.
10. Actions requiring approval.