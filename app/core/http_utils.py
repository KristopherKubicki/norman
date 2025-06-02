import asyncio
from typing import Any

import httpx


async def async_request_with_retries(
    method: str,
    url: str,
    retries: int = 2,
    timeout: float = 3.0,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request with retries and exponential backoff."""

    delay = 1.0
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt >= retries:
                raise
            await asyncio.sleep(delay)
            delay *= 2


async def async_get(url: str, **kwargs: Any) -> httpx.Response:
    return await async_request_with_retries("GET", url, **kwargs)


async def async_post(url: str, **kwargs: Any) -> httpx.Response:
    return await async_request_with_retries("POST", url, **kwargs)
