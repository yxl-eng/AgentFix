from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class ModelProviderError(RuntimeError):
    pass


class StructuredModelProvider(ABC):
    @abstractmethod
    def generate_structured(
        self,
        *,
        instructions: str,
        prompt: str,
        output_model: type[T],
        reasoning_effort: str | None = None,
    ) -> T:
        raise NotImplementedError
