// The open project as its requests need it: the launch token, the project's name, and where a failed request goes when the
// service is the cause (access lost, engine stopped). ProjectWorkspace provides it; the hooks and panels of the open project read
// it, instead of each being handed the three. A rename makes a new workspace (App keys it by the project's name), so the name
// does not change while a session lasts: what reads it once (a queue, a listener) may keep it.
import { createContext, useContext } from "react";

export interface ProjectSession {
  token: string;
  /** The open project's name, as the requests name it. */
  project: string;
  /** The app's handler: shows the access-lost or engine-stopped overlay when the failure is one of those (reportServiceProblem). */
  onServiceProblem: (error: unknown) => void;
}

export const ProjectSessionContext = createContext<ProjectSession | null>(null);

export function useProjectSession(): ProjectSession {
  const session = useContext(ProjectSessionContext);
  if (session === null) throw new Error("useProjectSession is for the parts of an open project, inside ProjectWorkspace");
  return session;
}
