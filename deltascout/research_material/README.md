# DeltaScout Local Research Materials

This directory is reserved for local-only DeltaScout research artifacts and server operations context.

Files in this directory are intentionally not published to the public repository, except for safe placeholders such as this README and `.example.md` templates.

## Public Repo Policy

- Do not store server hosts, SSH commands, absolute server paths, cron entries, or private operational prompts in tracked files here.
- Real local materials should live beside these templates as ignored files.

## Expected Local Files

Common local-only files:

- `RESEARCH_CONTEXT.md`
- `AGENTS.md`
- `runbooks/*.md`
- copied research artifacts, review bundles, raw archives, and local datasets

## Agent Routing

Local agents should read the local-only files in this directory when present.
If only placeholder files exist, assume the real operational context is not available in the current workspace.
