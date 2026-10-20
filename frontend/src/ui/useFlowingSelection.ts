import { useLayoutEffect, useRef, type RefObject } from "react";
import { createSelectionMotion, type SelectionMotionOptions } from "./selectionMotion.js";
import "./selectionMotion.css";

export function useFlowingSelection<T extends HTMLElement>(ref: RefObject<T | null>, selected: unknown, options: SelectionMotionOptions = {}): void {
  const controller = useRef<ReturnType<typeof createSelectionMotion> | null>(null);
  const attached = useRef<T | null>(null);
  const selectors = useRef<SelectionMotionOptions>({});
  useLayoutEffect(() => {
    if (attached.current === ref.current && selectors.current.itemSelector === options.itemSelector
      && selectors.current.selectedSelector === options.selectedSelector) return;
    controller.current?.destroy();
    attached.current = ref.current;
    selectors.current = { ...options };
    controller.current = ref.current ? createSelectionMotion(ref.current, options) : null;
  });
  useLayoutEffect(() => { controller.current?.update(); }, [selected]);
  useLayoutEffect(() => () => {
    controller.current?.destroy();
    controller.current = null;
    attached.current = null;
  }, []);
}
