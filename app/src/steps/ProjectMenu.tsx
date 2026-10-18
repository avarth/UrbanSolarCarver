// The menu of a project (R2 7.2), beside each project of the start screen and on the project name in the top bar: Open folder,
// Rename, Delete and, for a project made from an example, Reset to the example. While a run of the project is active the last
// three wait and say why (the service refuses them then too); Open folder changes nothing and stays. The menu opens on a click,
// Enter, Space or the down arrow with the focus on its first item; the arrow keys, Home and End move through it; Escape closes it
// and gives the focus back to its button; Tab or a press elsewhere closes it. It is placed in the window under its button (above
// it when the room below is too short), so a scrolling list never clips it, and it closes when the page scrolls. A dialog it opens
// gives the focus back to its button too.
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { messages } from "../messages";
import { DeleteProjectDialog, ProjectProblemDialog, RenameProjectDialog, ResetProjectDialog } from "./ProjectDialogs";
import "./steps.css";

const GAP_UNDER_BUTTON_PIXELS = 4;

/** The requests of the menu; each resolves with the service's reason when it was refused, or null once done. */
export interface ProjectActions {
  openFolder: (projectName: string) => Promise<string | null>;
  rename: (projectName: string, newName: string) => Promise<string | null>;
  delete: (projectName: string, confirmName: string) => Promise<string | null>;
  resetToExample: (projectName: string) => Promise<string | null>;
}

type MenuItemName = "open_folder" | "rename" | "delete" | "reset_to_example";
type OpenDialog = { kind: "rename" | "delete" | "reset_to_example" } | { kind: "open_folder_failed"; problem: string };

const ITEM_LABELS: Record<MenuItemName, string> = {
  open_folder: messages.openProjectFolder,
  rename: messages.renameProject,
  delete: messages.deleteProject,
  reset_to_example: messages.resetProjectToExample,
};

interface ProjectMenuProps {
  projectName: string;
  /** The title of the example the project came from, which offers Reset to the example; null for other projects. */
  exampleTitle: string | null;
  /** The project's folder, named in the delete dialog; null while the projects folder is not known. */
  projectFolderPath: string | null;
  /** A run of this project is active: Rename, Delete and Reset wait. */
  runActive: boolean;
  actions: ProjectActions;
  /** "top_bar": the button is the project name, the menu opens under its left edge; "project_row": a small button, the menu ends at its right edge. */
  placement: "top_bar" | "project_row";
}

