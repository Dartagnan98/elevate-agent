import logging

from elevate_cli import oneshot


def test_oneshot_returns_nonzero_but_preserves_nonempty_failure_text(monkeypatch, capsys):
    monkeypatch.setattr(
        oneshot,
        "_run_agent_result",
        lambda *args, **kwargs: {
            "final_response": "The model stopped before completing the task.",
            "failed": True,
            "completed": False,
        },
    )

    try:
        exit_code = oneshot.run_oneshot("finish this")
    finally:
        logging.disable(logging.NOTSET)

    assert exit_code == 1
    assert capsys.readouterr().out == "The model stopped before completing the task.\n"
