"""OpenAI-compatible client with provider fallback, throttling, retries, cache and JSON validation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

import openai
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from davidtimes.cache import Cache, hash_key
from davidtimes.config import LLMConfig, Provider

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

RETRYABLE = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APIConnectionError,
    openai.APITimeoutError,
)


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class LLMStats:
    calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    by_provider: Counter[str] = field(default_factory=Counter)


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.interval = 60.0 / max(1, per_minute)
        self.last = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            delay = self.last + self.interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.last = time.monotonic()


def parse_json(text: str, schema: type[T]) -> T:
    """Parse model output into the schema; tolerate code fences and stray prose."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the response")
    return schema.model_validate(json.loads(text[start : end + 1]))


def _default_factory(p: Provider, timeout: float) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(base_url=p.base_url, api_key=p.api_key, timeout=timeout, max_retries=0)


class LLMClient:
    def __init__(
        self,
        cfg: LLMConfig,
        cache: Cache,
        *,
        force: bool = False,
        offline: bool = False,
        factory: Callable[[Provider, float], openai.AsyncOpenAI] = _default_factory,
    ) -> None:
        self.cfg, self.cache, self.force, self.offline = cfg, cache, force, offline
        self.factory = factory
        self.stats = LLMStats()
        self._clients: dict[str, openai.AsyncOpenAI] = {}
        self._limiters: dict[str, RateLimiter] = {}

    def available(self, task: str) -> list[Provider]:
        return [p for p in self.cfg.providers if task in p.models and p.api_key]

    async def json(self, task: str, system: str, user: str, schema: type[T]) -> T:
        chain = [p for p in self.cfg.providers if task in p.models]
        key = hash_key(task, system, user, [(p.name, p.models[task]) for p in chain])
        cached = None if self.force else self.cache.get("llm", key)
        if cached is not None:
            self.stats.cache_hits += 1
            return schema.model_validate(cached)
        if self.offline:
            raise LLMError("offline mode and no cached LLM output")

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        raw = await self._complete(task, messages)
        try:
            result = parse_json(raw, schema)
        except (ValueError, ValidationError) as exc:
            log.info("invalid JSON from LLM, retrying once: %s", str(exc)[:200])
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That output failed validation: {str(exc)[:800]}\n"
                                            "Return the corrected JSON only."},
            ]
            result = parse_json(await self._complete(task, messages), schema)
        self.cache.set("llm", key, result.model_dump(mode="json"))
        return result

    async def _complete(self, task: str, messages: list[dict]) -> str:
        providers = self.available(task)
        if not providers:
            raise LLMError("no LLM provider has an API key set")
        errors = []
        for p in providers:
            try:
                return await self._call_with_retry(p, task, messages)
            except openai.APIError as exc:  # 429/5xx after retries, or 4xx: try the next provider
                log.warning("provider %s failed: %s", p.name, str(exc)[:200])
                errors.append(f"{p.name}: {type(exc).__name__}")
        raise LLMError("all providers failed: " + ", ".join(errors))

    async def _call_with_retry(self, p: Provider, task: str, messages: list[dict]) -> str:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(RETRYABLE),
            wait=wait_random_exponential(multiplier=2, max=40),
            stop=stop_after_attempt(3),
            reraise=True,
        ):
            with attempt:
                return await self._call(p, task, messages)
        raise AssertionError("unreachable")

    async def _call(self, p: Provider, task: str, messages: list[dict]) -> str:
        if self.stats.calls >= self.cfg.max_calls_per_run:
            raise BudgetExceeded(f"max_calls_per_run={self.cfg.max_calls_per_run} reached")
        limiter = self._limiters.setdefault(p.name, RateLimiter(self.cfg.requests_per_minute))
        await limiter.wait()
        client = self._clients.get(p.name) or self._clients.setdefault(
            p.name, self.factory(p, self.cfg.timeout_seconds)
        )
        kwargs = dict(p.params.get(task, {}))
        json_mode = self.cfg.json_mode if p.json_mode is None else p.json_mode
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        self.stats.calls += 1
        self.stats.by_provider[p.name] += 1
        log.info("LLM call %d: %s/%s (%s)", self.stats.calls, p.name, p.models[task], task)
        resp = await client.chat.completions.create(
            model=p.models[task], messages=messages, temperature=self.cfg.temperature, **kwargs
        )
        text = resp.choices[0].message.content or ""
        if resp.usage:
            self.stats.prompt_tokens += resp.usage.prompt_tokens or 0
            self.stats.completion_tokens += resp.usage.completion_tokens or 0
        else:  # rough estimate: ~4 characters per token
            self.stats.prompt_tokens += sum(len(m["content"]) for m in messages) // 4
            self.stats.completion_tokens += len(text) // 4
        return text
