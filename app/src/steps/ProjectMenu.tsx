// The menu of a project (R2 7.2), beside each project of the start screen and on the project name in the top bar: Open folder,
// Rename, Delete and, for a project made from an example, Reset to the example. While a run of the project is active the last
// three wait and say why (the service refuses them then too); Open folder changes nothing and stays. The menu itself (keyboard,
// placement in the window) is ActionMenu. A dialog it opens gives the focus back to its button.
import { useRef, useState } from "react";
import { messages } from "../messages";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { DeleteProjectDialog, ProjectProblemDialog, RenameProjectDialog, ResetProjectDialog } from "./ProjectDialogs";
import "./steps.css";

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
  /**
   * "top_bar": the button is the project name, the menu opens under its left edge; "project_row": a small button, the menu ends at
   * its right edge.
   */
  placement: "top_bar" | "project_row";
  /** The id of the line that says why the whole menu waits (the folder picker is open); the button is then disabled. */
  waitReasonId?: string | null;
}

export function ProjectMenu({ projectName, exampleTitle, projectFolderPath, runActive, actions, placement, waitReasonId = null }: ProjectMenuProps) {
  const [dialog, setDialog] = useState<OpenDialog | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const itemNames: MenuItemName[] = ["open_folder", "rename", "delete", ...(exampleTitle !== null ? ["reset_to_example" as const] : [])];
  const items: ActionMenuItem[] = itemNames.map((item) => ({
    key: item, label: ITEM_LABELS[item], disabledReason: runActive && item !== "open_folder" ? messages.projectChangesWaitForRun : null,
  }));

  const choose = async (item: MenuItemName) => {
    if (item !== "open_folder") return setDialog({ kind: item });
    button.current?.focus();
    const problem = await actions.openFolder(projectName);
    if (problem !== null) setDialog({ kind: "open_folder_failed", problem });
  };
  const closeDialog = () => {
    setDialog(null);
    button.current?.focus();
  };

  return (
    <div className="project-menu">
      <ActionMenu label={messages.projectMenuOf(projectName)} items={items} onChoose={(key) => void choose(key as MenuItemName)}
                  align={placement === "top_bar" ? "start" : "end"} buttonRef={button} waitReasonId={waitReasonId}
                  buttonClassName={`project-menu-button project-menu-button-${placement === "top_bar" ? "top-bar" : "row"}`}
                  symbol={placement === "top_bar"
                    ? <>{projectName}<span className="project-menu-caret" aria-hidden="true">{messages.projectMenuCaret}</span></>
                    : <span aria-hidden="true">{messages.projectMenuSymbol}</span>} />
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
