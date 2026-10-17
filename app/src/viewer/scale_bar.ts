// The scale bar of UX 8.1: a round length that adjusts to the zoom so the bar stays 100 to 250 px long.
import { formattedNumber, messages } from "../messages";

const SHORTEST_BAR_PIXELS = 100;
const ROUND_STEPS = [1, 2, 5];
const PIXEL_TOLERANCE = 1e-9;      // 10 m at 0.1 m per pixel is 100 px, which float arithmetic can make 99.999...

/** The smallest length of the 1, 2, 5 x 10^n series that is at least 100 px long, and its length in pixels. */
export function scaleBarLength(metresPerPixel: number): { metres: number; pixels: number } {
  let decade = Math.pow(10, Math.floor(Math.log10(SHORTEST_BAR_PIXELS * metresPerPixel)) - 1);
  for (;;) {
    for (const step of ROUND_STEPS) {
      const metres = Number((step * decade).toPrecision(12));     // 0.1 * 5 as 0.5, not 0.5000000000000001
      if (metres / metresPerPixel >= SHORTEST_BAR_PIXELS - PIXEL_TOLERANCE) return { metres, pixels: metres / metresPerPixel };
    }
    decade *= 10;
  }
}

export function scaleBarLabel(metres: number): string {
  return messages.scaleBar(formattedNumber(metres));
}
