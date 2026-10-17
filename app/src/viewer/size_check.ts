// The check that a model is in metres (technical spec 7, UX 11): a model more than 10 km or less than 1 m across is likely
// in another unit.
import { messages } from "../messages";
import type { Bounds3 } from "./local_origin";

const LONGEST_SIDE_LIMIT_METRES = 10_000;
const SHORTEST_PLAUSIBLE_SIDE_METRES = 1;

export function longestSide(bounds: Bounds3): number {
  return Math.max(...[0, 1, 2].map((axis) => bounds[1][axis] - bounds[0][axis]));
}

/** The warning for bounds whose longest side is over 10 000 m or under 1 m; null for a plausible size. */
export function sizeWarning(bounds: Bounds3): string | null {
  const side = longestSide(bounds);
  if (side > LONGEST_SIDE_LIMIT_METRES) return messages.modelMoreThan10Km;
  if (side < SHORTEST_PLAUSIBLE_SIDE_METRES) return messages.modelLessThan1M;
  return null;
}
