import { useEffect, useRef, type CSSProperties } from "react";
import { ACCENT_PRESETS } from "../../../../frontend/src/ui/accent";
import { useLocale } from "../i18n/locale";

export function AccentPicker({ color, onChange, compact = false }: { color: string; onChange: (color: string) => void; compact?: boolean }) {
  const { t } = useLocale();
  const details = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key === "Escape") details.current?.removeAttribute("open");
      else if (event instanceof PointerEvent && !details.current?.contains(event.target as Node)) details.current?.removeAttribute("open");
    };
    document.addEventListener("keydown", close);
    document.addEventListener("pointerdown", close);
    return () => { document.removeEventListener("keydown", close); document.removeEventListener("pointerdown", close); };
  }, []);
  return <details className={`accent-picker${compact ? " accent-picker-compact" : ""}`} ref={details}>
    <summary aria-label={t("accent.label")} title={t("accent.label")}><i className="accent-current" aria-hidden="true" /><span>{t("accent.label")}</span></summary>
    <div className="accent-picker-panel" role="group" aria-label={t("accent.label")}>
      <strong className="accent-picker-title">{t("accent.label")}</strong>
      <div className="accent-swatches">
        {ACCENT_PRESETS.map((preset) => <button key={preset.id} type="button" className="accent-swatch" style={{ "--swatch-color": preset.color } as CSSProperties} aria-label={preset.label} title={preset.label} aria-pressed={color === preset.color} onClick={() => onChange(preset.color)} />)}
      </div>
      <label className="accent-custom"><span>{t("accent.custom")}</span><code>{color.toUpperCase()}</code><input type="color" value={color} onChange={(event) => onChange(event.target.value)} aria-label={t("accent.custom")} /></label>
    </div>
  </details>;
}
