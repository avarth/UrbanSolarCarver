// A criterion's test surfaces, added, removed and taken from another criterion through its own routes (useCriteria). The reply
// lists file names only, so after an upload or a removal the stored files are asked for again (with their triangle counts, for the
// box and the 3D view); the stage status follows every change, as after a change of the site's inputs.
import { getInputFiles, serviceProblemOf, type InputFileInfo } from "../api_client/client";
import { inputProblemText } from "../steps/InputsStep";
import type { CriteriaHook } from "./use_criteria";

export interface TestSurfaceContext {
  token: string;
  project: string;
  criteria: CriteriaHook;
  /** The criterion whose files change. */
  criterionId: string;
  /** The stored test surface files after a change (every criterion's). */
  onStoredFiles: (files: InputFileInfo[]) => void;
  refreshStageStatus: () => void;
  /** Follows a change until its reply is in (the app waits for it before a rename, reset or delete). */
  followed: <Reply>(change: Promise<Reply>) => Promise<Reply>;
  onServiceProblem: (error: unknown) => void;
}

export interface TestSurfaceCalls {
  /** Adds the files one after another; resolves with a message per file that could not be added. */
  add: (files: File[]) => Promise<string[]>;
  /** Takes the file out of the criterion; resolves with the reason it could not, or null. */
  remove: (fileName: string) => Promise<string | null>;
  /** Lets the criterion use a file another criterion uses (stored already); resolves with the reason it could not, or null. */
  use: (fileName: string) => Promise<string | null>;
}

export function testSurfaceCallsOf(context: TestSurfaceContext): TestSurfaceCalls {
  const { token, project, criteria, criterionId, onServiceProblem } = context;
  const afterChange = async () => {
    context.refreshStageStatus();
    try {
      context.onStoredFiles(await getInputFiles(token, project, "test_surfaces"));
    } catch (error) {
      onServiceProblem(error);
    }
  };
  const addOneByOne = async (files: File[]): Promise<string[]> => {
    const problems: string[] = [];
    for (const file of files) {
      try {
        await criteria.addTestSurfaces(criterionId, [file]);
      } catch (error) {
        if (serviceProblemOf(error) !== "other") {
          onServiceProblem(error);
          break;
        }
        problems.push(inputProblemText(error, file.name));
      }
    }
    if (problems.length < files.length) await afterChange();
    return problems;
  };
  const removeAndApply = async (fileName: string): Promise<string | null> => {
    try {
      await criteria.removeFile(criterionId, fileName);
      await afterChange();
      return null;
    } catch (error) {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return inputProblemText(error, fileName);
    }
  };
  // The file is stored already, with its mesh loaded: only the stage status changes.
  const useStoredFile = async (fileName: string): Promise<string | null> => {
    try {
      await criteria.reuseFile(criterionId, fileName);
      context.refreshStageStatus();
      return null;
    } catch (error) {
      if (serviceProblemOf(error) !== "other") onServiceProblem(error);
      return inputProblemText(error, fileName);
    }
  };
  return {
    add: (files) => context.followed(addOneByOne(files)),
    remove: (fileName) => context.followed(removeAndApply(fileName)),
    use: (fileName) => context.followed(useStoredFile(fileName)),
  };
}
