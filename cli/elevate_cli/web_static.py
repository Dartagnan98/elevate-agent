from __future__ import annotations

from fastapi.staticfiles import StaticFiles


class ImmutableStaticFiles(StaticFiles):
    """StaticFiles variant for hashed Vite assets."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
