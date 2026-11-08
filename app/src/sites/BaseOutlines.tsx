// The base level of each site in the 3D view (design/base-height.md): a dashed outline at the site's lowest vertex plus its base
// height, projected on every camera change, over the view in Inputs. A site with no base height has none.
import { useEffect, useState } from "react";
import type { Point3 } from "../viewer/local_origin";
import type { ViewerScene } from "../viewer/scene";
import { baseHeightOf, elevationRange, outlinePoints, type Heights, type Site } from "./site_geometry";
import "./sites.css";

interface BaseOutlinesProps {
  scene: Pick<ViewerScene, "onCameraChange" | "toScreen">;
  origin: Point3;
  sites: Site[];
  heights: Heights;
}

export function BaseOutlines({ scene, origin, sites, heights }: BaseOutlinesProps) {
  const [, setCameraTick] = useState(0);
  useEffect(() => scene.onCameraChange(() => setCameraTick((tick) => tick + 1)), [scene]);
  const outlines = sites.flatMap((site) => {
    const base = baseHeightOf(site, heights);
    if (base === null) return [];
    const points = outlinePoints(site.points);
    const level = elevationRange(points)[0] + base;
    const projected = points.map(([x, y]) => scene.toScreen([x - origin[0], y - origin[1], level - origin[2]]));
    if (projected.some((point) => point === null)) return [];
    return [projected.map((point) => `${point![0].toFixed(1)},${point![1].toFixed(1)}`).join(" ")];
  });
  if (!outlines.length) return null;
  return (
    <div className="site-base-overlay">
      <svg className="site-base-outlines" aria-hidden="true">
        {outlines.map((points, index) => <polygon key={index} points={points} />)}
      </svg>
    </div>
  );
}
