import threading, warnings, pytest
from urbansolarcarver.run_context import (RunContext, Issue, run_context, report_issue,
                                          report_progress, stage_context, active_context)
from urbansolarcarver.errors import (RunCancelled, ConfigError, ConfigFieldError, InputError,
                                     StageChainError, UrbanSolarCarverError, UrbanSolarCarverWarning)

def test_issues_are_collected_with_their_stage_and_repeats_kept():
    context = RunContext()
    with run_context(context), stage_context("thresholding"):
        report_issue("nothing_carved", "all kept")
        report_issue("nothing_carved", "all kept")
    assert context.issues == [Issue("thresholding", "nothing_carved", "all kept")] * 2

def test_without_a_context_an_issue_is_a_warning():
    with pytest.warns(UrbanSolarCarverWarning, match="all kept"):
        report_issue("nothing_carved", "all kept")

def test_stage_context_without_an_active_context_collects_and_warns():
    with pytest.warns(UrbanSolarCarverWarning):
        with stage_context("massing") as context:
            report_issue("no_plates_fit", "none")
    assert context.issues_of("massing") == (Issue("massing", "no_plates_fit", "none"),)
    assert active_context() is None

def test_progress_reaches_the_callback_with_the_stage():
    calls = []
    with run_context(RunContext(on_progress=lambda s, d, t: calls.append((s, d, t)))), stage_context("preprocessing"):
        report_progress(2, 5)
    assert calls == [("preprocessing", 2, 5)]

def test_cancel_raises_run_cancelled():
    context = RunContext()
    context.cancel()
    with pytest.raises(RunCancelled):
        context.raise_if_cancelled()

def test_exception_classes_keep_their_builtin_bases():
    assert issubclass(ConfigError, ValueError) and issubclass(InputError, ValueError)
    assert issubclass(StageChainError, ValueError)
    assert ConfigError("bad", [ConfigFieldError("voxel_size", "too small")]).errors[0].field == "voxel_size"
    assert all(issubclass(c, UrbanSolarCarverError) for c in (ConfigError, InputError, StageChainError, RunCancelled))
