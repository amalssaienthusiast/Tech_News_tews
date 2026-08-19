"""
LLM Provider abstraction for Tech News Scraper v3.0

Provides unified interface for:
- Google Gemini (direct API)
- LangChain Gemini wrapper (for prompt templates and chains)
- Fallback to local models (DistilBART)

Hybrid strategy: Gemini for disruption analysis, local for summarization.
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Type variable for generic structured output
T = TypeVar("T", bound=BaseModel)


class ProviderType(str, Enum):
    """Available LLM providers."""
    GEMINI = "gemini"
    LANGCHAIN = "langchain"
    LOCAL = "local"
    AUTO = "auto"  # Auto-select based on availability


@dataclass
class LLMConfig:
    """Configuration for LLM providers."""
    provider: ProviderType = ProviderType.AUTO
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    temperature: float = 0.3
    max_tokens: int = 2048
    fallback_enabled: bool = True
    timeout_seconds: int = 30
    
    # Rate limiting
    requests_per_minute: int = 60
    
    def __post_init__(self):
        if not self.gemini_api_key:
            self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def analyze(
        self, 
        prompt: str, 
        schema: Optional[Type[T]] = None,
        context: Optional[str] = None
    ) -> T | str:
        """
        Analyze content with optional structured output.
        
        Args:
            prompt: The prompt to send to the LLM
            schema: Optional Pydantic model for structured output
            context: Optional additional context
            
        Returns:
            Parsed Pydantic model if schema provided, else raw string
        """
        pass
    
    @abstractmethod
    async def summarize(self, text: str, max_length: int = 150) -> str:
        """
        Generate a concise summary of the text.
        
        Args:
            text: Content to summarize
            max_length: Maximum summary length in words
            
        Returns:
            Summary string
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is available and configured."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging."""
        pass


class GeminiProvider(LLMProvider):
    """
    Direct Google Gemini API provider.
    
    Uses google-generativeai library for direct API access.
    Recommended for production use with structured outputs.
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._client = None
        self._model = None
        self._initialized = False
        
    def _ensure_initialized(self) -> bool:
        """Lazy initialization of Gemini client."""
        if self._initialized:
            return self._client is not None
            
        self._initialized = True
        
        if not self.config.gemini_api_key:
            logger.warning("Gemini API key not configured")
            return False
            
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=self.config.gemini_api_key)
            self._model = genai.GenerativeModel(
                self.config.gemini_model,
                generation_config=genai.GenerationConfig(
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_tokens,
                )
            )
            self._client = genai
            logger.info(f"Gemini provider initialized with model: {self.config.gemini_model}")
            return True
            
        except ImportError:
            logger.error("google-generativeai package not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Gemini: {e}")
            return False
    
    async def analyze(
        self, 
        prompt: str, 
        schema: Optional[Type[T]] = None,
        context: Optional[str] = None
    ) -> T | str:
        """Analyze using Gemini with optional structured output."""
        if not self._ensure_initialized():
            raise RuntimeError("Gemini provider not available")
        
        full_prompt = prompt
        if context:
            full_prompt = f"Context: {context}\n\n{prompt}"
        
        if schema:
            # Add JSON schema instruction for structured output
            schema_json = schema.model_json_schema()
            full_prompt += f"\n\nRespond with valid JSON matching this schema:\n{schema_json}"
        
        try:
            # Run in executor since genai is synchronous
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._model.generate_content(full_prompt)
            )
            
            result_text = response.text.strip()
            
            if schema:
                # Parse JSON response into Pydantic model
                import json
                # Handle markdown code blocks
                if result_text.startswith("```"):
                    lines = result_text.split("\n")
                    result_text = "\n".join(lines[1:-1])
                
                data = json.loads(result_text)
                return schema.model_validate(data)
            
            return result_text
            
        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            raise
    
    async def summarize(self, text: str, max_length: int = 150) -> str:
        """Generate summary using Gemini."""
        prompt = f"""Summarize the following text in {max_length} words or less.
Be concise and capture the key points.

Text:
{text[:3000]}  # Limit input to avoid token limits

