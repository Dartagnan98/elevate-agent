from __future__ import annotations

from types import SimpleNamespace

import pytest

from elevate_cli import debug


def test_debug_share_rejects_nonpositive_lines(monkeypatch):
    monkeypatch.setattr(debug, "_best_effort_sweep_expired_pastes", lambda: None)

    with pytest.raises(ValueError, match="--lines must be greater than 0"):
        debug.run_debug_share(
            SimpleNamespace(
                lines=0,
                expire=7,
                local=True,
                no_redact=False,
                session=None,
                last=None,
            )
        )
