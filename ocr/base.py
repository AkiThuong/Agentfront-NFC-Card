"""
Abstract base class for OCR providers.
Implement this interface to add new OCR backends (PaddleOCR, LLM, etc.)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class OCRTextBlock:
    """Single text block detected by OCR"""
    text: str
    confidence: float
    bbox: List[List[float]] = field(default_factory=list)  # Bounding box coordinates
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict"""
        return {
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "bbox": self.bbox
        }


@dataclass
class OCRResult:
    """Result from OCR processing"""
    success: bool
    text_blocks: List[OCRTextBlock] = field(default_factory=list)
    error: Optional[str] = None
    provider: str = "unknown"
    
    @property
    def raw_text(self) -> List[Dict[str, Any]]:
        """Get raw text blocks as list of dicts"""
        return [block.to_dict() for block in self.text_blocks]
    
    @property
    def full_text(self) -> str:
        """Get all text concatenated"""
        return " ".join(block.text for block in self.text_blocks)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict"""
        return {
            "ocr_success": self.success,
            "provider": self.provider,
            "raw_text": self.raw_text,
            "error": self.error
        }


class OCRProvider(ABC):
    """
    Abstract base class for OCR providers.
    
    Implement this interface to add new OCR backends:
    - EasyOCR (current default)
    - PaddleOCR
    - LLM-based OCR (GPT-4V, Claude, etc.)
    - Tesseract
    - Cloud services (Google Vision, AWS Textract)
    
    Example implementation:
    
        class MyOCRProvider(OCRProvider):
            def __init__(self):
                self.name = "my_ocr"
                self._reader = None
            
            def is_available(self) -> bool:
                try:
                    import my_ocr_lib
                    return True
                except ImportError:
                    return False
            
            def initialize(self) -> bool:
                self._reader = MyOCRLib()
                return True
            
            def process_image(self, image_data: bytes) -> OCRResult:
                results = self._reader.read(image_data)
                blocks = [OCRTextBlock(text=r.text, confidence=r.conf) for r in results]
                return OCRResult(success=True, text_blocks=blocks, provider=self.name)
    """
    
    def __init__(self):
        self.name: str = "base"
        self._initialized: bool = False
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this OCR provider's dependencies are available.
        
        Returns:
            True if the required libraries are installed
        """
        pass
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize the OCR engine (lazy loading).
        Called automatically on first use.
        
        Returns:
            True if initialization successful
        """
        pass
    
    @abstractmethod
    def process_image(self, image_data: bytes) -> OCRResult:
        """
        Process an image and extract text.
        
        Args:
            image_data: Raw image bytes (JPEG, PNG, etc.)
            
        Returns:
            OCRResult with extracted text blocks
        """
        pass
    
    def ensure_initialized(self) -> bool:
        """Ensure the OCR engine is initialized"""
        if not self._initialized:
            if not self.is_available():
                logger.error(f"OCR provider {self.name} is not available")
                return False
            if not self.initialize():
                logger.error(f"Failed to initialize OCR provider {self.name}")
                return False
            self._initialized = True
        return True
    
    def get_install_instructions(self) -> str:
        """Get installation instructions for this provider"""
        return f"Install the required dependencies for {self.name}"
