// The data colours of the 3D view (UX 10.1): cividis for scores, viridis for study values, the sun ramp for sky patch weights, the storey
// ramp for the building massing, the change ramp for a study's change from the maximum volume. The theme colours and the ends of the storey ramp live in theme/tokens.css and are read from there.

export type ViewportTheme = "light" | "dark";

// matplotlib's cividis colormap, its 256 entries (matplotlib 3.10, colormaps["cividis"]).
const CIVIDIS_HEX = (
  "00224e 00234f 002451 002553 002554 002656 002758 002859 00285b 00295d 002a5f 002a61 002b62 002c64 002c66 002d68 " +
  "002e6a 002e6c 002f6d 00306f 003070 003170 003171 013271 053371 083370 0c3470 0f3570 123570 143670 163770 18376f " +
  "1a386f 1c396f 1e3a6f 203a6f 213b6e 233c6e 243c6e 263d6e 273e6e 293f6e 2a3f6d 2b406d 2d416d 2e416d 2f426d 31436d " +
  "32436d 33446d 34456c 35456c 36466c 38476c 39486c 3a486c 3b496c 3c4a6c 3d4a6c 3e4b6c 3f4c6c 404c6c 414d6c 424e6c " +
  "434e6c 444f6c 45506c 46516c 47516c 48526c 49536c 4a536c 4b546c 4c556c 4d556c 4e566c 4f576c 50576c 51586d 52596d " +
  "535a6d 545a6d 555b6d 555c6d 565c6d 575d6d 585e6d 595e6e 5a5f6e 5b606e 5c616e 5d616e 5e626e 5e636f 5f636f 60646f " +
  "61656f 62656f 636670 646770 656870 656870 666970 676a71 686a71 696b71 6a6c71 6b6d72 6c6d72 6c6e72 6d6f72 6e6f73 " +
  "6f7073 707173 717274 727274 727374 737475 747475 757575 767676 777776 777777 787877 797977 7a7a78 7b7a78 7c7b78 " +
  "7d7c78 7e7c78 7e7d78 7f7e78 807f78 817f78 828079 838179 848279 858279 868379 878478 888578 898578 8a8678 8b8778 " +
  "8c8878 8d8878 8e8978 8f8a78 908b78 918b78 928c78 928d78 938e78 948e77 958f77 969077 979177 989277 999277 9a9376 " +
  "9b9476 9c9576 9d9576 9e9676 9f9775 a09875 a19975 a29975 a39a74 a49b74 a59c74 a69c74 a79d73 a89e73 a99f73 aaa073 " +
  "aba072 aca172 ada272 aea371 afa471 b0a571 b1a570 b3a670 b4a76f b5a86f b6a96f b7a96e b8aa6e b9ab6d baac6d bbad6d " +
  "bcae6c bdae6c beaf6b bfb06b c0b16a c1b26a c2b369 c3b369 c4b468 c5b568 c6b667 c7b767 c8b866 c9b965 cbb965 ccba64 " +
  "cdbb63 cebc63 cfbd62 d0be62 d1bf61 d2c060 d3c05f d4c15f d5c25e d6c35d d7c45c d9c55c dac65b dbc75a dcc859 ddc858 " +
  "dec958 dfca57 e0cb56 e1cc55 e2cd54 e4ce53 e5cf52 e6d051 e7d150 e8d24f e9d34e ead34c ebd44b edd54a eed649 efd748 " +
  "f0d846 f1d945 f2da44 f3db42 f5dc41 f6dd3f f7de3e f8df3c f9e03a fbe138 fce236 fde334 fee434 fee535 fee636 fee838"
).split(" ").map((hex) => `#${hex}`);

