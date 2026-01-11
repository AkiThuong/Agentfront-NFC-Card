"""
LLM-based OCR provider template.
Uses vision-capable LLMs (GPT-4V, Claude, etc.) for text extraction.

This is a template showing how to implement LLM-based OCR.
You'll need to add your API key and implement the actual API calls.
"""

import base64
import logging
from typing import List, Optional
from .base import OCRProvider, OCRResult, OCRTextBlock

logger = logging.getLogger(__name__)


class LLMOCRProvider(OCRProvider):
    """
    LLM-based OCR using vision-capable language models.
    
    Advantages:
    - Better context understanding
    - Can handle complex layouts
    - Can extract structured data directly
    - Good at reading handwritten text
    
    Disadvantages:
    - Slower than traditional OCR
    - Requires API access and costs money
    - May have rate limits
    
    Supported LLMs:
    - OpenAI GPT-4 Vision
    - Anthropic Claude 3
    - Google Gemini Pro Vision
    
    Example usage:
        from ocr import LLMOCRProvider
        
        provider = LLMOCRProvider(
            model="gpt-4-vision-preview",
            api_key="sk-xxx"
        )
        result = provider.process_image(image_bytes)
        print(result.full_text)
    """
    
    SUPPORTED_MODELS = {
        "gpt-4-vision-preview": "openai",
        "gpt-4o": "openai",
        "claude-3-opus": "anthropic",
        "claude-3-sonnet": "anthropic",
        "gemini-pro-vision": "google",
    }
    
    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        prompt: Optional[str] = None
    ):
        """
        Initialize LLM OCR provider.
        
        Args:
            model: Model name (e.g., "gpt-4o", "claude-3-sonnet")
            api_key: API key for the LLM service
            prompt: Custom prompt for text extraction
        """
        super().__init__()
        self.name = "llm"
        self.model = model
        self.api_key = api_key
        self.prompt = prompt or self._default_prompt()
    
    def _default_prompt(self) -> str:
        """Default prompt for card text extraction"""
        return """Extract all text from this ID card image.
Return the text in the following JSON format:
{
    "name": "full name on the card",
    "card_number": "card number",
    "date_of_birth": "YYYY-MM-DD",
    "gender": "性別",
    "nationality": "国籍",
    "address": "住所",
    "status_of_residence": "在留資格",
    "period_of_stay": "在留期間",
    "expiration_date": "有効期限",
    "work_permission": "就労制限",
    "raw_text": "all other text on the card"
}

Only include fields that are visible on the card.
For Japanese text, keep it in Japanese.
For dates, use ISO format (YYYY-MM-DD) when possible."""
    
    def is_available(self) -> bool:
        """Check if required libraries are available"""
        # Check for httpx or requests
        try:
            import httpx
            return True
        except ImportError:
            try:
                import requests
                return True
            except ImportError:
                return False
    
    def initialize(self) -> bool:
        """Validate configuration"""
        if not self.api_key:
            logger.error("API key not provided")
            return False
        
        if self.model not in self.SUPPORTED_MODELS:
            logger.warning(f"Unknown model: {self.model}")
        
        return True
    
    def process_image(self, image_data: bytes) -> OCRResult:
        """
        Process image using LLM vision API.
        
        Note: This is a template implementation.
        You need to implement the actual API calls for your chosen LLM.
        """
        if not self.ensure_initialized():
            return OCRResult(
                success=False,
                error="LLM OCR not configured. Set api_key.",
                provider=self.name
            )
        
        try:
            # Encode image to base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')
            
            # Determine provider
            provider = self.SUPPORTED_MODELS.get(self.model, "openai")
            
            if provider == "openai":
                return self._process_openai(image_b64)
            elif provider == "anthropic":
                return self._process_anthropic(image_b64)
            elif provider == "google":
                return self._process_google(image_b64)
            else:
                return OCRResult(
                    success=False,
                    error=f"Unsupported provider: {provider}",
                    provider=self.name
                )
                
        except Exception as e:
            logger.error(f"LLM OCR failed: {e}")
            import traceback
            traceback.print_exc()
            return OCRResult(
                success=False,
                error=str(e),
                provider=self.name
            )
    
    def _process_openai(self, image_b64: str) -> OCRResult:
        """Process using OpenAI GPT-4 Vision"""
        try:
            import httpx
        except ImportError:
            import requests as httpx
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1000
        }
        
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60.0
        )
        
        if response.status_code != 200:
            return OCRResult(
                success=False,
                error=f"OpenAI API error: {response.status_code}",
                provider=self.name
            )
        
        result = response.json()
        text = result["choices"][0]["message"]["content"]
        
        # Create single text block with full response
        return OCRResult(
            success=True,
            text_blocks=[OCRTextBlock(text=text, confidence=1.0)],
            provider=f"{self.name}:{self.model}"
        )
    
    def _process_anthropic(self, image_b64: str) -> OCRResult:
        """Process using Anthropic Claude"""
        # TODO: Implement Anthropic API call
        return OCRResult(
            success=False,
            error="Anthropic implementation not yet available",
            provider=self.name
        )
    
    def _process_google(self, image_b64: str) -> OCRResult:
        """Process using Google Gemini"""
        # TODO: Implement Google Gemini API call
        return OCRResult(
            success=False,
            error="Google Gemini implementation not yet available",
            provider=self.name
        )
    
    def get_install_instructions(self) -> str:
        """Get installation instructions"""
        return "pip install httpx\nSet api_key for your LLM provider"
