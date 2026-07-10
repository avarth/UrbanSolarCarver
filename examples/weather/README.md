# Bundled weather data

`USA_CO_Golden-NREL.724666_TMY3.epw` — Denver Centennial / Golden, Colorado
(NREL site), WMO #724666.

- **Source dataset:** NREL TMY3 (Typical Meteorological Year 3, 2008 release),
  produced by the U.S. National Renewable Energy Laboratory and distributed
  for unrestricted public use.
- **File obtained from:** the EnergyPlus weather-data collection
  (<https://energyplus.net/weather>).
- **Citation:** Wilcox, S., & Marion, W. (2008). *Users Manual for TMY3 Data
  Sets* (NREL/TP-581-43156). National Renewable Energy Laboratory.

This file exists so that the tutorials and the test suite run out of the box.
For real projects, download an EPW for your site (e.g. via Ladybug Tools'
`ladybug.epw` / epwmap, or <https://climate.onebuilding.org>) and set
`epw_path` in your config — or point the `USC_EPW_PATH` environment variable
at it for the test suite.
