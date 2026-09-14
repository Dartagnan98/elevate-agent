from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes.files import create_files_router


@pytest.fixture
def preview(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    outputs = tmp_path / 'outside-output'
    outputs.mkdir()
    app = FastAPI()
    app.include_router(create_files_router(project_root=project, get_elevate_home_func=lambda: tmp_path/'home', load_config_func=lambda: {'file_preview': {'additional_roots': [str(outputs)]}}))
    return TestClient(app), project, outputs


def test_preview_configured_draft_and_local_assets(preview):
    client, _, outputs = preview
    for name, body in [('email.html', '<h1>Draft</h1>'), ('photo with spaces.svg', '<svg/>'), ('style.css', 'body{color:green}'), ('draft–example.txt', 'Unicode file name')]:
        path = outputs/name
        path.write_text(body)
        response = client.get('/api/files/preview', params={'path': str(path)})
        assert response.status_code == 200
        assert response.text == body
    response = client.get('/api/files/preview', params={'path': (outputs/'photo with spaces.svg').as_uri()})
    assert response.status_code == 200


def test_relative_paths_resolve_against_workspace(preview, monkeypatch, tmp_path):
    client, project, _ = preview
    (project/'draft.txt').write_text('workspace draft')
    monkeypatch.chdir(tmp_path)
    assert client.get('/api/files/preview', params={'path': 'draft.txt'}).text == 'workspace draft'


def test_extra_root_does_not_allow_credentials(preview):
    client, _, outputs = preview
    (outputs/'credentials.json').write_text('{}')
    assert client.get('/api/files/preview', params={'path': str(outputs/'credentials.json')}).status_code == 403


def test_reject_remote_file_uri(preview):
    client, _, _ = preview
    assert client.get('/api/files/preview', params={'path': 'file://remote/private.pdf'}).status_code == 400


def test_configured_roots_still_resolve_symlinks(monkeypatch, tmp_path):
    # Exclude the OS temp root in this test so a sibling really is outside.
    import elevate_cli.web_routes.files as module
    monkeypatch.setattr(module.tempfile, 'gettempdir', lambda: str(tmp_path/'allowed-temp'))
    project = tmp_path/'project'; project.mkdir()
    outside = tmp_path/'private'; outside.mkdir()
    target = outside/'secret.txt'; target.write_text('secret')
    (project/'link.txt').symlink_to(target)
    # /tmp is separately a default root; macOS pytest temp dirs are /private/var.
    if str(tmp_path.resolve()).startswith(str(Path('/tmp').resolve())):
        pytest.skip('fixture lives inside an intentionally allowed temporary root')
    app = FastAPI(); app.include_router(create_files_router(project_root=project, get_elevate_home_func=lambda: tmp_path/'home', load_config_func=lambda: {}))
    assert TestClient(app).get('/api/files/preview', params={'path': str(project/'link.txt')}).status_code == 403


def test_video_preview_accepts_range_requests(preview):
    client, _, outputs = preview
    video = outputs/'tour.mp4'; video.write_bytes(b'0123456789' * 100)
    result = client.get('/api/files/preview', params={'path': str(video)}, headers={'Range':'bytes=0-99'})
    assert result.status_code == 206
    assert result.headers['content-type'] == 'video/mp4'
    assert len(result.content) == 100


def test_video_ranges_bypass_response_gzip(preview):
    from fastapi.middleware.gzip import GZipMiddleware
    client, _, outputs = preview
    client.app.add_middleware(GZipMiddleware, minimum_size=32)
    video=outputs/'movie.mp4';video.write_bytes(b'0123456789'*10000)
    result=client.get('/api/files/preview',params={'path':str(video)},headers={'Range':'bytes=1000-4999','Accept-Encoding':'gzip'})
    assert result.status_code==206
    assert result.headers['content-encoding']=='identity'
    assert result.headers['content-range']=='bytes 1000-4999/100000'
    assert result.content==video.read_bytes()[1000:5000]
