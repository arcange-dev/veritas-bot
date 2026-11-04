import { create } from "zustand";
import { persist } from "zustand/middleware";

export const LIMITS = {
  left: { min: 200, max: 420, default: 260 },
  right: { min: 300, max: 560, default: 380 },
  bottom: { min: 120, max: 520, default: 240 },
} as const;

export type PanelKey = keyof typeof LIMITS;

interface LayoutState {
  left: number;
  right: number;
  bottom: number;
  collapsed: Record<PanelKey, boolean>;
  setSize: (panel: PanelKey, px: number) => void;
  toggle: (panel: PanelKey) => void;
  reset: () => void;
}

const clamp = (panel: PanelKey, px: number): number => {
  const { min, max } = LIMITS[panel];
  return Math.min(max, Math.max(min, Math.round(px)));
};

export const useLayout = create<LayoutState>()(
  persist(
    (set, get) => ({
      left: LIMITS.left.default,
      right: LIMITS.right.default,
      bottom: LIMITS.bottom.default,
      collapsed: { left: false, right: false, bottom: false },
      setSize: (panel, px) => set({ [panel]: clamp(panel, px) } as Partial<LayoutState>),
      toggle: (panel) => {
        const collapsed = { ...get().collapsed, [panel]: !get().collapsed[panel] };
        set({ collapsed });
      },
      reset: () =>
        set({
          left: LIMITS.left.default,
          right: LIMITS.right.default,
          bottom: LIMITS.bottom.default,
          collapsed: { left: false, right: false, bottom: false },
        }),
    }),
    { name: "superagent.layout" },
  ),
);
