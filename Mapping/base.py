"""
base.py
=======
Shared machinery for the three LLM-backed agents (Extraction, Mining,
Enrichment). The key method is `structured()`, which forces the model to return
data matching a Pydantic schema by exposing that schema as a single tool and
requiring the model to call it. This is far more reliable than asking for "JSON
in your reply and nothing else" and then regex-parsing.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, List, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

from .config import Config

logger = logging.getLogger("avatar2")

T = TypeVar("T", bound=BaseModel)


class BaseAgent:
    def __init__(self, config: Config):
        self.config = config
        self._client = None  # lazy import so the package loads without the SDK

    @property
    def client(self):
        if self._client is None:
            import anthropic  # imported here so tests can run without the dep

            self.config.require("anthropic_api_key")
            self._client = anthropic.Anthropic(api_key=self.config.anthropic_api_key)
        return self._client

    # ------------------------------------------------------------------ #
    # Structured output via forced tool use
    # ------------------------------------------------------------------ #
    def structured(
        self,
        *,
        model: str,
        system: str,
        user_content: Union[str, List[dict]],
        output_model: Type[T],
        max_tokens: int | None = None,
    ) -> T:
        """Call the model and coerce its answer into `output_model`."""
        schema = output_model.model_json_schema()
        tool = {
            "name": "record",
            "description": f"Record the result as a {output_model.__name__} object.",
            "input_schema": schema,
        }
        messages = [
            {
                "role": "user",
                "content": user_content
                if isinstance(user_content, list)
                else [{"type": "text", "text": user_content}],
            }
        ]

        last_err: Exception | None = None
        for attempt in range(1, self.config.llm_max_retries + 1):
            try:
                resp = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens or self.config.max_tokens,
                    system=system,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": "record"},
                    messages=messages,
                )
                payload = self._first_tool_input(resp)
                return output_model.model_validate(payload)
            except (ValidationError, ValueError) as e:
                last_err = e
                logger.warning("Structured parse failed (attempt %d): %s", attempt, e)
            except Exception as e:  # network / rate limit / API errors
                last_err = e
                logger.warning("LLM call failed (attempt %d): %s", attempt, e)
                time.sleep(min(2 ** attempt, 30))  # exponential backoff

        # Graceful degradation: return an empty instance rather than crashing a
        # long ingestion run on one bad chunk.
        logger.error("Giving up after %d attempts: %s", self.config.llm_max_retries, last_err)
        try:
            return output_model()  # works when all fields have defaults
        except ValidationError:
            raise last_err  # required fields with no default — surface the error

    @staticmethod
    def _first_tool_input(resp: Any) -> dict:
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
        # Fallback: maybe the model emitted JSON as text
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text = block.text.strip().strip("`")
                if text.startswith("json"):
                    text = text[4:]
                return json.loads(text)
        raise ValueError("No tool_use or JSON block in model response.")
