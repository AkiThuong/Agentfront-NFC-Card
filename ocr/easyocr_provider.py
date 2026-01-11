"""
EasyOCR implementation for card text extraction.
Supports Japanese and English text recognition.
"""

import logging
from typing import List
from .base import OCRProvider, OCRResult, OCRTextBlock

logger = logging.getLogger(__name__)

# Try to import dependencies
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    easyocr = None

try:
    from PIL import Image
    import io
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    Image = None
    io = None

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None


class EasyOCRProvider(OCRProvider):
    """
    EasyOCR-based text extraction.
    
    Supports:
    - Japanese text (hiragana, katakana, kanji)
    - English text (Latin alphabet)
    - Mixed Japanese-English content
    
    Optimized for:
    - Zairyu cards (在留カード)
    - Identity documents with mixed text
    
    Install: pip install easyocr
    """
    
    def __init__(self, languages: List[str] = None, use_gpu: bool = False):
        """
        Initialize EasyOCR provider.
        
        Args:
            languages: List of language codes (default: ['ja', 'en'])
            use_gpu: Whether to use GPU acceleration
        """
        super().__init__()
        self.name = "easyocr"
        self.languages = languages or ['ja', 'en']
        self.use_gpu = use_gpu
        self._reader = None
    
    def is_available(self) -> bool:
        """Check if EasyOCR and dependencies are installed"""
        return EASYOCR_AVAILABLE and PILLOW_AVAILABLE and NUMPY_AVAILABLE
    
    def initialize(self) -> bool:
        """Initialize the EasyOCR reader (lazy loading)"""
        if self._reader is not None:
            return True
        
        if not self.is_available():
            logger.error("EasyOCR dependencies not available")
            return False
        
        try:
            logger.info(f"Initializing EasyOCR reader (languages: {self.languages})...")
            self._reader = easyocr.Reader(self.languages, gpu=self.use_gpu)
            logger.info("EasyOCR reader initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
            return False
    
    def process_image(self, image_data: bytes) -> OCRResult:
        """
        Process image and extract text using EasyOCR.
        
        Args:
            image_data: Raw image bytes (JPEG, PNG, JP2, TIFF, etc.)
            
        Returns:
            OCRResult with extracted text blocks
        """
        if not self.ensure_initialized():
            return OCRResult(
                success=False,
                error="EasyOCR not available. Install: pip install easyocr",
                provider=self.name
            )
        
        try:
            # Convert bytes to numpy array
            img = Image.open(io.BytesIO(image_data))
            img_array = np.array(img)
            
            logger.info(f"Running EasyOCR on image (size: {img.size}, mode: {img.mode})...")
            
            # Run OCR
            ocr_results = self._reader.readtext(img_array)
            
            # Convert to OCRTextBlock objects
            text_blocks = []
            for (bbox, text, confidence) in ocr_results:
                # Convert numpy types to native Python types
                conf_value = float(confidence) if hasattr(confidence, 'item') else confidence
                
                # Convert bbox (list of [x,y] points)
                bbox_native = []
                for point in bbox:
                    if hasattr(point, 'tolist'):
                        bbox_native.append(point.tolist())
                    elif isinstance(point, (list, tuple)):
                        bbox_native.append([float(x) if hasattr(x, 'item') else x for x in point])
                    else:
                        bbox_native.append(point)
                
                text_blocks.append(OCRTextBlock(
                    text=text,
                    confidence=conf_value,
                    bbox=bbox_native
                ))
                logger.debug(f"OCR: '{text}' (conf: {conf_value:.2f})")
            
            logger.info(f"EasyOCR extracted {len(text_blocks)} text regions")
            
            return OCRResult(
                success=True,
                text_blocks=text_blocks,
                provider=self.name
            )
            
        except Exception as e:
            logger.error(f"EasyOCR processing failed: {e}")
            import traceback
            traceback.print_exc()
            return OCRResult(
                success=False,
                error=str(e),
                provider=self.name
            )
    
    def get_install_instructions(self) -> str:
        """Get installation instructions"""
        missing = []
        if not EASYOCR_AVAILABLE:
            missing.append("easyocr")
        if not PILLOW_AVAILABLE:
            missing.append("Pillow")
        if not NUMPY_AVAILABLE:
            missing.append("numpy")
        
        if missing:
            return f"pip install {' '.join(missing)}"
        return "All dependencies installed"


# Global singleton instance (optional, for backward compatibility)
_default_provider: EasyOCRProvider = None


def get_default_provider() -> EasyOCRProvider:
    """Get the default EasyOCR provider (singleton)"""
    global _default_provider
    if _default_provider is None:
        _default_provider = EasyOCRProvider()
    return _default_provider
