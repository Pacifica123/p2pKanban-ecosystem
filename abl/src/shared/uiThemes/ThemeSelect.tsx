import { useState } from "react";
import { DEFAULT_UI_THEME, UI_THEMES, applyUiTheme, normalizeUiTheme } from "./uiThemes";

export function ThemeSelect() {
  const [theme, setTheme] = useState(() => normalizeUiTheme(document.documentElement.dataset.uiTheme ?? DEFAULT_UI_THEME));
  return (
    <label className="theme-select">
      <span>Theme</span>
      <select
        aria-label="Application theme"
        value={theme}
        onChange={(event) => {
          const next = normalizeUiTheme(event.target.value);
          applyUiTheme(next);
          setTheme(next);
        }}
      >
        {UI_THEMES.map((item) => (
          <option key={item.id} value={item.id}>{item.label} · {item.description}</option>
        ))}
      </select>
    </label>
  );
}