Summary:"""
        
        return await self.analyze(prompt)
    
    def is_available(self) -> bool:
        """Check if Gemini is available."""
        return self._ensure_initialized()
    
    @property
    def name(self) -> str:
        return "Gemini"


class LangChainGeminiProvider(LLMProvider):
    """
    LangChain wrapper for Gemini.
    
    Enables prompt templates, chains, and advanced workflows.
    Use when you need LangChain's abstractions.
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._llm = None
        self._initialized = False
        
    def _ensure_initialized(self) -> bool:
        """Lazy initialization of LangChain Gemini."""
        if self._initialized:
            return self._llm is not None
            
        self._initialized = True
        
        if not self.config.gemini_api_key:
            logger.warning("Gemini API key not configured for LangChain")
            return False
            
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            
            self._llm = ChatGoogleGenerativeAI(
                model=self.config.gemini_model,
                google_api_key=self.config.gemini_api_key,
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
            )
            logger.info("LangChain Gemini provider initialized")
            return True
            
        except ImportError:
            logger.error("langchain-google-genai package not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize LangChain Gemini: {e}")
            return False
    
    async def analyze(
        self, 
        prompt: str, 
        schema: Optional[Type[T]] = None,
        context: Optional[str] = None
    ) -> T | str:
        """Analyze using LangChain with optional structured output."""
        if not self._ensure_initialized():
            raise RuntimeError("LangChain Gemini provider not available")
        
        full_prompt = prompt
        if context:
            full_prompt = f"Context: {context}\n\n{prompt}"
        
        try:
            if schema:
                # Use LangChain's with_structured_output
                structured_llm = self._llm.with_structured_output(schema)
                result = await structured_llm.ainvoke(full_prompt)
                return result
            else:
                response = await self._llm.ainvoke(full_prompt)
                return response.content
                
        except Exception as e:
            logger.error(f"LangChain analysis failed: {e}")
            raise
    
    async def summarize(self, text: str, max_length: int = 150) -> str:
        """Generate summary using LangChain Gemini."""
        prompt = f"Summarize in {max_length} words or less:\n\n{text[:3000]}"
        return await self.analyze(prompt)
    
    def is_available(self) -> bool:
        """Check if LangChain Gemini is available."""
        return self._ensure_initialized()
    
    @property
    def name(self) -> str:
        return "LangChain-Gemini"


class LocalProvider(LLMProvider):
    """
    Local model provider using DistilBART for summarization.
    
    Fallback provider when cloud APIs are unavailable.
    Only supports summarization, not structured analysis.
    """
    
    def __init__(self):
        self._summarizer = None
        self._initialized = False
        
    def _ensure_initialized(self) -> bool:
        """Lazy initialization of local models."""
        if self._initialized:
            return self._summarizer is not None
            
        self._initialized = True
        
        try:
            # Import the existing ai_processor module
            from src.ai_processor import initialize_ai_models, summarize_text, is_initialized
            
            if not is_initialized():
                initialize_ai_models()
            
            self._summarizer = summarize_text
            logger.info("Local provider initialized with DistilBART")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize local models: {e}")
            return False
    
    async def analyze(
        self, 
        prompt: str, 
        schema: Optional[Type[T]] = None,
        context: Optional[str] = None
    ) -> T | str:
        """Local provider does not support structured analysis."""
        raise NotImplementedError(
            "Local provider only supports summarization. "
            "Use Gemini or LangChain for structured analysis."
        )
    
    async def summarize(self, text: str, max_length: int = 150) -> str:
        """Generate summary using local DistilBART model."""
        if not self._ensure_initialized():
            return "Local summarization unavailable"
        
        # Run in executor since local model is synchronous
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._summarizer, text)
    
    def is_available(self) -> bool:
        """Check if local models are available."""
        return self._ensure_initialized()
    
    @property
    def name(self) -> str:
        return "Local-DistilBART"


