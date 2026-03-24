"""Public orchestration API surface."""

from agvv.orchestration.git_ops import commit_and_push_branch, git_remote_exists
from agvv.orchestration.layout import (
    adopt_project,
    cleanup_feature,
    cleanup_feature_force,
    init_project,
    layout_paths,
    start_feature,
)
from agvv.orchestration.models import LayoutPaths
from agvv.orchestration.tmux_ops_deprecated import (
    tmux_kill_session,
    tmux_new_session,
    tmux_pipe_pane,
    tmux_session_exists,
)
from agvv.shared.errors import AgvvError

__all__ = [
    "AgvvError",
    "LayoutPaths",
    "layout_paths",
    "init_project",
    "adopt_project",
    "start_feature",
    "cleanup_feature",
    "cleanup_feature_force",
    "tmux_session_exists",
    "tmux_kill_session",
    "tmux_new_session",
    "tmux_pipe_pane",
    "commit_and_push_branch",
    "git_remote_exists",
]
