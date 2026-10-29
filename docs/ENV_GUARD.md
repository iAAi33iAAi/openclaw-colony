# AETHEL Environment and Credential Guard

## What it checks

Run \`python aethel_env_guard.py ci\` to check the current Git index and review reachable Git history for environment-file names. The report contains filenames, rule identifiers, and line numbers only; it does not print source snippets or candidate values.

Run \`python aethel_env_guard.py precommit\` to check staged files before a local commit. Run \`python aethel_env_guard.py history\` to inspect historical env-file exposure. CI treats historical exposure as an advisory by default because deleting a file now cannot remove it from earlier commits; set \`AETHEL_ENV_GUARD_STRICT_HISTORY=1\` only when a repository intentionally requires history findings to block the build.

The credential-pattern scanner is heuristic. High-confidence token formats are checked throughout text. Key/value assignment checks are restricted to environment and configuration file formats to avoid interpreting normal application identifiers such as \`token\`, \`authorization\`, or \`secret\` as leaked credentials.

## Enable the local pre-commit hook

The hook source is versioned at \`.githooks/pre-commit\`, but Git does not activate it automatically. From the repository root, run once:

\`\`\`bash
git config core.hooksPath .githooks
\`\`\`

Verify it is enabled with:

\`\`\`bash
git config --get core.hooksPath
\`\`\`

The expected output is \`.githooks\`. This is a local Git setting and does not change another developer's local configuration.

## CI

The \`.github/workflows/env_guard.yml\` workflow runs the guard on pushes and pull requests to \`main\`, checks full history, and runs the guard regression tests. Its workflow permissions are read-only for repository contents, and the action revisions are pinned to full commit SHAs.

## Response to a finding

1. Do not copy the candidate value into an issue, PR, chat, terminal transcript, or log.
2. Determine privately whether it is a real credential. If real or uncertain, revoke or rotate it with the issuing service and provision its replacement through an approved secret manager or an untracked local environment.
3. Remove the sensitive file from the current Git tree and review reachable history, clones, forks, artifacts, and deployment copies.
4. Run the guard and relevant application tests again.

A clean current-tree scan is not proof that history or external copies are clean. History rewriting does not replace credential rotation. The guard is a defense-in-depth detector, not a secret manager and not a substitute for code review.
