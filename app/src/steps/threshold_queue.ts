// Threshold updates while a carving run is under way (UX 5.5, 6.4). The engine checks for cancel only between stages, so
// cancelling a one-stage carving run saves nothing: the run in progress is left to end, values that arrive meanwhile replace
// each other, and exactly one more run follows with the last of them.

export interface ThresholdUpdateQueue {
  /** Applies *value* and runs the carving now, or after the run in progress when there is one. */
  submit: (value: number) => void;
  /** A run is in progress or a value waits for one. */
  busy: () => boolean;
}

/**
 * At most one *applyAndRun* at a time. *applyAndRun* saves the value, starts the carving run and resolves at the run's last
 * event; it reports its own failures, and a rejection only ends that call, so a value waiting behind it still runs.
 */
export function createThresholdUpdateQueue(applyAndRun: (value: number) => Promise<void>): ThresholdUpdateQueue {
  let running = false;
  let waitingValue: number | null = null;

  const run = async (value: number): Promise<void> => {
    running = true;
    try {
      await applyAndRun(value);
    } catch {
      // applyAndRun has shown what went wrong; the next value still gets its run
    } finally {
      running = false;
    }
    if (waitingValue !== null) {
      const nextValue = waitingValue;
      waitingValue = null;
      void run(nextValue);
    }
  };

  return {
    submit: (value) => {
      if (running) waitingValue = value;
      else void run(value);
    },
    busy: () => running || waitingValue !== null,
  };
}
