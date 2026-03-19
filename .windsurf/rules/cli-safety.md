---
title: CLI Command Safety & Performance
trigger: always_on
---

# Terminal Constraints
- **NO HANGING COMMANDS**: Do not run commands that exceed 30 seconds of expected execution time.
- **RESTRICT SEARCH SCOPE**: Never run `grep`, `find`, or `ls -R` from the project root without excluding `node_modules`, `.git`, and build folders.
- **CHUNK EXECUTIONS**: If you need to process many files, list them first and process in chunks of 5 using a loop or xargs with limits.
- **VERBOSE OUTPUT**: Always append `| head -n 20` to commands that might produce thousands of lines of output to prevent the Windsurf terminal buffer from freezing.
- **INTERACTIVE MODE**: Never run commands that require interactive user input (e.g., `npm init` without `-y`) as they will hang the session.
- **NO INLINE PYTHON**: NEVER run `python3 -c "..."` or `.venv/bin/python3 -c "..."` on the command line. These inline scripts frequently hang, are hard to cancel, and bypass timeout safeguards. If you need to run Python logic, write a small script file and execute it, or use the available tools instead.
- **NO INLINE GH PR BODY**: NEVER run `gh pr create --title "..." --body "..."` with an inline body string. It WILL hang. Instead, write the body to a temp file and use `--body-file /tmp/pr_body.md`.