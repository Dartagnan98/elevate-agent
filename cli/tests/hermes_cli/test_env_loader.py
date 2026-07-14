import importlib
import os
import sys

from elevate_cli.env_loader import load_elevate_dotenv


def test_user_env_overrides_stale_shell_values(tmp_path, monkeypatch):
    home = tmp_path / "elevate"
    home.mkdir()
    env_file = home / ".env"
    env_file.write_text("OPENAI_BASE_URL=https://new.example/v1\n", encoding="utf-8")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://old.example/v1")

    loaded = load_elevate_dotenv(elevate_home=home)

    assert loaded == [env_file]
    assert os.getenv("OPENAI_BASE_URL") == "https://new.example/v1"


def test_project_env_overrides_stale_shell_values_when_user_env_missing(tmp_path, monkeypatch):
    home = tmp_path / "elevate"
    project_env = tmp_path / ".env"
    project_env.write_text("OPENAI_BASE_URL=https://project.example/v1\n", encoding="utf-8")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://old.example/v1")

    loaded = load_elevate_dotenv(elevate_home=home, project_env=project_env)

    assert loaded == [project_env]
    assert os.getenv("OPENAI_BASE_URL") == "https://project.example/v1"


def test_project_env_is_sanitized_before_loading(tmp_path, monkeypatch):
    home = tmp_path / "elevate"
    project_env = tmp_path / ".env"
    project_env.write_text(
        "TELEGRAM_BOT_TOKEN=8356550917:AAGGEkzg06Hrc3Hjb3Sa1jkGVDOdU_lYy2Q"
        "ANTHROPIC_API_KEY=sk-ant-test123\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    loaded = load_elevate_dotenv(elevate_home=home, project_env=project_env)

    assert loaded == [project_env]
    assert os.getenv("TELEGRAM_BOT_TOKEN") == "8356550917:AAGGEkzg06Hrc3Hjb3Sa1jkGVDOdU_lYy2Q"
    assert os.getenv("ANTHROPIC_API_KEY") == "sk-ant-test123"


def test_user_env_takes_precedence_over_project_env(tmp_path, monkeypatch):
    home = tmp_path / "elevate"
    home.mkdir()
    user_env = home / ".env"
    project_env = tmp_path / ".env"
    user_env.write_text("OPENAI_BASE_URL=https://user.example/v1\n", encoding="utf-8")
    project_env.write_text("OPENAI_BASE_URL=https://project.example/v1\nOPENAI_API_KEY=project-key\n", encoding="utf-8")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://old.example/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    loaded = load_elevate_dotenv(elevate_home=home, project_env=project_env)

    assert loaded == [user_env, project_env]
    assert os.getenv("OPENAI_BASE_URL") == "https://user.example/v1"
    assert os.getenv("OPENAI_API_KEY") == "project-key"


def test_main_import_applies_user_env_over_shell_values(tmp_path, monkeypatch):
    home = tmp_path / "elevate"
    home.mkdir()
    (home / ".env").write_text(
        "OPENAI_BASE_URL=https://new.example/v1\nELEVATE_INFERENCE_PROVIDER=custom\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://old.example/v1")
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "openrouter")

    sys.modules.pop("elevate_cli.main", None)
    importlib.import_module("elevate_cli.main")

    assert os.getenv("OPENAI_BASE_URL") == "https://new.example/v1"
    assert os.getenv("ELEVATE_INFERENCE_PROVIDER") == "custom"


def test_user_env_cannot_replace_launcher_owned_identity(tmp_path, monkeypatch):
    home = tmp_path / "elevate-beta"
    home.mkdir()
    env_file = home / ".env"
    env_file.write_text(
        "ELEVATE_HOME=/tmp/hostile-stable-home\n"
        "ELEVATE_RELEASE_CHANNEL=latest\n"
        "ELEVATE_APP_VERSION=0.0.0-hostile\n"
        "ELEVATE_APP_ARCHITECTURE=x64-hostile\n"
        "ELEVATE_APP_BUNDLE_NAME=Elevate.app\n"
        "ELEVATE_SOURCE_RECEIPT_ID=hostile-receipt\n"
        "OPENAI_BASE_URL=https://profile.example/v1\n",
        encoding="utf-8",
    )
    expected = {
        "ELEVATE_HOME": str(home),
        "ELEVATE_RELEASE_CHANNEL": "beta",
        "ELEVATE_APP_VERSION": "1.2.68",
        "ELEVATE_APP_ARCHITECTURE": "arm64",
        "ELEVATE_APP_BUNDLE_NAME": "Elevate Beta.app",
        "ELEVATE_SOURCE_RECEIPT_ID": "candidate-123",
    }
    for name, value in expected.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://stale.example/v1")

    loaded = load_elevate_dotenv(elevate_home=home)

    assert loaded == [env_file]
    assert {name: os.getenv(name) for name in expected} == expected
    assert os.getenv("OPENAI_BASE_URL") == "https://profile.example/v1"


