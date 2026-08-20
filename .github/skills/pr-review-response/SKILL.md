---
name: pr-review-response
description: Address GitHub pull request review comments end-to-end. Use when asked to check, respond to, resolve, or implement PR review feedback, including inline comments and review threads.
---

# PR Review Response

Use `gh` for all GitHub operations. Treat an addressed review thread as incomplete until it is resolved on GitHub.

1. Get all feedback, including inline comments:

   ```powershell
   gh pr view <pr-number> --repo <owner>/<repo> --json comments,reviews,reviewDecision
   gh api repos/<owner>/<repo>/pulls/<pr-number>/comments
   ```

2. For each actionable thread, inspect the referenced code and its tests. Make the smallest correct change, add or update a regression test when appropriate, and run the narrowest relevant validation.

3. Review the diff, commit, and push the change. Do not include unrelated worktree changes.

4. Reply to the original inline comment with the commit SHA and a concise explanation:

   ```powershell
   gh api --method POST repos/<owner>/<repo>/pulls/comments/<comment-id>/replies `
     -f body="Resolved in <sha>: <what changed>."
   ```

5. Resolve every addressed review thread. Retrieve the GraphQL thread ID by matching the original comment's `databaseId`, then call `resolveReviewThread`:

   ```powershell
   $query = 'query { repository(owner: "<owner>", name: "<repo>") { pullRequest(number: <pr-number>) { reviewThreads(first: 100) { nodes { id isResolved comments(first: 20) { nodes { databaseId } } } } } } }'
   gh api graphql -f query=$query

   $mutation = 'mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'
   gh api graphql -f query=$mutation
   ```

6. Verify `isResolved: true` before reporting completion. If a thread is blocked or the feedback is declined, do not resolve it; explain the reason in a reply and to the user.
