import json
import os

from elevate_cli.source_connector_modules import apple_messages, source_io


def test_missing_directions_file_preserves_legacy_defaults(tmp_path, monkeypatch):
    source_dir = tmp_path / "apple-messages"
    monkeypatch.setattr(apple_messages, "_apple_messages_source_dir", lambda config=None: source_dir)

    assert apple_messages.get_apple_messages_directions({}) == {
        "inbound": True,
        "outbound": True,
    }


def test_malformed_existing_directions_file_fails_outbound_closed(tmp_path, monkeypatch):
    source_dir = tmp_path / "apple-messages"
    source_dir.mkdir()
    (source_dir / "directions.json").write_text('{"outbound":', encoding="utf-8")
    monkeypatch.setattr(apple_messages, "_apple_messages_source_dir", lambda config=None: source_dir)

    assert apple_messages.get_apple_messages_directions({}) == {
        "inbound": True,
        "outbound": False,
    }


def test_unreadable_existing_directions_file_fails_outbound_closed(tmp_path, monkeypatch):
    source_dir = tmp_path / "apple-messages"
    source_dir.mkdir()
    (source_dir / "directions.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(apple_messages, "_apple_messages_source_dir", lambda config=None: source_dir)
    monkeypatch.setattr(
        apple_messages,
        "_read_json",
        lambda _path: (_ for _ in ()).throw(PermissionError("denied")),
    )

    assert apple_messages.get_apple_messages_directions({}) == {
        "inbound": True,
        "outbound": False,
    }


def test_existing_directions_without_boolean_outbound_fails_closed(tmp_path, monkeypatch):
    source_dir = tmp_path / "apple-messages"
    source_dir.mkdir()
    (source_dir / "directions.json").write_text(
        json.dumps({"inbound": True, "outbound": "true"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(apple_messages, "_apple_messages_source_dir", lambda config=None: source_dir)

    assert apple_messages.get_apple_messages_directions({})["outbound"] is False


def test_json_settings_write_replaces_complete_temp_file_atomically(tmp_path, monkeypatch):
    path = tmp_path / "directions.json"
    path.write_text('{"outbound": false}\n', encoding="utf-8")
    real_replace = os.replace
    replacements = []

    def checked_replace(source, destination):
        source_path = type(path)(source)
        destination_path = type(path)(destination)
        replacements.append((source_path, destination_path))
        assert source_path != destination_path
        assert json.loads(source_path.read_text(encoding="utf-8")) == {
            "inbound": True,
            "outbound": True,
        }
        assert json.loads(destination_path.read_text(encoding="utf-8")) == {
            "outbound": False,
        }
        real_replace(source, destination)

    monkeypatch.setattr(source_io.os, "replace", checked_replace)
    source_io._write_json(path, {"inbound": True, "outbound": True})

    assert replacements and replacements[0][1] == path
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "inbound": True,
        "outbound": True,
    }
    assert list(tmp_path.glob(".directions.json.*.tmp")) == []
