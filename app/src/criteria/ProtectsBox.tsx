// What a criterion protects (spec 7.2): the drop box of its test surfaces, titled "Test surfaces" as the Inputs box was (one
// criterion brings no new words), with its files. While it has none the box offers to add test surfaces, with a hint of what its
// mode may protect (mode_tiles.json, protects_hint; hints only).
import type { InputFileInfo } from "../api_client/client";
import { messages } from "../messages";
import { InputBox } from "../steps/InputsStep";
import { MODE_TILES } from "../steps/step_summaries";

interface ProtectsBoxProps {
  /** The criterion's test surface files, with their triangle counts. */
  files: InputFileInfo[];
  /** The criterion's mode, whose hint the empty box gives. */
  mode: string;
  /** Adds the files to the criterion; resolves with a message per file that could not be added (empty when all were). */
  onAddFiles: (files: File[]) => Promise<string[]>;
  /** Takes the file out of the criterion; resolves with the reason it could not, or null. */
  onRemoveFile: (fileName: string) => Promise<string | null>;
  /** Why files cannot be added or removed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The files the 3D view cannot draw, one text each naming the file. */
  drawingProblems?: string[];
}

export function protectsHintOf(mode: string): string {
  return MODE_TILES.find((tile) => tile.engine_name === mode)?.protects_hint ?? messages.testSurfacesHint;
}

export function ProtectsBox({ files, mode, onAddFiles, onRemoveFile, disabledReason, drawingProblems }: ProtectsBoxProps) {
  return (
    <InputBox role="test_surfaces" files={files} hint={protectsHintOf(mode)} addLabel={messages.addTestSurfaces}
              weatherLocation={null} weatherHint="" onAddFiles={(_role, chosen) => onAddFiles(chosen)} onRemoveFile={(_role, fileName) => onRemoveFile(fileName)}
              disabledReason={disabledReason} drawingProblems={drawingProblems} showsDisabledReason={false} />
  );
}
