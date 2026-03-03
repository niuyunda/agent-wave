from __future__ import annotations

import agvv.runtime.api as runtime_api


def test_runtime_api_reexports_expected_symbols() -> None:
    expected = {
        "TaskSpec",
        "TaskState",
        "TaskStore",
        "run_task_from_spec",
        "retry_task",
        "cleanup_task",
        "daemon_run_once",
        "daemon_run_loop",
        "list_task_statuses",
    }
    assert expected.issubset(set(runtime_api.__all__))
    for name in expected:
        assert hasattr(runtime_api, name)
        assert getattr(runtime_api, name) is not None
