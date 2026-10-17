// The toolbar of UX 8.1, top right of the 3D view and left of the layers menu: frame all, top view, and the light or dark
// viewport (a moon on the light viewport, a sun on the dark one). The viewport choice is kept in this browser's storage.
import { messages } from "../messages";
import type { ViewportTheme } from "../viewer/scene";
import "./overlays.css";

const VIEWPORT_THEME_KEY = "usc.viewportTheme";

/** The viewport theme chosen last on this computer; light when none was chosen or storage is blocked. */
export function rememberedViewportTheme(): ViewportTheme {
  try {
    return window.localStorage.getItem(VIEWPORT_THEME_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function rememberViewportTheme(theme: ViewportTheme): void {
  try {
    window.localStorage.setItem(VIEWPORT_THEME_KEY, theme);
  } catch {
    // storage is blocked: the choice lasts for this page only
  }
}

interface ViewToolbarProps {
  theme: ViewportTheme;
  onFrameAll: () => void;
  onTopView: () => void;
  onThemeChange: (theme: ViewportTheme) => void;
}

const ICON_PROPS = { width: 20, height: 20, viewBox: "0 0 20 20", fill: "none", stroke: "currentColor", strokeWidth: 1.6,
                     strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

function FrameAllIcon() {
  return <svg {...ICON_PROPS}><path d="M3 7V3h4M13 3h4v4M17 13v4h-4M7 17H3v-4" /><rect x="7" y="7" width="6" height="6" /></svg>;
}

function TopViewIcon() {
  return <svg {...ICON_PROPS}><rect x="4" y="4" width="12" height="12" /><path d="M10 7v6M8 9l2-2 2 2" /></svg>;
}

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

export function ViewToolbar({ theme, onFrameAll, onTopView, onThemeChange }: ViewToolbarProps) {
  const dark = theme === "dark";
  const switchTheme = () => {
    const next: ViewportTheme = dark ? "light" : "dark";
    rememberViewportTheme(next);
    onThemeChange(next);
  };
  return (
    <div className="viewer-overlay viewer-toolbar" data-viewport-theme={theme} role="toolbar">
      <button type="button" aria-label={messages.frameAll} title={messages.frameAll} onClick={onFrameAll}><FrameAllIcon /></button>
      <button type="button" aria-label={messages.topView} title={messages.topView} onClick={onTopView}><TopViewIcon /></button>
      <button type="button" aria-label={messages.darkViewport} aria-pressed={dark} title={dark ? messages.lightViewport : messages.darkViewport}
              onClick={switchTheme}>
        {dark ? <SunIcon /> : <MoonIcon />}
      </button>
    </div>
  );
}
