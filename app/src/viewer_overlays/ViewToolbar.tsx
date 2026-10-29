// The toolbar of UX 8.1, top right of the 3D view and left of the layers menu: frame all, top view, and the ground aid (R2 2:
// off, ground grid, compass ring in turn, the button showing the one it switches to), kept in this browser's storage. The
// viewport is light or dark with the app's theme (theme/app_theme.tsx).
import type { ReactElement } from "react";
import { messages } from "../messages";
import { GROUND_AIDS, nextGroundAid, type GroundAid, type ViewportTheme } from "../viewer/scene";
import "./overlays.css";

const GROUND_AID_KEY = "usc.groundAid";

/** The ground aid chosen last on this computer; the ground grid when none was chosen or storage is blocked. */
export function rememberedGroundAid(): GroundAid {
  try {
    const remembered = window.localStorage.getItem(GROUND_AID_KEY);
    return GROUND_AIDS.find((aid) => aid === remembered) ?? "grid";
  } catch {
    return "grid";
  }
}

export function rememberGroundAid(aid: GroundAid): void {
  try {
    window.localStorage.setItem(GROUND_AID_KEY, aid);
  } catch {
    // storage is blocked: the choice lasts for this page only
  }
}

interface ViewToolbarProps {
  theme: ViewportTheme;
  groundAid: GroundAid;
  onFrameAll: () => void;
  onTopView: () => void;
  onGroundAidChange: (aid: GroundAid) => void;
}

const ICON_PROPS = { width: 20, height: 20, viewBox: "0 0 20 20", fill: "none", stroke: "currentColor", strokeWidth: 1.6,
                     strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

function FrameAllIcon() {
  return <svg {...ICON_PROPS}><path d="M3 7V3h4M13 3h4v4M17 13v4h-4M7 17H3v-4" /><rect x="7" y="7" width="6" height="6" /></svg>;
}

function TopViewIcon() {
  return <svg {...ICON_PROPS}><rect x="4" y="4" width="12" height="12" /><path d="M10 7v6M8 9l2-2 2 2" /></svg>;
}

function GroundGridIcon() {
  return <svg {...ICON_PROPS}><rect x="3" y="3" width="14" height="14" /><path d="M7.7 3v14M12.3 3v14M3 7.7h14M3 12.3h14" /></svg>;
}

function CompassRingIcon() {
  return (
    <svg {...ICON_PROPS}>
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 2.5v3.5M10 14v3.5M2.5 10h3.5M14 10h3.5" />
    </svg>
  );
}

/** No ground aid: the grid, struck through. */
function NoGroundAidIcon() {
  return <svg {...ICON_PROPS}><rect x="3" y="3" width="14" height="14" strokeOpacity="0.5" /><path d="M3 17L17 3" /></svg>;
}

const GROUND_AID_ICONS: Record<GroundAid, () => ReactElement> = { off: NoGroundAidIcon, grid: GroundGridIcon, compass_ring: CompassRingIcon };

export function ViewToolbar({ theme, groundAid, onFrameAll, onTopView, onGroundAidChange }: ViewToolbarProps) {
  const followingGroundAid = nextGroundAid(groundAid);
  const FollowingGroundAidIcon = GROUND_AID_ICONS[followingGroundAid];
  const switchGroundAid = () => {
    rememberGroundAid(followingGroundAid);
    onGroundAidChange(followingGroundAid);
  };
  return (
    <div className="viewer-overlay viewer-toolbar" data-viewport-theme={theme} role="toolbar">
      <button type="button" aria-label={messages.frameAll} title={messages.frameAll} onClick={onFrameAll}><FrameAllIcon /></button>
      <button type="button" aria-label={messages.topView} title={messages.topView} onClick={onTopView}><TopViewIcon /></button>
      <button type="button" className="viewer-ground-aid-button" aria-label={messages.groundAidSwitchTo[followingGroundAid]}
              title={messages.groundAidSwitchTo[followingGroundAid]} onClick={switchGroundAid}>
        <FollowingGroundAidIcon />
      </button>
    </div>
  );
}
