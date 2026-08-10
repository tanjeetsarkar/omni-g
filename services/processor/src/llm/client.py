from __future__ import annotations

import httpx
from openai import AsyncOpenAI

from ..processor.config import Settings, get_settings


class LLMClient:
    """Unified LLM client that can use either OpenRouter or Ollama as the backend."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the LLM client with the provided settings or default settings."""
        self._settings = settings or get_settings()
        self._provider = self._settings.llm_provider.lower()

        if self._provider == "openrouter":
            if not self._settings.openrouter_api_key:
                raise ValueError("OpenRouter API key is required when using OpenRouter provider")

            self._openrouter_client = AsyncOpenAI(
                base_url=self._settings.openrouter_base_url,
                api_key=self._settings.openrouter_api_key,
            )
        elif self._provider == "ollama":
            # For Ollama, we'll use httpx directly
            pass
        else:
            raise ValueError(f"Unsupported LLM provider: {self._provider}")

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using the configured LLM provider.

        Args:
            prompt: The prompt to send to the LLM
            **kwargs: Additional arguments to pass to the LLM

        Returns:
            The generated text response
        """
        if self._provider == "openrouter":
            return await self._generate_openrouter(prompt, **kwargs)
        elif self._provider == "ollama":
            return await self._generate_ollama(prompt, **kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {self._provider}")

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings for the given text using the configured LLM provider.

        Args:
            text: The text to embed

        Returns:
            A list of floats representing the embedding vector
        """
        if self._provider == "openrouter":
            return await self._embed_openrouter(text)
        elif self._provider == "ollama":
            return await self._embed_ollama(text)
        else:
            raise ValueError(f"Unsupported LLM provider: {self._provider}")

    async def _generate_openrouter(self, prompt: str, **kwargs) -> str:
        """Generate text using OpenRouter API."""
        try:
            model = kwargs.get("model", self._settings.openrouter_model)
            response = await self._openrouter_client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], **kwargs
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise Exception(f"OpenRouter generation failed: {str(e)}") from e

    async def _generate_ollama(self, prompt: str, **kwargs) -> str:
        """Generate text using Ollama API."""
        try:
            model = kwargs.get("model", self._settings.ollama_model)
            url = f"{self._settings.ollama_url.rstrip('/')}/api/generate"

            payload = {"model": model, "prompt": prompt, "stream": False, **kwargs}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return str(response.json().get("response", ""))
        except Exception as e:
            raise Exception(f"Ollama generation failed: {str(e)}") from e

    async def _embed_openrouter(self, text: str) -> list[float]:
        """Generate embeddings using OpenRouter API."""
        try:
            # OpenRouter doesn't have a direct embedding API,
            # so we'll use OpenAI-compatible embeddings
            # For now, we'll return a placeholder - in a real implementation,
            # you might use a separate
            # embedding service or a model that supports embeddings
            response = await self._openrouter_client.embeddings.create(
                model=self._settings.openrouter_embedding_model, input=text
            )
            return response.data[0].embedding
        except Exception as e:
            raise Exception(f"OpenRouter embedding failed: {str(e)}") from e

    async def _embed_ollama(self, text: str) -> list[float]:
        """Generate embeddings using Ollama API."""
        try:
            url = f"{self._settings.ollama_url.rstrip('/')}/api/embeddings"

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    url,
                    json={
                        "model": self._settings.ollama_model,
                        "prompt": text,
                    },
                )
                response.raise_for_status()
                data = response.json()
                embedding = data.get("embedding")
                if embedding and isinstance(embedding, list):
                    vector = [float(v) for v in embedding if isinstance(v, int | float)]
                    return vector
                raise Exception("Invalid embedding response structure")
        except Exception as e:
            raise Exception(f"Ollama embedding failed: {str(e)}") from e
