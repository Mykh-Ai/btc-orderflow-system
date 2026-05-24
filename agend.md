# Agent Permission Guidance

Agents should avoid asking for routine permissions that are safe and local to this repository.

Allowed without asking first:
- Read-only inspection: `git status`, `git diff`, `git log`, `rg`, file reads, line counts, and similar audit commands.
- Local workspace edits requested by the user, including creating or modifying project files with a clear task scope.
- Staging requested files when the user explicitly asks for it.
- Running local validation commands such as tests, linters, compile checks, and formatting checks.

Ask for explicit permission before:
- Deleting files, directories, branches, worktrees, or remote refs.
- Running destructive git commands such as reset, clean, restore, rebase, force push, or history rewrite.
- Pushing, opening pull requests, creating commits, or merging unless the user explicitly requested that exact action.
- Deploying, restarting services, changing production/server state, or running commands on a remote server.
- Installing dependencies, changing credentials/secrets, or performing network actions with side effects.

When unsure, prefer doing safe local read/edit/test work directly, and ask only for actions that can lose data, affect remote systems, or change shared history.
