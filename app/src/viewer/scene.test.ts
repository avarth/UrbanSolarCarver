import { expect, test } from "vitest";
import { cameraOrientation, describeView, metresPerPixelAt } from "./scene";

test("camera yaw is the clockwise turn from the top view with +Y up the screen", () => {
  expect(cameraOrientation([0, 0, -1], [0, 1, 0])).toEqual({ yawDegrees: 0, elevationDegrees: 90 });
  const turned = cameraOrientation([0, 0, -1], [Math.sin(Math.PI / 6), Math.cos(Math.PI / 6), 0]);
  expect(turned.yawDegrees).toBeCloseTo(30);
  const level = cameraOrientation([-1, 0, 0], [0, 0, 1]);       // looking along -X
  expect(level.yawDegrees).toBeCloseTo(270);
  expect(level.elevationDegrees).toBeCloseTo(0);
});

test("metres per pixel at the orbit target", () => {
  expect(metresPerPixelAt(100, 90, 1000)).toBeCloseTo(0.2);
});

test("the accessible name lists the layers on screen with their counts and states", () => {
  expect(describeView([])).toBe("3D view, empty.");
  expect(describeView([
    { label: "Maximum volume", detail: null, dimmed: false },
    { label: "Kept voxels, coloured by score", detail: "16 126 voxels", dimmed: true },
  ])).toBe("3D view showing: Maximum volume; Kept voxels, coloured by score, 16 126 voxels, out of date.");
});
