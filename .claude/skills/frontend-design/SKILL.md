---
name: frontend-design
description: Visual and interaction system for the SuperAgent web app - graphite dark theme, blue/cyan accents, type scale, panel geometry, motion budget, accessible states. Use when designing or building any screen, component, empty state, or layout in apps/web.
---

# Frontend Design

## When to use
Any new page, component, layout, or visual polish pass in `apps/web`. Read this before
writing JSX so the result does not look like a generic AI dashboard.

## Direction
Professional developer SaaS. Graphite, not black. Dense but calm. The product is a tool;
the UI should feel like an instrument, not a landing page. Zero decorative gradients on
content surfaces, zero emoji, zero rounded-full blobs.

## Tokens

```css
/* apps/web/src/styles/tokens.css */
:root {
  --bg-base: #0b0d10;        /* app background */
  --bg-raised: #12151a;      /* panels */
  --bg-overlay: #171b21;     /* popovers, command palette */
  --border-subtle: #232833;
  --border-strong: #2f3644;
  --text-primary: #e8ecf1;
  --text-secondary: #9aa4b2;
  --text-muted: #5f6a7a;
  --accent: #3b82f6;         /* primary action, focus */
  --accent-soft: #60a5fa;
  --cyan: #22d3ee;           /* live/streaming indicators only */
  --ok: #34d399;
  --warn: #fbbf24;
  --danger: #f87171;
  --radius-sm: 6px;
  --radius: 10px;
  --radius-lg: 14px;
  --shadow-panel: 0 1px 0 rgba(255,255,255,.03), 0 8px 24px rgba(0,0,0,.35);
}
[data-theme="light"] {
  --bg-base: #f7f8fa; --bg-raised: #ffffff; --bg-overlay: #ffffff;
  --border-subtle: #e3e7ee; --border-strong: #cdd4e0;
  --text-primary: #16191f; --text-secondary: #4b5563; --text-muted: #8b95a5;
  --shadow-panel: 0 1px 2px rgba(16,24,40,.06), 0 8px 24px rgba(16,24,40,.06);
}
```

Typography: UI in `Inter`, variable, 13px base in panels / 15px in prose, `-0.01em`
tracking on headings. Code in `JetBrains Mono` 12.5px / 1.55. Numerals tabular in all
metrics (`font-variant-numeric: tabular-nums`).

## Layout geometry
- Full-height app shell: `grid-template-rows: 44px 1fr` with a 44px status rail.
- Developer Studio: `grid-template-columns: 260px minmax(0,1fr) 380px`, rows
  `1fr 240px`, all gutters 1px borders not gaps. Panels own their own scroll.
- Panel headers are 32px, uppercase 11px labels with `letter-spacing: .06em`.
- Every panel is resizable via drag handles with `role="separator"`, `aria-orientation`,
  and keyboard arrow support (+- 16px per press).

## Motion budget
- Hover/press: 90ms `ease-out`.
- Panel expand, drawer: 180ms `cubic-bezier(.2,.8,.2,1)`.
- Streaming text caret: 1s `steps(2)` blink, and only while a stream is open.
- Route transitions: none. Do not animate page changes in a tool.
- Respect `prefers-reduced-motion: reduce` -> durations to 0.

## Required states
Every data surface implements four states with real copy: loading (skeleton with the
final geometry, not a spinner in the middle of nowhere), empty (what it is, why it is
empty, one primary action), error (what failed, retry button, request id), populated.

## Do not
- Do not use gradient text, glassmorphism, or neon glow.
- Do not put a large number in a card unless it is a metric the user acts on.
- Do not use more than one accent hue per view; cyan is reserved for "live".
- Do not hide primary actions in overflow menus.

## Checklist
- [ ] Contrast >= 4.5:1 body, >= 3:1 large text and borders on interactive elements.
- [ ] Focus visible on every control, 2px `--accent` ring with 2px offset.
- [ ] Works at 1024px (panels stack) and 1440px.
- [ ] No layout shift when data arrives.
