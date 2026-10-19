// The mesh file format of the carved envelope and the building massing (UX 5.7): one of the four formats the engine writes, as a row of radio buttons.
import { useId } from "react";
import { messages } from "../../messages";
import type { ControlProps } from "./NumberInput";

// The formats the engine's final_mesh_format pattern allows.
export const MESH_FORMATS = ["ply", "obj", "stl", "glb"] as const;

interface MeshFormatProps extends ControlProps {
  value: string | null;
  onFormat: (format: string) => void;
}

export function MeshFormat({ value, onFormat, inputId, labelId, invalid, describedBy, disabled }: MeshFormatProps) {
  const choiceName = useId();
  return (
    <div role="radiogroup" aria-labelledby={labelId} aria-invalid={invalid} aria-describedby={describedBy} className="setting-choice-row">
      {MESH_FORMATS.map((format, index) => (
        <label key={format}>
          <input id={index === 0 ? inputId : undefined} type="radio" name={choiceName} value={format} checked={value === format}
                 disabled={disabled} onChange={() => onFormat(format)} />
          {messages.meshFormatNames[format]}
        </label>
      ))}
    </div>
  );
}
