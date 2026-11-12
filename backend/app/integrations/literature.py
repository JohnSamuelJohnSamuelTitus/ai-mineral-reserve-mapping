"""OpenAlex Works API adapter for grounding geological context in peer-reviewed literature."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from app.core.cache import CacheBackend
from app.integrations.base import BaseProviderAdapter, ProviderResponseError


class LiteratureWork(BaseModel):
    openalex_id: str
    title: str
    publication_year: int | None = None
    doi: str | None = None
    cited_by_count: int = 0
    concepts: list[str] = Field(default_factory=list)


class OpenAlexAdapter(BaseProviderAdapter):
    provider_key = "openalex"

    def __init__(
        self,
        *,
        base_url: str = "https://api.openalex.org",
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        cache: CacheBackend | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        super().__init__(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            requests_per_second=5.0,
            cache=cache,
            transport=transport,
        )

    async def search_works(self, query: str, *, per_page: int = 5) -> list[LiteratureWork]:
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")
        params: dict[str, str | int] = {"search": query.strip(), "per-page": min(max(per_page, 1), 25)}
        if self._api_key:
            params["api_key"] = self._api_key

        resp = await self.request("GET", "/works", params=params)
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(self.provider_key, f"Invalid JSON: {exc}") from exc

        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise ProviderResponseError(self.provider_key, "Malformed OpenAlex response: missing 'results'")

        works: list[LiteratureWork] = []
        for item in results:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            concepts = [
                str(c.get("display_name"))
                for c in (item.get("concepts") or [])[:5]
                if isinstance(c, dict) and c.get("display_name")
            ]
            works.append(
                LiteratureWork(
                    openalex_id=str(item["id"]),
                    title=str(item.get("title") or "Untitled"),
                    publication_year=item.get("publication_year"),
                    doi=item.get("doi"),
                    cited_by_count=int(item.get("cited_by_count") or 0),
                    concepts=concepts,
                )
            )
        return works

