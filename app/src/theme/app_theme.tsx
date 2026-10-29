// The light or dark theme of the whole app: switched by the button at the right of the top bar, kept in this browser's storage
// and set on the body as data-theme, where tokens.css gives the dark values of the interface's colours. The 3D view and its
// overlays follow it (useAppTheme). The dark values stay off the root element, so the colours the 3D scene reads from there
// (colourToken) are the same in both themes; the scene has its own dark viewport colours.
import { createContext, useContext } from "react";
import { messages } from "../messages";
import type { ViewportTheme } from "../viewer/colour_scales";

export type AppTheme = ViewportTheme;

const THEME_KEY = "usc.theme";

/** The theme chosen last on this computer; light when none was chosen or storage is blocked. */
export function rememberedTheme(): AppTheme {
  try {
    return window.localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function rememberTheme(theme: AppTheme): void {
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    // storage is blocked: the choice lasts for this page only
  }
}

/** Puts *theme* on the page: the body's data-theme, which tokens.css reads. */
export function showTheme(theme: AppTheme): void {
  document.body.dataset.theme = theme;
}

const AppThemeContext = createContext<AppTheme>("light");

export const AppThemeProvider = AppThemeContext.Provider;

export function useAppTheme(): AppTheme {
  return useContext(AppThemeContext);
}

const ICON_PROPS = { width: 20, height: 20, viewBox: "0 0 20 20", fill: "none", stroke: "currentColor", strokeWidth: 1.6,
                     strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

function MoonIcon() {
  return <svg {...ICON_PROPS}><path d="M15.5 12.5A6 6 0 0 1 7.5 4.5a6 6 0 1 0 8 8z" /></svg>;
}

function SunIcon() {
  return (
    <svg {...ICON_PROPS}>
      <circle cx="10" cy="10" r="3.2" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
    </svg>
  );
}

/** The theme switch of the top bar: a moon in the light theme, a sun in the dark one; the choice is remembered. */
export function ThemeButton({ theme, onChange }: { theme: AppTheme; onChange: (theme: AppTheme) => void }) {
  const dark = theme === "dark";
  const switchTheme = () => {
    const next: AppTheme = dark ? "light" : "dark";
    rememberTheme(next);
    onChange(next);
  };
  return (
    <button type="button" className="top-bar-icon-button" aria-label={messages.darkTheme} aria-pressed={dark}
            title={dark ? messages.switchToLightTheme : messages.switchToDarkTheme} onClick={switchTheme}>
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
