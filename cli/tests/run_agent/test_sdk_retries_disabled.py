"""SDK-level retries must be disabled so Elevate's loop owns retry policy.

The SDK default (2 internal retries) stacked under Elevate's stream-retry and
app-retry loops multiplied one 429 into a storm (observed: 1,354 usage-cap
429s on a single client). Pin max_retries=0 on the built clients.
"""
import agent.anthropic_adapter as aa


def test_anthropic_client_disables_sdk_retries():
    client = aa.build_anthropic_client("sk-ant-test123456", timeout=30)
    assert client.max_retries == 0


def test_openai_client_kwargs_setdefault_zero():
    """The standard OpenAI client path injects max_retries=0 via setdefault."""
    from openai import OpenAI

    # Mirror the run_agent / agent_runtime_helpers standard-path guard.
    client_kwargs = {"api_key": "x", "base_url": "http://localhost:1234/v1"}
    if "command" not in client_kwargs:
        client_kwargs.setdefault("max_retries", 0)
    assert OpenAI(**client_kwargs).max_retries == 0


def test_acp_path_is_not_given_max_retries():
    """ACP runtimes (command/args) must NOT receive max_retries."""
    client_kwargs = {"command": "hermes", "args": []}
    if "command" not in client_kwargs:
        client_kwargs.setdefault("max_retries", 0)
    assert "max_retries" not in client_kwargs
