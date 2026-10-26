// Threshold updates while a carving run is under way (UX 5.5, 6.4). The engine checks for cancel only between stages, so
// cancelling a one-stage carving run saves nothing: the run in progress is left to end, values that arrive meanwhile replace
// each other, and exactly one more run follows with the last of them. Values are kept by key (the criterion they were given
// for, spec 7.3): a value of one criterion never replaces another criterion's waiting value, and each waiting value runs in turn.

export interface ThresholdUpdateQueue<Value> {
  /** Applies *value* and runs the carving now, or after the run in progress when there is one. *key*: whose value it is. */
  submit: (value: Value, key?: string) => void;
  /** A run is in progress or a value waits for one. */
  busy: () => boolean;
}

/** One submitted value; each submission is its own object, so two submissions of one value stay apart. */
interface Submission<Value> {
  value: Value;
  key: string;
}

/**
 * At most one *applyAndRun* at a time. *applyAndRun* saves the value, starts the carving run and resolves at the run's last
 * event, with whether a run was started for the value (false when the save was not stored, the run did not start or the
 * service had nothing to run); it reports its own failures, and a rejection only ends that call, so a value waiting behind it
 * still runs. *isSuperseded* tells, at any time, whether a newer value of the same key is waiting or being applied: the user has
 * left this value, so the results of its run are not the ones to show, and the newer value's run brings them.
 * *onLastValueEndedWithoutRun* is called when the last value submitted ended without a run: no newer run follows any more,
 * so the run before it is not superseded now, and the results the service holds are the ones to show.
 */
export function createThresholdUpdateQueue<Value = number>(applyAndRun: (value: Value, isSuperseded: () => boolean, key: string) => Promise<boolean>,
                                                          onLastValueEndedWithoutRun: () => void): ThresholdUpdateQueue<Value> {
  let applying: Submission<Value> | null = null;
  const waiting = new Map<string, Submission<Value>>();      // by key, in the order each key first waited

  const newerValueToCome = (submission: Submission<Value>) => {
    const newest = waiting.get(submission.key) ?? (applying?.key === submission.key ? applying : null);
    return newest !== null && newest !== submission;
  };

  const run = async (submission: Submission<Value>): Promise<void> => {
    applying = submission;
    let runStarted = false;
    try {
      runStarted = await applyAndRun(submission.value, () => newerValueToCome(submission), submission.key);
    } catch {
      // applyAndRun has shown what went wrong; the next value still gets its run
    } finally {
      applying = null;
    }
    const next = waiting.values().next().value;
    if (next !== undefined) {
      waiting.delete(next.key);
      void run(next);
    } else if (!runStarted) {
      onLastValueEndedWithoutRun();
    }
  };

  return {
    submit: (value, key = "") => {
      const submission = { value, key };
      if (applying !== null) waiting.set(key, submission);
      else void run(submission);
    },
    busy: () => applying !== null || waiting.size > 0,
  };
}
