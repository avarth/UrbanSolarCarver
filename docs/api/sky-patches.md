# Sky Patches

Implements the Tregenza hemisphere subdivision (145 patches) used by all weighted carving modes. Each patch represents a solid-angle region of the sky dome; the weighting functions assign a weight to each patch depending on the analysis mode.

- **Tregenza geometry**: 145 direction vectors and their solid angles, following the standard subdivision used in climate-based daylight modelling.
- **EPW-based weights** (`compute_EPW_based_weights`): for `irradiance` and `benefit`, builds a cumulative sky matrix of direct and diffuse irradiance from an EPW weather file with the Perez all-weather sky model. Benefit keeps only hours with outdoor temperature below the balance point, or scales each hour by simulated weights. For `daylight`, returns the CIE overcast luminance distribution without reading an EPW.
- **Radiative cooling weights** (`compute_radiative_cooling_weights`): long-wave cooling potential per patch from the Martin-Berdahl clear-sky emissivity with Bliss angular attenuation.

::: urbansolarcarver.sky_patches
