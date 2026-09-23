import { useEffect, useRef, type CSSProperties } from "react";
import { ACCENT_PRESETS } from "../../../ui/accent.js";
import { translate, type RuntimeLanguage } from "../../../runtime_i18n.js";

export function AccentPicker({ color, onChange, language }: { color: string; onChange: (color: string) => void; language: RuntimeLanguage }) {
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
  const label = translate("Theme color", language);
  return <details className="accent-picker" ref={details}>
    <summary title={label} aria-label={label}><i className="accent-current" aria-hidden="true" /><span>{label}</span></summary>
    <div className="accent-picker-panel" role="group" aria-label={label}>
      <strong className="accent-picker-title">{label}</strong>
      <div className="accent-swatches">
        {ACCENT_PRESETS.map((preset) => <button key={preset.id} type="button" className="accent-swatch" style={{ "--swatch-color": preset.color } as CSSProperties} aria-label={preset.label} title={preset.label} aria-pressed={color === preset.color} onClick={() => onChange(preset.color)} />)}
      </div>
      <label className="accent-custom"><span>{translate("Custom color", language)}</span><code>{color.toUpperCase()}</code><input type="color" value={color} onChange={(event) => onChange(event.target.value)} aria-label={translate("Custom color", language)} /></label>
    </div>
  </details>;
}
