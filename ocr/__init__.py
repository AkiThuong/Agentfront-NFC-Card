"""
OCR Module for NFC Card Text Extraction
========================================
Supports multiple OCR backends for extracting text from card images.

Available providers:
- EasyOCR (default) - pip install easyocr
- PaddleOCR - pip install paddleocr paddlepaddle
- LLM OCR (GPT-4V, Claude) - pip install httpx

Usage:
    from ocr import EasyOCRProvider, ZairyuCardParser
    
    # Initialize OCR
    ocr = EasyOCRProvider()
    result = ocr.process_image(image_bytes)
    
    # Parse Zairyu card fields
    parser = ZairyuCardParser()
    fields = parser.parse(result)
    
To add a new OCR provider, inherit from OCRProvider base class.
"""

from .base import OCRProvider, OCRResult, OCRTextBlock
from .easyocr_provider import EasyOCRProvider
from .paddleocr_provider import PaddleOCRProvider
from .llm_provider import LLMOCRProvider
from .parser import ZairyuCardParser, parse_zairyu_ocr

__all__ = [
    # Base classes
    'OCRProvider',
    'OCRResult',
    'OCRTextBlock',
    # Providers
    'EasyOCRProvider',
    'PaddleOCRProvider',
    'LLMOCRProvider',
    # Parsers
    'ZairyuCardParser',
    'parse_zairyu_ocr',
]
