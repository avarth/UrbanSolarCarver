// The setup of a new project (design/new-project-setup.md, section 3): the project settings shown a page at a time when Create
// project makes a project, so the weather file, which lives in Settings, is asked for once. Three pages: Location (the weather file
// and north, the same group as in Settings), the site's way in (sites drawn in the view, or a maximum volume file), and the heights
// (the Heights group; the max height only for sites). Each change is saved as it is made, as in Settings; nothing is required.
// Start closes the window and the workspace opens the Site step on the way chosen; Skip setup, × and Escape close it at any page
// and keep what was set. Examples and opened projects do not show it.
import { useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { DialogFrame } from "../common/dialogs";
import { messages } from "../messages";
import { Subheading } from "../settings_form/Subheading";
import "../theme/panels.css";
import "../sites/sites.css";

/** How the largest volume that may be built is given: sites drawn in the view, or mesh files. */
export type SiteWay = "sites" | "mesh";

const PAGES = ["location", "site", "heights"] as const;
type SetupPage = (typeof PAGES)[number];

interface ProjectSetupDialogProps {
  /** The Location group: the weather file's box and north (SettingsStep). */
  location: ReactNode;
  /** The way in chosen so far; null before one is. */
  way: SiteWay | null;
  onChooseWay: (way: SiteWay) => void;
  /** The Heights group for the way chosen (HeightsSettings); null while the project's heights are not read yet. */
  heights: (way: SiteWay | null) => ReactNode;
  /** Why the choice cannot be made now (a run is in progress); null when it can. */
  disabledReason: string | null;
  /** Start, on the last page. */
  onStart: (way: SiteWay | null) => void;
  /** Skip setup, × or Escape. */
  onSkip: () => void;
}

export function ProjectSetupDialog({ location, way, onChooseWay, heights, disabledReason, onStart, onSkip }: ProjectSetupDialogProps) {
  const [page, setPage] = useState<SetupPage>("location");
  const at = PAGES.indexOf(page);
  const last = at === PAGES.length - 1;
  const lineId = useId();
  const siteTitleId = useId();
  const choose = (chosen: SiteWay) => {
    onChooseWay(chosen);
    setPage("heights");
  };
  // Drawn into the page's body, as the project settings: inside the panel its backdrop could not cover the view's overlays.
  return createPortal(
    <DialogFrame title={messages.setupTitle} busy={false} onClose={onSkip} closeLabel={messages.skipSetup} describedBy={lineId}>
      <div className="project-settings project-setup" data-page={page}>
        <p className="project-setup-count">{messages.setupPageOf(at + 1, PAGES.length)}</p>
        {page === "location" && (
          <>
            <p id={lineId} className="project-settings-intro">{messages.setupLocationLine}</p>
            {location}
          </>
        )}
        {page === "site" && (
          <section className="input-choice" aria-labelledby={siteTitleId}>
            <Subheading id={siteTitleId} className="setting-group-title">{messages.setupSiteTitle}</Subheading>
            <p id={lineId} className="project-settings-intro">{messages.setupSiteLine}</p>
            <div className="input-choice-tiles">
              <button type="button" className="input-choice-tile" aria-pressed={way === "sites"} disabled={disabledReason !== null} onClick={() => choose("sites")}>
                <strong>{messages.inputChoiceSite}</strong>
                <span>{messages.inputChoiceSiteLine}</span>
              </button>
              <button type="button" className="input-choice-tile" aria-pressed={way === "mesh"} disabled={disabledReason !== null} onClick={() => choose("mesh")}>
                <strong>{messages.inputChoiceMaxVolume}</strong>
                <span>{messages.inputChoiceMaxVolumeLine}</span>
              </button>
            </div>
            {disabledReason !== null && <p className="input-box-reason">{disabledReason}</p>}
          </section>
        )}
        {page === "heights" && (
          <>
            <p id={lineId} className="project-settings-intro">{messages.setupHeightsLine}</p>
            {heights(way)}
          </>
        )}
      </div>
      <div className="project-dialog-buttons project-setup-buttons">
        <button type="button" className="link-button project-setup-skip" onClick={onSkip}>{messages.skipSetup}</button>
        {at > 0 && <button type="button" className="secondary-button" onClick={() => setPage(PAGES[at - 1])}>{messages.setupBack}</button>}
        <button type="button" className="primary-button" onClick={() => (last ? onStart(way) : setPage(PAGES[at + 1]))}>
          {last ? messages.setupStart : messages.setupNext}
        </button>
      </div>
    </DialogFrame>,
    document.body,
  );
}
