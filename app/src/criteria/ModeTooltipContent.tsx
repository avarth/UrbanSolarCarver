// What a mode's tooltip says, on a mode tile and beside an item of the Add criterion menu.
import { messages } from "../messages";
import type { ModeTile } from "../modes";
import { MessageParts } from "../settings_form/SettingTooltip";

export function ModeTooltipContent({ tile }: { tile: ModeTile }) {
  return (
    <>
      <span className="mode-tooltip-name">{tile.plain_name}</span>
      <span className="mode-tooltip-line">{tile.one_line}</span>
      <span>{tile.tooltip}</span>
      <span>{tile.needs}</span>
      <span className="setting-tooltip-config"><MessageParts parts={messages.engineName(tile.engine_name)} /></span>
    </>
  );
}
