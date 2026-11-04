# Rule: code execution safety

- Execution adapters implement `ExecutionBackend` (`apps/api/execution/base.py`).
  Adding a provider means adding an adapter, not a branch in a view.
- Every command goes through `ToolRegistry.dispatch()`, which validates the
  argument schema, checks the tool permission, enforces a timeout, caps output, and
  writes an audit row.
- Destructive operations require an `ApprovalRequest` in state `approved` before
  dispatch. That covers: recursive deletion of a filesystem root, table or column
  drops, production migrations, forced pushes to a protected branch, deployments,
  and credential changes.
- Runners execute as a non-root user inside an approved workspace path. Path
  traversal above the workspace root is rejected before execution.
- Timeouts and output caps are mandatory. Truncate output at 200 KB and set
  `truncated: true`.