def test_data_files_cannot_create_launch_identity_when_launcher_omits_it(
    tmp_path, monkeypatch
):
    home = tmp_path / "elevate"
    project_env = tmp_path / ".env"
    project_env.write_text(
        "ELEVATE_HOME=/tmp/injected-home\n"
        "ELEVATE_RELEASE_CHANNEL=beta\n"
        "ELEVATE_SOURCE_RECEIPT_ID=injected-receipt\n",
        encoding="utf-8",
    )
    for name in (
        "ELEVATE_HOME",
        "ELEVATE_RELEASE_CHANNEL",
        "ELEVATE_SOURCE_RECEIPT_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    loaded = load_elevate_dotenv(elevate_home=home, project_env=project_env)

    assert loaded == [project_env]
    assert os.getenv("ELEVATE_HOME") is None
    assert os.getenv("ELEVATE_RELEASE_CHANNEL") is None
    assert os.getenv("ELEVATE_SOURCE_RECEIPT_ID") is None


def test_external_secret_source_cannot_replace_launch_identity(
    tmp_path, monkeypatch
):
    from elevate_cli import env_loader

    home = tmp_path / "elevate-beta"
    expected_home = str(home)
    monkeypatch.setenv("ELEVATE_HOME", expected_home)
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    def hostile_secret_source(_home):
        os.environ["ELEVATE_HOME"] = "/tmp/secret-source-home"
        os.environ["ELEVATE_RELEASE_CHANNEL"] = "latest"

    monkeypatch.setattr(
        env_loader, "_apply_external_secret_sources", hostile_secret_source
    )

    load_elevate_dotenv(elevate_home=home)

    assert os.getenv("ELEVATE_HOME") == expected_home
    assert os.getenv("ELEVATE_RELEASE_CHANNEL") == "beta"


def test_launch_identity_is_restored_when_loading_fails(tmp_path, monkeypatch):
    from elevate_cli import env_loader

    home = tmp_path / "elevate-beta"
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    def failing_secret_source(_home):
        os.environ["ELEVATE_HOME"] = "/tmp/partial-home"
        os.environ["ELEVATE_RELEASE_CHANNEL"] = "latest"
        raise RuntimeError("secret source failed after partial mutation")

    monkeypatch.setattr(
        env_loader, "_apply_external_secret_sources", failing_secret_source
    )

    try:
        load_elevate_dotenv(elevate_home=home)
    except RuntimeError as exc:
        assert str(exc) == "secret source failed after partial mutation"
    else:
        raise AssertionError("expected the simulated loader failure")

    assert os.getenv("ELEVATE_HOME") == str(home)
    assert os.getenv("ELEVATE_RELEASE_CHANNEL") == "beta"


def test_main_import_cannot_downgrade_launcher_beta_identity(tmp_path, monkeypatch):
    from elevate_cli.beta_provider_policy import beta_provider_policy_active

    home = tmp_path / "elevate-beta"
    home.mkdir()
    (home / ".env").write_text(
        "ELEVATE_HOME=/tmp/stable-profile\nELEVATE_RELEASE_CHANNEL=latest\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    sys.modules.pop("elevate_cli.main", None)
    importlib.import_module("elevate_cli.main")

    assert os.getenv("ELEVATE_HOME") == str(home)
    assert os.getenv("ELEVATE_RELEASE_CHANNEL") == "beta"
    assert beta_provider_policy_active()


def test_send_command_reload_cannot_downgrade_launch_identity(
    tmp_path, monkeypatch
):
    from elevate_cli.send_cmd import _load_elevate_env

    home = tmp_path / "elevate-beta"
    home.mkdir()
    (home / ".env").write_text(
        "ELEVATE_HOME=/tmp/stable-profile\n"
        "ELEVATE_RELEASE_CHANNEL=latest\n"
        "TELEGRAM_BOT_TOKEN=fresh-token\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "stale-token")

    _load_elevate_env()

    assert os.getenv("ELEVATE_HOME") == str(home)
    assert os.getenv("ELEVATE_RELEASE_CHANNEL") == "beta"
    assert os.getenv("TELEGRAM_BOT_TOKEN") == "fresh-token"
