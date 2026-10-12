# Sun Vectors

Computes solar position vectors for specified dates and times using Ladybug's sunpath model. Used by the `time-based` carving mode.

- **`get_sun_vectors`**: returns unit direction vectors pointing toward the sun for each sampled date-time of the analysis period (`sun_steps_per_hour` per hour), dropping positions below `min_altitude` and rotating by `north_deg`.

::: urbansolarcarver.sun