// matplotlib's viridis colormap, its 256 entries (matplotlib 3.10.5, colormaps["viridis"]). Simulate colours study values with it:
// cividis passes through a neutral grey at its middle, where most facade values of a study fall, so gains there read as no change
// (user, 2026-10-28); viridis is perceptually even and readable with the common colour vision deficiencies, without a grey.
const VIRIDIS_HEX = (
  "440154 440256 450457 450559 46075a 46085c 460a5d 460b5e 470d60 470e61 471063 471164 471365 481467 481668 481769 " +
  "48186a 481a6c 481b6d 481c6e 481d6f 481f70 482071 482173 482374 482475 482576 482677 482878 482979 472a7a 472c7a " +
  "472d7b 472e7c 472f7d 46307e 46327e 46337f 463480 453581 453781 453882 443983 443a83 443b84 433d84 433e85 423f85 " +
  "424086 424186 414287 414487 404588 404688 3f4788 3f4889 3e4989 3e4a89 3e4c8a 3d4d8a 3d4e8a 3c4f8a 3c508b 3b518b " +
  "3b528b 3a538b 3a548c 39558c 39568c 38588c 38598c 375a8c 375b8d 365c8d 365d8d 355e8d 355f8d 34608d 34618d 33628d " +
  "33638d 32648e 32658e 31668e 31678e 31688e 30698e 306a8e 2f6b8e 2f6c8e 2e6d8e 2e6e8e 2e6f8e 2d708e 2d718e 2c718e " +
  "2c728e 2c738e 2b748e 2b758e 2a768e 2a778e 2a788e 29798e 297a8e 297b8e 287c8e 287d8e 277e8e 277f8e 27808e 26818e " +
  "26828e 26828e 25838e 25848e 25858e 24868e 24878e 23888e 23898e 238a8d 228b8d 228c8d 228d8d 218e8d 218f8d 21908d " +
  "21918c 20928c 20928c 20938c 1f948c 1f958b 1f968b 1f978b 1f988b 1f998a 1f9a8a 1e9b8a 1e9c89 1e9d89 1f9e89 1f9f88 " +
  "1fa088 1fa188 1fa187 1fa287 20a386 20a486 21a585 21a685 22a785 22a884 23a983 24aa83 25ab82 25ac82 26ad81 27ad81 " +
  "28ae80 29af7f 2ab07f 2cb17e 2db27d 2eb37c 2fb47c 31b57b 32b67a 34b679 35b779 37b878 38b977 3aba76 3bbb75 3dbc74 " +
  "3fbc73 40bd72 42be71 44bf70 46c06f 48c16e 4ac16d 4cc26c 4ec36b 50c46a 52c569 54c568 56c667 58c765 5ac864 5cc863 " +
  "5ec962 60ca60 63cb5f 65cb5e 67cc5c 69cd5b 6ccd5a 6ece58 70cf57 73d056 75d054 77d153 7ad151 7cd250 7fd34e 81d34d " +
  "84d44b 86d549 89d548 8bd646 8ed645 90d743 93d741 95d840 98d83e 9bd93c 9dd93b a0da39 a2da37 a5db36 a8db34 aadc32 " +
  "addc30 b0dd2f b2dd2d b5de2b b8de29 bade28 bddf26 c0df25 c2df23 c5e021 c8e020 cae11f cde11d d0e11c d2e21b d5e21a " +
  "d8e219 dae319 dde318 dfe318 e2e418 e5e419 e7e419 eae51a ece51b efe51c f1e51d f4e61e f6e620 f8e621 fbe723 fde725"
).split(" ").map((hex) => `#${hex}`);

function clampedShare(t: number): number {
  return Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
}

/** matplotlib's cividis at t in [0, 1], looked up the way matplotlib does (256 bins). */
export function cividis(t: number): string {
  return CIVIDIS_HEX[Math.min(CIVIDIS_HEX.length - 1, Math.floor(clampedShare(t) * CIVIDIS_HEX.length))];
}

/** matplotlib's viridis at t in [0, 1], looked up as cividis is (256 bins); Simulate's study values. */
export function viridis(t: number): string {
  return VIRIDIS_HEX[Math.min(VIRIDIS_HEX.length - 1, Math.floor(clampedShare(t) * VIRIDIS_HEX.length))];
}

/** The score range the kept voxels are coloured over: 0 to the cutoff, the range of the kept voxels (UX 8.2). */
export function keptScoreRange(thresholdValue: number): [number, number] {
  return [0, thresholdValue];
}

/** The value of a --colour-* token of theme/tokens.css. */
export function colourToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--colour-${name}`).trim();
}

export function viewportBackground(theme: ViewportTheme): string {
  return colourToken(`viewport-${theme}`);
}

function rgbOf(hex: string): [number, number, number] {
  const digits = hex.replace("#", "");
  return [0, 2, 4].map((start) => parseInt(digits.slice(start, start + 2), 16)) as [number, number, number];
}

function hexOf(rgb: number[]): string {
  return `#${rgb.map((channel) => Math.round(channel).toString(16).padStart(2, "0")).join("")}`;
}

/** The colour a share t of the way from one colour to another, mixed in sRGB. */
function mixedColour(from: string, to: string, t: number): string {
  const share = clampedShare(t);
  const start = rgbOf(from), end = rgbOf(to);
  return hexOf(start.map((channel, index) => channel + (end[index] - channel) * share));
}

/** The sky dome ramp: the viewport background at 0, the sun colour at 1. */
export function sunRamp(t: number, viewportTheme: ViewportTheme): string {
  return mixedColour(viewportBackground(viewportTheme), colourToken("sun"), t);
}

/**
 * The change ramp of Simulate's Change (a study's change from the maximum volume): light grey at no change, the accent colour at the
 * largest gain. A loss (t below 0), which carving cannot give but a massing can, is drawn in the carved colour.
 */
export function changeRamp(t: number): string {
  if (t < 0) return colourToken("carved");
  return mixedColour(colourToken("storey-low"), colourToken("accent"), t);
}

/** The change ramp at *steps* evenly spaced shares from 0 to 1 (changeRamp's colours), its two tokens read once. */
export function changeRampStops(steps: number): string[] {
  const low = colourToken("storey-low"), high = colourToken("accent");
  return Array.from({ length: steps }, (_, step) => mixedColour(low, high, step / (steps - 1)));
}

/** The colour of a storey (0 for the ground storey) of the building massing: the storey ramp, from light grey to slate (UX 10.1). */
export function storeyColour(storeyIndex: number, storeyCount: number): string {
  return mixedColour(colourToken("storey-low"), colourToken("storey-high"), storeyCount > 1 ? storeyIndex / (storeyCount - 1) : 0);
}
