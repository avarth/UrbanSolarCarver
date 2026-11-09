// A criterion's test surfaces: the project's surface sets switched on and off through the criterion's routes (useCriteria). The reply
// lists file names only, so after each change the stored files are asked for again (with their triangle counts, for the
// box and the 3D view); the stage status follows every change, as after a change of the site's inputs.
import { getInputFiles, reportServiceProblem, type InputFileInfo } from "../api_client/client";
import { useProjectSession } from "../api_client/project_session";
import { inputProblemText } from "../common/InputBox";
import type { CriteriaHook } from "./use_criteria";

export interface TestSurfaceContext {
  criteria: CriteriaHook;
  /** The criterion whose files change. */
  criterionId: string;
  /** The stored test surface files after a change (every criterion's). */
  onStoredFiles: (files: InputFileInfo[]) => void;
  refreshStageStatus: () => void;
  /** Follows a change until its reply is in (the app waits for it before a rename, reset or delete). */
  followed: <Reply>(change: Promise<Reply>) => Promise<Reply>;
}

export interface TestSurfaceCalls {
  /** Takes the file out of the criterion; resolves with the reason it could not, or null. */
  remove: (fileName: string) => Promise<string | null>;
  /** Lets the criterion use a surface set of the project (stored already); resolves with the reason it could not, or null. */
  use: (fileName: string) => Promise<string | null>;
  /** Asks for the stored files again (after a criterion is deleted, its files no other criterion uses are gone). */
  reloadStoredFiles: () => Promise<void>;
}

export function useTestSurfaceCalls(context: TestSurfaceContext): TestSurfaceCalls {
  const { token, project, onServiceProblem } = useProjectSession();
  const { criteria, criterionId } = context;
  const reloadStoredFiles = async () => {
    try {
      context.onStoredFiles(await getInputFiles(token, project, "test_surfaces"));
    } catch (error) {
      onServiceProblem(error);
    }
  };
  const afterChange = async () => {
    context.refreshStageStatus();
    await reloadStoredFiles();
  };
  const removeAndApply = async (fileName: string): Promise<string | null> => {
    try {
      await criteria.removeFile(criterionId, fileName);
      await afterChange();
      return null;
    } catch (error) {
      reportServiceProblem(error, onServiceProblem);
      return inputProblemText(error, fileName);
    }
  };
  // The file is stored already, with its mesh loaded: the stage status changes, and the sets are read again for who uses them.
  const useStoredFile = async (fileName: string): Promise<string | null> => {
    try {
      await criteria.reuseFile(criterionId, fileName);
      await afterChange();
      return null;
    } catch (error) {
      reportServiceProblem(error, onServiceProblem);
      return inputProblemText(error, fileName);
    }
  };
  return {
    remove: (fileName) => context.followed(removeAndApply(fileName)),
    use: (fileName) => context.followed(useStoredFile(fileName)),
    reloadStoredFiles,
  };
}
