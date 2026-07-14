from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _run_terminal_completion_case(command_result):
    tool_call = SimpleNamespace(
        id="call_complete",
        type="function",
        function=SimpleNamespace(
            name="terminal",
            arguments='{"command":"finish-task"}',
        ),
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason="tool_calls",
            message=SimpleNamespace(content=None, tool_calls=[tool_call]),
        )]
    )

    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = response
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="test/model",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()
        runner._execute_command = MagicMock(return_value=command_result)

        result = runner.run_task("finish the task")

    return result


def test_run_task_kimi_omits_temperature():
    """Kimi models should NOT have client-side temperature overrides.

    The Kimi gateway selects the correct temperature server-side.
    """
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="done", tool_calls=[]),
            )]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="kimi-for-coding",
            base_url="https://api.kimi.com/coding/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()

        result = runner.run_task("2+2")

    assert result["completed"] is False
    assert "temperature" not in client.chat.completions.create.call_args.kwargs


def test_run_task_public_moonshot_kimi_k2_5_omits_temperature():
    """kimi-k2.5 on the public Moonshot API should not get a forced temperature."""
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.base_url = "https://api.moonshot.ai/v1"
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="done", tool_calls=[]),
            )]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="kimi-k2.5",
            base_url="https://api.moonshot.ai/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()

        result = runner.run_task("2+2")

    assert result["completed"] is False
    assert "temperature" not in client.chat.completions.create.call_args.kwargs


def test_filtered_response_never_executes_partial_tool_call():
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="content_filter",
                    message=SimpleNamespace(
                        content="filtered partial",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_filtered",
                                type="function",
                                function=SimpleNamespace(
                                    name="terminal",
                                    arguments='{"command":"touch /tmp/should-not-run"}',
                                ),
                            )
                        ],
                    ),
                )
            ]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="google/gemini-2.5-flash",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()
        runner._execute_command = MagicMock()

        result = runner.run_task("do something")

    assert result["completed"] is False
    runner._execute_command.assert_not_called()


def test_length_response_never_executes_tool_call():
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(
                        content="truncated response",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_truncated",
                                type="function",
                                function=SimpleNamespace(
                                    name="terminal",
                                    arguments='{"command":"touch /tmp/should-not-run"}',
                                ),
                            )
                        ],
                    ),
                )
            ]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="google/gemini-2.5-flash",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()
        runner._execute_command = MagicMock()

        result = runner.run_task("do something")

    assert result["completed"] is False
    runner._execute_command.assert_not_called()


def test_empty_stop_response_never_claims_completion():
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="   ", tool_calls=[]),
                )
            ]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="test/model",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()

        result = runner.run_task("do something")

    assert result["completed"] is False
    assert result["api_calls"] == 1


def test_plain_text_stop_before_sentinel_never_claims_completion():
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content="Done. I completed every requested change.",
                    tool_calls=[],
                ),
            )]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="test/model",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=3,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()
        runner._execute_command = MagicMock()

        result = runner.run_task("make a verified change")

    assert result["completed"] is False
    assert result["api_calls"] == 1
    runner._execute_command.assert_not_called()


def test_missing_finish_reason_never_executes_tool_call():
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call_unconfirmed",
                                type="function",
                                function=SimpleNamespace(
                                    name="terminal",
                                    arguments='{"command":"touch /tmp/should-not-run"}',
                                ),
                            )
                        ],
                    ),
                )
            ]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="test/model",
            base_url="https://openrouter.ai/api/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()
        runner._execute_command = MagicMock()

        result = runner.run_task("do something")

    assert result["completed"] is False
    runner._execute_command.assert_not_called()


def test_nonterminal_text_never_claims_completion():
    for finish_reason in ("length", None):
        with patch("openai.OpenAI") as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=finish_reason,
                        message=SimpleNamespace(
                            content="partial answer",
                            tool_calls=[],
                        ),
                    )
                ]
            )
            mock_openai.return_value = client

            from mini_swe_runner import MiniSWERunner

            runner = MiniSWERunner(
                model="test/model",
                base_url="https://openrouter.ai/api/v1",
                api_key="test-key",
                env_type="local",
                max_iterations=1,
            )
            runner._create_env = MagicMock()
            runner._cleanup_env = MagicMock()

            result = runner.run_task("do something")

        assert result["completed"] is False


def test_incidental_marker_substring_never_claims_completion():
    result = _run_terminal_completion_case({
        "output": "log: MINI_SWE_AGENT_FINAL_OUTPUT was mentioned incidentally\n",
        "exit_code": 0,
        "error": None,
    })

    assert result["completed"] is False


def test_nonzero_command_with_exact_marker_never_claims_completion():
    result = _run_terminal_completion_case({
        "output": "MINI_SWE_AGENT_FINAL_OUTPUT\n",
        "exit_code": 1,
        "error": "command failed",
    })

    assert result["completed"] is False


def test_successful_command_with_standalone_marker_claims_completion():
    result = _run_terminal_completion_case({
        "output": "work complete\nMINI_SWE_AGENT_FINAL_OUTPUT\nsummary follows\n",
        "exit_code": 0,
        "error": None,
    })

    assert result["completed"] is True
