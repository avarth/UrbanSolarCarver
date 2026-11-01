// The six modes as the interface names them (mode_tiles.json: the plain name, the line and tooltip of the tile, what the
// mode needs and what it may protect), and the plain name of an engine mode.
import modeTiles from "./mode_tiles.json";

export interface ModeTile {
  engine_name: string;
  plain_name: string;
  one_line: string;
  tooltip: string;
  needs: string;
  /** What a criterion of the mode may protect, under the drop box of its test surfaces while it has none (7.2: hints only). */
  protects_hint: string;
  symbol: string;
}

export const MODE_TILES: readonly ModeTile[] = modeTiles;

export function plainModeName(engineName: string): string {
  return MODE_TILES.find((tile) => tile.engine_name === engineName)?.plain_name ?? engineName;
}
