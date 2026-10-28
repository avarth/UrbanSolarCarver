// The palettes Simulate colours a study's values with (user, 2026-10-28: pinned, magma by value, viridis by share of the
// no-build value and for Change): matplotlib's perceptually even colormaps, 256 entries each (matplotlib 3.10.5). Each runs
// from dark to light without a grey middle; viridis is the one most readable with the common colour vision deficiencies.
// Written by a script from matplotlib's tables; do not edit by hand.

export type StudyPalette = "magma" | "viridis";

const HEX: Record<StudyPalette, string> = {
  magma:
    "000004 010005 010106 010108 020109 02020b 02020d 03030f 030312 040414 050416 060518 06051a 07061c 08071e 090720 " +
    "0a0822 0b0924 0c0926 0d0a29 0e0b2b 100b2d 110c2f 120d31 130d34 140e36 150e38 160f3b 180f3d 19103f 1a1042 1c1044 " +
    "1d1147 1e1149 20114b 21114e 221150 241253 251255 271258 29115a 2a115c 2c115f 2d1161 2f1163 311165 331067 341069 " +
    "36106b 38106c 390f6e 3b0f70 3d0f71 3f0f72 400f74 420f75 440f76 451077 471078 491078 4a1079 4c117a 4e117b 4f127b " +
    "51127c 52137c 54137d 56147d 57157e 59157e 5a167e 5c167f 5d177f 5f187f 601880 621980 641a80 651a80 671b80 681c81 " +
    "6a1c81 6b1d81 6d1d81 6e1e81 701f81 721f81 732081 752181 762181 782281 792282 7b2382 7c2382 7e2482 802582 812581 " +
    "832681 842681 862781 882781 892881 8b2981 8c2981 8e2a81 902a81 912b81 932b80 942c80 962c80 982d80 992d80 9b2e7f " +
    "9c2e7f 9e2f7f a02f7f a1307e a3307e a5317e a6317d a8327d aa337d ab337c ad347c ae347b b0357b b2357b b3367a b5367a " +
    "b73779 b83779 ba3878 bc3978 bd3977 bf3a77 c03a76 c23b75 c43c75 c53c74 c73d73 c83e73 ca3e72 cc3f71 cd4071 cf4070 " +
    "d0416f d2426f d3436e d5446d d6456c d8456c d9466b db476a dc4869 de4968 df4a68 e04c67 e24d66 e34e65 e44f64 e55064 " +
    "e75263 e85362 e95462 ea5661 eb5760 ec5860 ed5a5f ee5b5e ef5d5e f05f5e f1605d f2625d f2645c f3655c f4675c f4695c " +
    "f56b5c f66c5c f66e5c f7705c f7725c f8745c f8765c f9785d f9795d f97b5d fa7d5e fa7f5e fa815f fb835f fb8560 fb8761 " +
    "fc8961 fc8a62 fc8c63 fc8e64 fc9065 fd9266 fd9467 fd9668 fd9869 fd9a6a fd9b6b fe9d6c fe9f6d fea16e fea36f fea571 " +
    "fea772 fea973 feaa74 feac76 feae77 feb078 feb27a feb47b feb67c feb77e feb97f febb81 febd82 febf84 fec185 fec287 " +
    "fec488 fec68a fec88c feca8d fecc8f fecd90 fecf92 fed194 fed395 fed597 fed799 fed89a fdda9c fddc9e fddea0 fde0a1 " +
    "fde2a3 fde3a5 fde5a7 fde7a9 fde9aa fdebac fcecae fceeb0 fcf0b2 fcf2b4 fcf4b6 fcf6b8 fcf7b9 fcf9bb fcfbbd fcfdbf",
  viridis:
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
    "d8e219 dae319 dde318 dfe318 e2e418 e5e419 e7e419 eae51a ece51b efe51c f1e51d f4e61e f6e620 f8e621 fbe723 fde725",
};

const TABLES = Object.fromEntries(Object.entries(HEX).map(([name, hexes]) => [name, hexes.split(" ").map((hex) => `#${hex}`)])) as
  Record<StudyPalette, string[]>;

/** The colour of *palette* at t in [0, 1], looked up as matplotlib does (256 bins); t outside is clamped to the ends. */
export function studyPaletteColour(palette: StudyPalette, t: number): string {
  const table = TABLES[palette];
  const share = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  return table[Math.min(table.length - 1, Math.floor(share * table.length))];
}
