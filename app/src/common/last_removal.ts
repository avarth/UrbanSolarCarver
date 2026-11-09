// The undo of the last removal of an input file (user, 2026-11-09): a removed file is kept under inputs/removed/<role>/ of the
// project folder, and the box it was removed from says so with an Undo until the next change of the inputs. The workspace gives the
// last removal to every InputBox through this context, so the boxes inside the Site card and the settings need no prop for it.
import { createContext } from "react";

export interface LastRemoval {
  /** The input role (InputBox's InputRole), as a string so this module does not import InputBox, which reads it. */
  role: string;
  /** The name the file was shown by. */
  name: string;
  /** Adds the file back; resolves with the reason it could not, or null. */
  undo: () => Promise<string | null>;
}

export const LastRemovalContext = createContext<LastRemoval | null>(null);
