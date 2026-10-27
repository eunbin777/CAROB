"""Multi-model LLM client wrapper for evaluation.

The evaluation harness calls multiple models per (task, baseline) cell.
This module provides a registry that returns a chat callable per model id.

Each model id matches the OpenRouter naming convention (e.g.
``"openai/gpt-5"``, ``"anthropic/claude-sonnet-4.6"``).
Set ``OPENROUTER_API_KEY`` in the environment.

Evaluation decoding is greedy with no token cap by default: temperature
0.0, and ``max_tokens`` is sent only when the caller passes one. There is no
response cache; every call goes to the API.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from orgbench.engine.config import base_dir, load_config

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

__all__ = [
    "EvalClientFactory", "build_factory_from_config", "ChatFn",
    "MODEL_PRESETS",
]

ChatFn = Callable[[list[dict]], str]

MODEL_PRESETS: dict[str, list[str]] = {
    "paper": [   # the five models evaluated in the paper
        "openai/gpt-5.4",
        "anthropic/claude-sonnet-4.6",
        "google/gemini-3.1-pro-preview",
        "qwen/qwen3.5-122b-a10b",
        "meta-llama/llama-4-maverick",
    ],
}


class EvalClientFactory:
    """Build per-model chat callables on demand via OpenRouter.

    Usage::

        factory = EvalClientFactory(base_llm_cfg, repo_root)
        chat = factory("openai/gpt-5-mini")
        out = chat([{"role": "system", "content": "..."},
                    {"role": "user", "content": "..."}])
    """

    def __init__(
        self, llm_cfg: dict, base_dir: Path, *,
        json_mode: bool = False,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
    ) -> None:
        if OpenAI is None:
            raise ImportError(
                "openai package required for evaluation. "
                "Install with: pip install openai"
            )
        self._base_url = llm_cfg.get(
            "base_url", "https://openrouter.ai/api/v1")
        self._api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._json_mode = json_mode
        self._temperature = temperature
        self._max_tokens = max_tokens          # None: no output cap sent
        self._clients: dict[str, OpenAI] = {}

    def _client_for(self, model: str) -> OpenAI:
        if not self._api_key:
            raise SystemExit(
                "OPENROUTER_API_KEY is not set. The LLM baselines call models "
                "through OpenRouter; export your key and run again.")
        if model not in self._clients:
            self._clients[model] = OpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
            )
        return self._clients[model]

    def __call__(self, model: str) -> ChatFn:
        client = self._client_for(model)

        def chat(messages: list[dict]) -> str:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
            }
            if self._temperature is not None:
                kwargs["temperature"] = self._temperature
            if self._max_tokens is not None:
                kwargs["max_tokens"] = self._max_tokens
            if self._json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        return chat


def build_factory_from_config(
    config_path: str | Path = "orgbench/config/default.yaml",
    *, json_mode: bool = False, max_tokens: int | None = None,
    temperature: float | None = 0.0,
) -> EvalClientFactory:
    """Read config and build a factory with OpenRouter settings.

    Only ``llm.base_url`` is read from the config; decoding is set by the
    arguments (default greedy, no ``max_tokens``).
    """
    cfg = load_config(config_path)
    root = base_dir(cfg["_config_path"])
    return EvalClientFactory(
        cfg["llm"], root, json_mode=json_mode,
        max_tokens=max_tokens, temperature=temperature)
