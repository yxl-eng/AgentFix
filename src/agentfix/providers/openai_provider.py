from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from agentfix.providers.base import ModelProviderError, StructuredModelProvider, T


class OpenAIResponsesProvider(StructuredModelProvider):
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        transport: str = "auto",
    ) -> None:
        if not api_key:
            raise ModelProviderError("OpenAI API key is required.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ModelProviderError(
                "The openai package is required. Install project dependencies first."
            ) from exc

        self.model = model
        self.transport = transport
        self.api_key = api_key
        self.base_url = base_url
        client_kwargs: dict[str, str] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = OpenAI(**client_kwargs)

    def generate_structured(
        self,
        *,
        instructions: str,
        prompt: str,
        output_model: type[T],
        reasoning_effort: str | None = None,
    ) -> T:
        response_error: Exception | None = None
        if self.transport in {"auto", "responses"}:
            try:
                return self._generate_with_responses(
                    instructions=instructions,
                    prompt=prompt,
                    output_model=output_model,
                    reasoning_effort=reasoning_effort,
                )
            except Exception as exc:  # pragma: no cover
                response_error = exc
                if self.transport == "responses":
                    raise ModelProviderError(f"Responses API request failed: {exc}") from exc

        if self.transport in {"auto", "chat_completions"}:
            try:
                return self._generate_with_chat_completions(
                    instructions=instructions,
                    prompt=prompt,
                    output_model=output_model,
                )
            except Exception as exc:  # pragma: no cover
                response_error = response_error or exc
                if self.transport == "chat_completions":
                    raise ModelProviderError(f"Chat Completions request failed: {exc}") from exc

        if self.transport in {"auto", "rest_chat_completions"}:
            try:
                return self._generate_with_rest_chat_completions(
                    instructions=instructions,
                    prompt=prompt,
                    output_model=output_model,
                )
            except Exception as exc:  # pragma: no cover
                if response_error is not None:
                    raise ModelProviderError(
                        f"Structured generation failed. Earlier transport error: {response_error}; "
                        f"REST chat completions error: {exc}"
                    ) from exc
                raise ModelProviderError(f"REST chat completions request failed: {exc}") from exc

        raise ModelProviderError(f"Unsupported provider transport mode: {self.transport}")

    def _generate_with_responses(
        self,
        *,
        instructions: str,
        prompt: str,
        output_model: type[T],
        reasoning_effort: str | None = None,
    ) -> T:
        request: dict[str, object] = {
            "model": self.model,
            "instructions": instructions,
            "input": [{"role": "user", "content": prompt}],
            "text_format": output_model,
        }
        if reasoning_effort:
            request["reasoning"] = {"effort": reasoning_effort}
        response = self.client.responses.parse(**request)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise ModelProviderError("Responses API returned no structured output.")
        return parsed

    def _generate_with_chat_completions(
        self,
        *,
        instructions: str,
        prompt: str,
        output_model: type[T],
    ) -> T:
        schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False, indent=2)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{instructions}\n"
                        "Return only a valid JSON object. Do not include markdown fences or extra commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "RESPONSE JSON SCHEMA\n"
                        f"{schema}"
                    ),
                },
            ],
        )
        raw_text = self._extract_chat_text(response)
        json_text = self._extract_json_object(raw_text)
        data = json.loads(json_text)
        return output_model.model_validate(data)

    def _generate_with_rest_chat_completions(
        self,
        *,
        instructions: str,
        prompt: str,
        output_model: type[T],
    ) -> T:
        if not self.base_url:
            raise ModelProviderError("REST chat completions fallback requires a configured base_url.")
        schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False, indent=2)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{instructions}\n"
                        "Return only a valid JSON object. Do not include markdown fences or extra commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "RESPONSE JSON SCHEMA\n"
                        f"{schema}"
                    ),
                },
            ],
        }
        endpoint = str(self.base_url).rstrip("/") + "/chat/completions"
        raw_response = self._post_json(
            endpoint,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        content = raw_response["choices"][0]["message"]["content"]
        json_text = self._extract_json_object(content)
        data = json.loads(json_text)
        return output_model.model_validate(data)

    def _post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise ModelProviderError(f"HTTP {exc.code} from provider: {details}") from exc

    def _extract_chat_text(self, response: Any) -> str:
        try:
            message = response.choices[0].message
        except Exception as exc:
            raise ModelProviderError(f"Unexpected chat completion response shape: {exc}") from exc
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                    continue
                text = getattr(item, "text", None)
                if text:
                    chunks.append(text)
            if chunks:
                return "".join(chunks)
        raise ModelProviderError("Chat completion response did not contain text content.")

    def _extract_json_object(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ModelProviderError("Provider response did not contain a JSON object.")
        candidate = stripped[start : end + 1]
        json.loads(candidate)
        return candidate