export function ProjectMenu({ projectName, exampleTitle, projectFolderPath, runActive, actions, placement }: ProjectMenuProps) {
  const [menuPlace, setMenuPlace] = useState<CSSProperties | null>(null);     // null while the menu is closed
  const [dialog, setDialog] = useState<OpenDialog | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const reasonId = useId();
  const open = menuPlace !== null;
  const items: MenuItemName[] = ["open_folder", "rename", "delete", ...(exampleTitle !== null ? ["reset_to_example" as const] : [])];
  const waitsForRun = (item: MenuItemName) => runActive && item !== "open_folder";

  const openMenu = () => {
    const anchor = button.current!.getBoundingClientRect();
    const top = anchor.bottom + GAP_UNDER_BUTTON_PIXELS;
    setMenuPlace(placement === "top_bar" ? { top, left: anchor.left } : { top, right: window.innerWidth - anchor.right });
  };
  const closeMenu = (focusButton: boolean) => {
    setMenuPlace(null);
    if (focusButton) button.current?.focus();
  };

  // A menu that would run past the bottom of the window opens above its button instead, when there is more room there.
  useLayoutEffect(() => {
    if (!open) return;
    const anchor = button.current!.getBoundingClientRect();
    const menuHeight = popup.current!.offsetHeight;
    const roomBelow = window.innerHeight - anchor.bottom - GAP_UNDER_BUTTON_PIXELS;
    const roomAbove = anchor.top - GAP_UNDER_BUTTON_PIXELS;
    if (menuHeight > roomBelow && roomAbove > roomBelow) setMenuPlace((place) => ({ ...place, top: anchor.top - GAP_UNDER_BUTTON_PIXELS - menuHeight }));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    popup.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true });
    const closeOnPressElsewhere = (event: Event) => {
      const target = event.target instanceof Node ? event.target : null;
      if (!(popup.current?.contains(target) || button.current?.contains(target))) closeMenu(false);
    };
    const closeOnMove = () => closeMenu(false);
    document.addEventListener("pointerdown", closeOnPressElsewhere);
    window.addEventListener("scroll", closeOnMove, true);       // capture: a scrolling list moves the button too
    window.addEventListener("resize", closeOnMove);
    return () => {
      document.removeEventListener("pointerdown", closeOnPressElsewhere);
      window.removeEventListener("scroll", closeOnMove, true);
      window.removeEventListener("resize", closeOnMove);
    };
  }, [open]);

  const openOnArrowDown = (event: KeyboardEvent) => {
    if (event.key !== "ArrowDown" || open) return;
    event.preventDefault();
    openMenu();
  };

  const moveThroughMenu = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu(true);
      return;
    }
    if (event.key === "Tab") return closeMenu(false);       // the focus goes on to the next control of the page
    const entries = [...popup.current!.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    const current = entries.indexOf(document.activeElement as HTMLElement);
    const next = { ArrowDown: (current + 1) % entries.length, ArrowUp: (current - 1 + entries.length) % entries.length, Home: 0,
                   End: entries.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    entries[next].focus();
  };

  const choose = async (item: MenuItemName) => {
    if (waitsForRun(item)) return;
    closeMenu(item === "open_folder");
    if (item !== "open_folder") return setDialog({ kind: item });
    const problem = await actions.openFolder(projectName);
    if (problem !== null) setDialog({ kind: "open_folder_failed", problem });
  };
  const closeDialog = () => {
    setDialog(null);
    button.current?.focus();
  };

  return (
    <div className="project-menu">
      <button ref={button} type="button" className={`project-menu-button project-menu-button-${placement === "top_bar" ? "top-bar" : "row"}`}
              aria-label={messages.projectMenuOf(projectName)} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
              onClick={() => (open ? closeMenu(false) : openMenu())} onKeyDown={openOnArrowDown}>
        {placement === "top_bar"
          ? <>{projectName}<span className="project-menu-caret" aria-hidden="true">{messages.projectMenuCaret}</span></>
          : <span aria-hidden="true">{messages.projectMenuSymbol}</span>}
      </button>
      {open && (
        <div ref={popup} className="project-menu-popup" style={menuPlace}>
          <ul id={menuId} role="menu" aria-label={messages.projectMenuOf(projectName)} onKeyDown={moveThroughMenu}>
            {items.map((item) => (
              <li key={item} role="none">
                <button type="button" role="menuitem" tabIndex={-1} aria-disabled={waitsForRun(item) || undefined}
                        aria-describedby={waitsForRun(item) ? reasonId : undefined} onClick={() => void choose(item)}>
                  {ITEM_LABELS[item]}
                </button>
              </li>
            ))}
          </ul>
          {runActive && <p id={reasonId} className="project-menu-reason">{messages.projectChangesWaitForRun}</p>}
        </div>
      )}
      {dialog?.kind === "rename" && (
        <RenameProjectDialog projectName={projectName} onRename={(newName) => actions.rename(projectName, newName)} onClose={closeDialog} />
      )}
      {dialog?.kind === "delete" && (
        <DeleteProjectDialog projectName={projectName} projectFolderPath={projectFolderPath}
                             onDelete={(confirmName) => actions.delete(projectName, confirmName)} onClose={closeDialog} />
      )}
      {dialog?.kind === "reset_to_example" && exampleTitle !== null && (
        <ResetProjectDialog projectName={projectName} exampleTitle={exampleTitle} onReset={() => actions.resetToExample(projectName)} onClose={closeDialog} />
      )}
      {dialog?.kind === "open_folder_failed" && (
        <ProjectProblemDialog title={messages.openFolderFailedTitle} problem={dialog.problem} onClose={closeDialog} />
      )}
    </div>
  );
}
