// The open project's session for a test that renders a hook or panel of it without ProjectWorkspace around it.
import type { ReactElement } from "react";
import { ProjectSessionContext, type ProjectSession } from "./project_session";

export const TEST_SESSION: ProjectSession = { token: "token", project: "p", onServiceProblem: () => {} };

/** *element* inside the session of project "p" with token "token", or with what *session* gives instead. */
export function inProjectSession(element: ReactElement, session: Partial<ProjectSession> = {}): ReactElement {
  return <ProjectSessionContext value={{ ...TEST_SESSION, ...session }}>{element}</ProjectSessionContext>;
}