class HybridProvider(LLMProvider):
    """
    Hybrid provider combining Gemini for analysis and local for summarization.
    
    This is the recommended configuration:
    - Uses Gemini's reasoning for market disruption analysis
    - Uses fast local DistilBART for basic summarization
    - Automatic fallback if Gemini unavailable
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._gemini = GeminiProvider(config)
        self._langchain = LangChainGeminiProvider(config)
        self._local = LocalProvider()
        
    async def analyze(
        self, 
        prompt: str, 
        schema: Optional[Type[T]] = None,
        context: Optional[str] = None
    ) -> T | str:
        """
        Analyze using Gemini (primary) or LangChain (fallback).
        
        For structured output, Gemini is preferred.
        """
        # Try Gemini first
        if self._gemini.is_available():
            try:
                return await self._gemini.analyze(prompt, schema, context)
            except Exception as e:
                logger.warning(f"Gemini failed, trying LangChain: {e}")
        
        # Try LangChain as fallback
        if self._langchain.is_available():
            try:
                return await self._langchain.analyze(prompt, schema, context)
            except Exception as e:
                logger.warning(f"LangChain also failed: {e}")
        
        raise RuntimeError("No LLM providers available for analysis")
    
    async def summarize(self, text: str, max_length: int = 150) -> str:
        """
        Summarize using local DistilBART (primary) for speed.
        Falls back to Gemini if local unavailable.
        """
        # Try local first (faster, no API cost)
        if self._local.is_available():
            try:
                return await self._local.summarize(text, max_length)
            except Exception as e:
                logger.warning(f"Local summarization failed: {e}")
        
        # Fallback to Gemini
        if self._gemini.is_available():
            return await self._gemini.summarize(text, max_length)
        
        return "Summarization unavailable"
    
    def is_available(self) -> bool:
        """At least one provider should be available."""
        return (
            self._gemini.is_available() or 
            self._langchain.is_available() or 
            self._local.is_available()
        )
    
    @property
    def name(self) -> str:
        return "Hybrid"


class UnifiedLLMProvider:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UnifiedLLMProvider, cls).__new__(cls)
            cls._instance._client = None
            cls._instance._provider_name = "none"
        return cls._instance

    async def initialize(self):
        async with self._lock:
            if self._client:
                return

            openai_key = os.getenv("OPENAI_API_KEY")
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")

            try:
                if openai_key:
                    from openai import AsyncOpenAI
                    self._client = AsyncOpenAI(api_key=openai_key, timeout=15.0)
                    self._provider_name = "openai"
                    logger.info("LLM Provider initialized: OpenAI")
                elif anthropic_key:
                    from anthropic import AsyncAnthropic
                    self._client = AsyncAnthropic(api_key=anthropic_key, timeout=15.0)
                    self._provider_name = "anthropic"
                    logger.info("LLM Provider initialized: Anthropic")
                else:
                    logger.warning("No LLM API keys found. Falling back to local/truncation summarization.")
                    self._provider_name = "local"
            except ImportError as e:
                logger.warning(f"LLM SDK not installed ({e}). Falling back to local summarization.")
                self._provider_name = "local"

    async def summarize(self, text: str, max_tokens: int = 150) -> str:
        if not self._client:
            await self.initialize()
            if not self._client:
                return text[:max_tokens] + "..."

        try:
            if self._provider_name == "openai":
                resp = await self._client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": f"Summarize this tech news article in 2 sentences:\n\n{text}"}],
                    max_tokens=max_tokens
                )
                return resp.choices[0].message.content.strip()
            elif self._provider_name == "anthropic":
                resp = await self._client.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": f"Summarize this tech news article in 2 sentences:\n\n{text}"}]
                )
                return resp.content[0].text.strip()
        except asyncio.TimeoutError:
            logger.warning("LLM request timed out. Falling back to truncation.")
        except Exception as e:
            logger.error(f"LLM request failed: {e}. Falling back to truncation.")

        return text[:max_tokens] + "..."


# Global provider instance (lazy initialization)
_provider: Optional[LLMProvider] = None


def get_provider(
    provider_type: ProviderType = ProviderType.AUTO,
    config: Optional[LLMConfig] = None
) -> LLMProvider:
    """Factory function to get an LLM provider."""
    global _provider
    
    if config is None:
        config = LLMConfig(provider=provider_type)
    
    if _provider is not None and provider_type == ProviderType.AUTO:
        return _provider
    
    if provider_type == ProviderType.AUTO:
        _provider = HybridProvider(config)
    elif provider_type == ProviderType.GEMINI:
        _provider = GeminiProvider(config)
    elif provider_type == ProviderType.LANGCHAIN:
        _provider = LangChainGeminiProvider(config)
    elif provider_type == ProviderType.LOCAL:
        _provider = LocalProvider()
    else:
        _provider = HybridProvider(config)
    
    logger.info(f"LLM Provider: {_provider.name}")
    return _provider


def reset_provider():
    """Reset the global provider."""
    global _provider
    _provider = None


def get_llm_provider() -> UnifiedLLMProvider:
    return UnifiedLLMProvider()


