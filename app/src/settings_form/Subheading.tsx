// The heading of a part of a step (a group of settings, an input box, the score histogram): an h3 under the step's h2, and an h4
// inside a section of a criterion's panel, whose header is the h3 (PanelSection provides the level).
import { createContext, useContext, type ReactNode } from "react";

export const SubheadingLevel = createContext<3 | 4>(3);

export function Subheading({ id, className, children }: { id?: string; className?: string; children: ReactNode }) {
  const Heading = useContext(SubheadingLevel) === 4 ? "h4" : "h3";
  return <Heading id={id} className={className}>{children}</Heading>;
}
