from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from agentfix.providers.base import StructuredModelProvider, T


class StaticProvider(StructuredModelProvider):
    def __init__(self, responses: Sequence[BaseModel | dict[str, object]]) -> None:
        self.responses = list(responses)

    def generate_structured(
        self,
        *,
        instructions: str,
        prompt: str,
        output_model: type[T],
        reasoning_effort: str | None = None,
    ) -> T:
        if not self.responses:
            raise AssertionError("No more fake responses queued.")
        response = self.responses.pop(0)
        if isinstance(response, BaseModel):
            return output_model.model_validate(response.model_dump(mode="python"))
        return output_model.model_validate(response)
