"""Exercise SPA hosting with an isolated build directory, never backend/static."""
import httpx
import pytest

from tests.static_app_support import isolated_spa

pytestmark = pytest.mark.anyio


@pytest.fixture
def isolated_app(monkeypatch, tmp_path):
    load, static = isolated_spa(monkeypatch, tmp_path)
    (static / 'favicon.ico').write_bytes(b'test-icon')
    (tmp_path / 'secret.txt').write_text('outside static root')
    return load, static


async def test_spa_serves_files_and_routes_but_never_api_errors_or_parent_files(isolated_app):
    load, _ = isolated_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=load()), base_url='http://test') as client:
        for path in ['/', '/terminal', '/terminal/', '/plaid/oauth']:
            response = await client.get(path)
            assert response.status_code == 200 and response.text == '<html>isolated app shell</html>'
            assert response.headers['cache-control'] == 'no-store, no-cache, must-revalidate, max-age=0'
        assert (await client.get('/favicon.ico')).content == b'test-icon'
        assert (await client.get('/favicon.ico')).headers['cache-control'].startswith('no-store')
        for path in ['/nested/client-route', '/%2e%2e/secret.txt']:
            response = await client.get(path)
            assert response.status_code == 404
            assert response.text == '<html>isolated app shell</html>'
        for path in ['/api/unknown', '/api']:
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json()['error']['code'] == 'NOT_FOUND'


async def test_hashed_build_assets_are_cached_but_missing_ones_are_not(isolated_app):
    load, static = isolated_app
    (static / 'assets' / 'main-AbC123.js').write_text('console.log(1)')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=load()), base_url='http://test') as client:
        response = await client.get('/assets/main-AbC123.js')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
        assert 'pragma' not in response.headers
        revalidated = await client.get('/assets/main-AbC123.js', headers={'If-None-Match': response.headers['etag']})
        assert revalidated.status_code == 304
        assert revalidated.headers['cache-control'] == 'public, max-age=31536000, immutable'
        # A chunk from another deploy must not be cached as missing.
        missing = await client.get('/assets/main-Old999.js')
        assert missing.status_code == 404
        assert missing.headers['cache-control'] == 'no-store, no-cache, must-revalidate, max-age=0'
        assert (await client.get('/api/health')).headers['cache-control'].startswith('no-store')


async def test_development_without_a_static_build_keeps_api_available(isolated_app):
    load, static = isolated_app
    static.rename(static.with_name('saved-static'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=load()), base_url='http://test') as client:
        assert (await client.get('/api/health')).json() == {'status': 'ok'}
        assert (await client.get('/client-route')).status_code == 404
