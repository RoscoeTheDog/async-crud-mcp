# Shell Restrictions Reference

`async_exec_tool` enforces a deny-pattern policy that blocks shell commands which bypass the CRUD tool audit trail. This document lists all restricted commands, the rationale for each restriction, and the recommended alternative.

## How It Works

Before executing a command, the shell validator checks it against a list of regex deny patterns. If any pattern matches, the command is rejected with a `ExecDeniedResponse` containing the matched pattern and the reason. The deny patterns are configured in `ShellConfig` and can be customized via `crud_update_config`.

## Content Redaction

In addition to deny patterns, `async_exec_tool` applies content scanner redaction to stdout and stderr before returning results. This prevents sensitive data (API keys, tokens, private keys) from being exposed in command output. The same redaction applies to background task output retrieved via `async_wait_tool`.

## Restricted Commands

### File I/O Commands

These commands are blocked to force file operations through the CRUD tools, ensuring proper locking, hash tracking, and audit trail.

| Blocked Command | Pattern | Recommended Alternative |
|----------------|---------|------------------------|
| `cat` | `\bcat\b` | `async_read_tool` |
| `head` | `\bhead\b` | `async_read_tool` with `offset`/`limit` |
| `tail` | `\btail\b` | `async_read_tool` with `offset`/`limit` |
| `sed` | `\bsed\b` | `async_update_tool` with patches or regex_patches |
| `awk` | `\bawk\b` | `async_read_tool` + `async_update_tool` |
| `tee` | `\btee\b` | `async_write_tool` |
| `echo ... > file` | `\becho\b.*>(?!&)\s*[^&\s]` | `async_write_tool` |
| `printf ... > file` | `\bprintf\b.*>(?!&)\s*[^&\s]` | `async_write_tool` |
| `cp` | `\bcp\b` | `async_read_tool` + `async_write_tool` |
| `mv` | `\bmv\b` | `async_rename_tool` |
| `rm` | `\brm\b` | `async_delete_tool` (moves to recycle bin) |

**Note:** `echo` and `printf` are only blocked when redirecting to a file (`> file`). Using them for stdout display (e.g., `echo "hello"`) is allowed. The pattern excludes `>&` (stderr redirection) to avoid false positives.

### Dangerous System Commands

These commands are blocked to prevent accidental or malicious system modifications.

| Blocked Command | Pattern | Reason |
|----------------|---------|--------|
| `chmod` | `\bchmod\b` | File permission changes not allowed |
| `chown` | `\bchown\b` | File ownership changes not allowed |
| `dd` | `\bdd\b` | Block device operations not allowed |
| `mkfs` | `\bmkfs\b` | Filesystem operations not allowed |
| `sudo` / `su` | `\b(sudo\|su)\b` | Privilege escalation not allowed |

### Interpreter Inline-Code Flags

These block interpreters from executing arbitrary inline code that could perform file I/O outside CRUD governance.

| Blocked Command | Pattern | Reason |
|----------------|---------|--------|
| `perl -e '...'` | `\bperl\b\s+(-\w*e\b\|.*\s-e\s)` | Inline code execution bypasses CRUD tools |
| `ruby -e '...'` | `\bruby\b\s+(-\w*e\b\|.*\s-e\s)` | Inline code execution bypasses CRUD tools |
| `python -c '...'` | `\b(python3?\|python3?\.\d+)\b\s+(-\w*c\b\|.*\s-c\s)` | Inline code execution bypasses CRUD tools |
| `node -e '...'` | `\bnode\b\s+(-\w*e\b\|.*\s-e\s)` | Inline code execution bypasses CRUD tools |

**Note:** Running scripts by filename (e.g., `python script.py`, `node app.js`) is allowed. Only inline code flags (`-e`, `-c`) are blocked because they can embed arbitrary file operations.

### Command Construction / Obfuscation Prevention

These block techniques that could bypass deny patterns by constructing commands dynamically.

| Blocked Command | Pattern | Reason |
|----------------|---------|--------|
| `eval` | `\beval\b` | Dynamic command construction could bypass deny patterns |
| `source` | `\bsource\b` | Sourcing scripts could execute blocked commands |

### Pipe to Shell

These block piping decoded or constructed payloads into shell interpreters.

| Blocked Pattern | Pattern | Reason |
|----------------|---------|--------|
| `\| sh` / `\| bash` | `\|\s*(ba)?sh\b` | Piping to shell interpreter not allowed |
| `\| dash` / `\| zsh` / `\| fish` | `\|\s*(da\|z\|fi)sh\b` | Piping to shell interpreter not allowed |

### Alternate Shells / Interpreters

These block spawning secondary shell interpreters that could execute unrestricted commands.

| Blocked Command | Pattern | Reason |
|----------------|---------|--------|
| `powershell` / `pwsh` | `\b(powershell\|pwsh)(\.exe)?\b` | PowerShell execution not allowed |
| `cmd /c` / `cmd /k` | `\bcmd(\.exe)?\s*/[cCkK]\b` | cmd.exe execution not allowed |

### File Descriptor Redirection

| Blocked Pattern | Pattern | Reason |
|----------------|---------|--------|
| `exec N>file` | `\bexec\b\s+\d*[<>]` | File descriptor redirection bypasses CRUD tools |

### Dangerous Utilities

| Blocked Command | Pattern | Reason |
|----------------|---------|--------|
| `install` | `(^\|[;&\|]\s*)install\b` | The `install` command copies files with permission setting; blocked to prevent CRUD bypass |

## What IS Allowed

The following are examples of commands that pass deny-pattern validation:

- **Git operations**: `git status`, `git diff`, `git log`, `git add`, `git commit`
- **Package managers**: `pip install`, `npm install`, `uv sync`, `cargo build`
- **Build tools**: `make`, `cmake`, `tsc`, `webpack`, `vite`
- **Test runners**: `pytest`, `jest`, `go test`, `cargo test`
- **System info**: `whoami`, `hostname`, `uname`, `env`, `pwd`, `ls`
- **Network tools**: `curl`, `wget` (output goes to stdout, not file bypass)
- **Docker**: `docker build`, `docker run`, `docker compose`
- **Script execution**: `python script.py`, `node app.js`, `bash script.sh`

## Customizing Deny Patterns

Deny patterns can be modified via the config tool:

```
crud_update_config(section="shell", updates={
  "additional_deny_patterns": [
    {"pattern": "\\bcurl\\b.*-o\\b", "reason": "curl file download not allowed"}
  ]
})
```

Or by editing the server config file directly (requires daemon restart).

## Troubleshooting

**Command rejected unexpectedly?**
The `ExecDeniedResponse` includes:
- `matched_pattern`: The regex that matched
- `reason`: Why the command was blocked

Check if your command contains a substring matching a deny pattern. For example, `echo $PATH` is allowed, but `echo "data" > output.txt` triggers the `echo ... > file` pattern.

**Need a blocked command?**
Use the equivalent CRUD tool listed in the table above. The CRUD tools provide proper file locking, hash tracking, content scanning, and audit trail that shell commands cannot.
