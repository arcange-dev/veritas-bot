/**
 * Accessible splitter. Pointer drag plus arrow-key resizing; double click
 * resets. `role="separator"` with a live aria-valuenow is what makes the studio
 * usable without a mouse.
 */
import { useCallback, useRef } from "react";
import { cn } from "@/lib/cn";
import { LIMITS, type PanelKey, useLayout } from "@/stores/layout";

interface SplitterProps {
  panel: PanelKey;
  orientation?: "vertical" | "horizontal";
  /** Which side of the splitter the sized panel sits on. */
  side?: "before" | "after";
  label: string;
}

export function Splitter({ panel, orientation = "vertical", side = "before", label }: SplitterProps) {
  const { setSize, left, right, bottom, reset } = useLayout();
  const size = panel === "left" ? left : panel === "right" ? right : bottom;
  const dragOrigin = useRef<{ pointer: number; size: number } | null>(null);
  const limits = LIMITS[panel];

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      dragOrigin.current = {
        pointer: orientation === "vertical" ? event.clientX : event.clientY,
        size,
      };
    },
    [orientation, size],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const origin = dragOrigin.current;
      if (!origin) return;
      const current = orientation === "vertical" ? event.clientX : event.clientY;
      const delta = current - origin.pointer;
      const signed = side === "before" ? delta : -delta;
      setSize(panel, origin.size + signed);
    },
    [orientation, panel, setSize, side],
  );

  const onPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    dragOrigin.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? 32 : 16;
      const isVertical = orientation === "vertical";
      if (event.key === (isVertical ? "ArrowLeft" : "ArrowUp")) {
        event.preventDefault();
        setSize(panel, size + (side === "before" ? -step : step));
      } else if (event.key === (isVertical ? "ArrowRight" : "ArrowDown")) {
        event.preventDefault();
        setSize(panel, size + (side === "before" ? step : -step));
      } else if (event.key === "Home") {
        event.preventDefault();
        reset();
      }
    },
    [orientation, panel, reset, setSize, side, size],
  );

  return (
    <div
      role="separator"
      aria-orientation={orientation}
      aria-label={label}
      aria-valuenow={size}
      aria-valuemin={limits.min}
      aria-valuemax={limits.max}
      tabIndex={0}
      data-orientation={orientation}
      className={cn("splitter")}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={reset}
      onKeyDown={onKeyDown}
    />
  );
}
