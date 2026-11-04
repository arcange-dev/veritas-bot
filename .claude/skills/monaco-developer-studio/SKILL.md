---
name: monaco-developer-studio
description: The Developer Studio workspace UI - resizable five-region layout, Monaco editor integration with lazy workers and model management, multi-tab editing with dirty state, xterm.js terminal bound to a run stream, diff viewer, and keyboard-first navigation. Use when building or modifying anything in the studio route.
---

# Monaco Developer Studio

## When to use
Any work on `apps/web/src/features/studio/**`: layout, editor, tabs, terminal, diff,
toolbar, panel resizing.

## Layout contract
```
┌──────────────────────────────────────────────────────────────┐
│ TOPBAR  project · env(local|cloud) · model · build run test   │ 48px
├────────────┬─────────────────────────────────┬───────────────┤
│ LEFT       │ CENTER                          │ RIGHT         │
│ explorer   │ tabs                            │ chat          │
│ agents     │ Monaco                          │ plan          │
│ git status │                                 │ approvals     │
│ 260px      ├─────────────────────────────────┤ 380px         │
│            │ BOTTOM terminal / tests / logs  │               │
│            │ 240px                           │               │
└────────────┴─────────────────────────────────┴───────────────┘
```
Implement with CSS grid and pointer-driven splitters that write to a Zustand store
(persisted to localStorage per user). Below 1024px: left and right become drawers, bottom
becomes a tab of the center region. Every splitter is a `role="separator"` with
`aria-valuenow`, arrow-key resize, and double-click to reset.

## Monaco integration rules
- Load Monaco lazily; it is ~1 MB and must not be in the initial bundle.
- One `monaco.editor.IStandaloneCodeEditor` instance, many models. Create a model per open
  file with the right language id; dispose models on tab close.
- Configure workers explicitly with Vite:

```ts
// src/features/studio/monaco/setup.ts
import * as monaco from "monaco-editor";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import tsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";
import jsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";

self.MonacoEnvironment = {
  getWorker(_id, label) {
    if (label === "typescript" || label === "javascript") return new tsWorker();
    if (label === "json") return new jsonWorker();
    return new editorWorker();
  },
};
monaco.editor.defineTheme("superagent-graphite", {
  base: "vs-dark", inherit: true,
  colors: { "editor.background": "#0b0d10", "editorLineNumber.foreground": "#3d4655" },
  rules: [{ token: "comment", foreground: "5f6a7a", fontStyle: "italic" }],
});
```
- `automaticLayout: false`; drive layout from a `ResizeObserver` on the container so
  resizing panels does not thrash.
- Read-only mode is the default while an agent run is active on that file, with a visible
  "agent is editing" banner. Editing while an agent writes the same file is the bug factory.
- Debounce change events 400ms, then mark the tab dirty and schedule autosave.

## Tabs and dirty state
`OpenTab { path, language, modelUri, dirty, pinned }`. Dirty tabs get a dot, closing a dirty
tab confirms. Restore tabs per project from localStorage. Never keep file contents in the
Zustand store beyond the dirty flag.

## Diff viewer
Use `monaco.editor.createDiffEditor` with `renderSideBySide: false` under 900px width.
Diff is fetched as a patch from the API, not computed client-side against stale content.

## Terminal (xterm.js)
- `@xterm/xterm` + `@xterm/addon-fit` + `@xterm/addon-web-links`. Fit on container resize,
  dispose on unmount.
- One WebSocket per terminal session; write frames in order by `seq`, buffer gaps and
  request replay.
- Read-only replay mode for finished runs, with a scrubber.
- Streaming a run's output must not remount the terminal: keep the session component
  mounted and swap the data source.

## Accessibility
File tree is a `tree` role with arrow-key navigation; terminal has a "copy output" button
and never steals focus on stream; all toolbar actions reachable via `Ctrl/Cmd+K` palette.

## Checklist
- [ ] Monaco code-split out of the main bundle.
- [ ] Models disposed; no memory growth across 50 tab opens.
- [ ] Terminal survives panel resize without remount.
- [ ] Read-only during agent writes, with visible banner.
- [ ] Layout degrades below 1024px.
