# ⚠️ deprecated/ — DO NOT IMPORT OR RUN

These files are superseded, unreferenced legacy code kept only for
historical reference. They are **not** imported by `main.py`,
`mcp_server.py`, or anything under `core/`.

## agent.py.DO_NOT_USE
Early monolithic agent implementation, replaced by `core/agent.py` +
`core/policy.py` + `core/executor.py`. It runs shell commands via
`subprocess.run(command, shell=True, ...)` with no argv-list
enforcement and no path/command allowlist equivalent to the current
`core/policy.py`. If re-introduced or imported anywhere, it
reopens command-injection and workspace-escape issues that the
current `core/` implementation was built to close.

Do not resurrect this file without rebuilding it on top of the
current `Policy`/`SafeExecutor` classes.
