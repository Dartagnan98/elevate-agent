from elevate_cli.harness.redaction import redact_sensitive_text, sanitize_browser_snapshot


def test_redacts_bearer_tokens():
    text = "Authorization: Bearer abc.def.ghi"
    redacted = redact_sensitive_text(text)
    assert "abc.def.ghi" not in redacted
    assert "[REDACTED_BEARER_TOKEN]" in redacted


def test_redacts_jwt_like_tokens():
    text = "token eyJabc.def.ghi"
    assert "eyJabc.def.ghi" not in redact_sensitive_text(text)


def test_removes_browser_storage():
    snapshot = {
        "url": "https://example.com",
        "localStorage": {"okta-token-storage": '{"accessToken":"secret"}'},
        "sessionStorage": {"anything": "secret"},
        "text": "safe page text",
    }
    cleaned = sanitize_browser_snapshot(snapshot)
    assert "localStorage" not in cleaned
    assert "sessionStorage" not in cleaned
    assert cleaned["text"] == "safe page text"


def test_redacts_password_fields():
    snapshot = {"fields": [{"type": "password", "name": "pw", "value": "super-secret"}]}
    cleaned = sanitize_browser_snapshot(snapshot)
    assert cleaned["fields"][0]["value"] == "[REDACTED_PASSWORD_FIELD]"
