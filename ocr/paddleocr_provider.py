"""
PaddleOCR implementation for card text extraction.
Optimized for Japanese Zairyu cards (在留カード).

Updated for PaddleOCR 3.x API (3.0+)

Install: pip install paddlepaddle paddleocr

For GPU support:
    pip install paddlepaddle-gpu paddleocr
"""

import logging
import tempfile
import os
from typing import List, Optional
from .base import OCRProvider, OCRResult, OCRTextBlock

logger = logging.getLogger(__name__)

# Try to import dependencies
try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
    # Check PaddleOCR version
    try:
        import paddleocr
        PADDLEOCR_VERSION = getattr(paddleocr, '__version__', '0.0.0')
        PADDLEOCR_V3 = int(PADDLEOCR_VERSION.split('.')[0]) >= 3
    except Exception:
        PADDLEOCR_VERSION = 'unknown'
        PADDLEOCR_V3 = True  # Assume v3+ by default
except ImportError:
    PADDLEOCR_AVAILABLE = False
    PADDLEOCR_VERSION = None
    PADDLEOCR_V3 = False
    PaddleOCR = None

try:
    from PIL import Image, ImageEnhance, ImageFilter
    import io
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    Image = None
    ImageEnhance = None
    ImageFilter = None

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None


class PaddleOCRProvider(OCRProvider):
    """
    PaddleOCR-based text extraction optimized for Zairyu cards.
    
    Updated for PaddleOCR 3.x API.
    
    Features:
    - High accuracy for Japanese text (PP-OCRv5 model)
    - Good at mixed Japanese-English content
    - Fast and lightweight
    - Image preprocessing for better accuracy
    - Supports 100+ languages
    
    Install: 
        pip install paddlepaddle paddleocr
        
        # For GPU support:
        pip install paddlepaddle-gpu paddleocr
    
    Example usage:
        from ocr import PaddleOCRProvider
        
        provider = PaddleOCRProvider()
        result = provider.process_image(image_bytes)
        print(result.full_text)
    """
    
    def __init__(
        self,
        preprocess: bool = True,
        lang: str = 'japan',
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_textline_orientation: bool = False,
        ocr_version: str = 'PP-OCRv5',
        device: str = 'cpu',
        use_mobile_models: bool = True,
    ):
        """
        Initialize PaddleOCR provider for Japanese card reading.
        
        Args:
            preprocess: Apply image preprocessing for better accuracy
            lang: Language for OCR ('japan', 'ch', 'en', 'korean', etc.)
            use_doc_orientation_classify: Enable document orientation classification (slow)
            use_doc_unwarping: Enable document unwarping/deskewing (slow)
            use_textline_orientation: Enable text line orientation detection (adds ~3s startup)
            ocr_version: OCR model version ('PP-OCRv5' or 'PP-OCRv4')
            device: Device to use ('cpu' or 'gpu')
            use_mobile_models: Use faster mobile models instead of server models (default: True)
        """
        super().__init__()
        self.name = "paddleocr"
        self.preprocess = preprocess
        self.lang = lang
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self.use_textline_orientation = use_textline_orientation
        self.ocr_version = ocr_version
        self.device = device
        self.use_mobile_models = use_mobile_models
        self._ocr = None
    
    def is_available(self) -> bool:
        """Check if PaddleOCR and dependencies are installed"""
        return PADDLEOCR_AVAILABLE and PILLOW_AVAILABLE and NUMPY_AVAILABLE
    
    def initialize(self, warmup: bool = False) -> bool:
        """
        Initialize the PaddleOCR engine.
        
        Args:
            warmup: If True, run a dummy OCR to pre-load models into memory.
                   Default is False for faster startup (models load on first use).
        """
        if self._ocr is not None:
            return True
        
        if not self.is_available():
            logger.error("PaddleOCR dependencies not available")
            return False
        
        try:
            logger.info(f"Initializing PaddleOCR (version: {PADDLEOCR_VERSION})...")
            
            # PaddleOCR 3.x initialization
            # Build config for fast startup
            ocr_kwargs = {
                'lang': self.lang,
                'ocr_version': self.ocr_version,
                'device': self.device,
                'use_doc_orientation_classify': self.use_doc_orientation_classify,
                'use_doc_unwarping': self.use_doc_unwarping,
                'use_textline_orientation': self.use_textline_orientation,
            }
            
            # Choose between mobile (fast) or server (accurate) models
            if self.use_mobile_models:
                # Mobile models: ~5x faster to load, good for quick reads
                ocr_kwargs['text_detection_model_name'] = 'PP-OCRv5_mobile_det'
                ocr_kwargs['text_recognition_model_name'] = 'PP-OCRv5_mobile_rec'
                logger.info("Using mobile models for faster loading")
            else:
                # Server models: higher accuracy, better for name recognition
                ocr_kwargs['text_detection_model_name'] = 'PP-OCRv5_server_det'
                ocr_kwargs['text_recognition_model_name'] = 'PP-OCRv5_server_rec'
                logger.info("Using server models for better accuracy")
            
            self._ocr = PaddleOCR(**ocr_kwargs)
            
            model_type = "mobile" if self.use_mobile_models else "server"
            logger.info(f"PaddleOCR initialized (lang={self.lang}, version={self.ocr_version}, models={model_type})")
            
            # Pre-warm the model only if requested (slow!)
            if warmup:
                logger.info("Warming up PaddleOCR models...")
                try:
                    dummy_img = np.ones((100, 200, 3), dtype=np.uint8) * 255
                    dummy_img[40:50, 10:190] = 0  # Add a line
                    
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        tmp_path = tmp.name
                        Image.fromarray(dummy_img).save(tmp_path)
                    
                    try:
                        self._ocr.predict(input=tmp_path)
                        logger.info("PaddleOCR warmup complete")
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                except Exception as e:
                    logger.warning(f"Warmup failed (non-critical): {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _preprocess_image(self, img: Image.Image) -> Image.Image:
        """
        Preprocess image for better OCR accuracy on ID cards.
        
        Optimizations for Zairyu cards:
        - Convert to RGB if needed
        - Limit max size to avoid slow processing
        - Enhance contrast for faded text
        - Sharpen edges
        """
        try:
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Get image dimensions
            width, height = img.size
            
            # IMPORTANT: Limit max size to avoid extremely slow processing
            # Known issue: images around 1200x1400 can take 23+ minutes
            max_dimension = 1280
            if width > max_dimension or height > max_dimension:
                scale = min(max_dimension / width, max_dimension / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                logger.debug(f"Downscaled image from {width}x{height} to {new_width}x{new_height}")
            
            # Upscale only very small images (below 640px)
            min_dimension = 640
            if width < min_dimension and height < min_dimension:
                scale = min(min_dimension / width, min_dimension / height)
                if scale > 1.5:  # Only upscale if significantly small
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    logger.debug(f"Upscaled image from {width}x{height} to {new_width}x{new_height}")
            
            # Enhance contrast (important for faded cards)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.2)
            
            # Enhance sharpness slightly
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.3)
            
            # Slight brightness adjustment for dark images
            img_array = np.array(img)
            mean_brightness = np.mean(img_array)
            if mean_brightness < 100:
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(1.2)
                logger.debug(f"Brightened dark image (mean: {mean_brightness:.1f})")
            
            return img
            
        except Exception as e:
            logger.warning(f"Image preprocessing failed: {e}")
            return img
    
    def process_image(self, image_data: bytes) -> OCRResult:
        """
        Process image and extract text using PaddleOCR.
        
        Args:
            image_data: Raw image bytes (JPEG, PNG, JP2, TIFF, etc.)
            
        Returns:
            OCRResult with extracted text blocks
        """
        if not self.ensure_initialized():
            return OCRResult(
                success=False,
                error="PaddleOCR not available. Install: pip install paddlepaddle paddleocr",
                provider=self.name
            )
        
        tmp_path = None
        try:
            # Load image
            img = Image.open(io.BytesIO(image_data))
            logger.info(f"Processing image: size={img.size}, mode={img.mode}")
            
            # Preprocess if enabled
            if self.preprocess:
                img = self._preprocess_image(img)
                logger.info(f"After preprocessing: size={img.size}")
            
            # PaddleOCR 3.x requires input as file path
            # Save preprocessed image to temp file
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp_path = tmp.name
                img.save(tmp_path)
            
            # Run OCR using predict method (PaddleOCR 3.x API)
            logger.info("Running PaddleOCR...")
            results = self._ocr.predict(input=tmp_path)
            
            # Parse results
            text_blocks = []
            
            # Debug: log the structure
            logger.debug(f"OCR raw result type: {type(results)}")
            
            if results is None:
                logger.warning("PaddleOCR returned None")
                return OCRResult(success=True, text_blocks=[], provider=self.name)
            
            # PaddleOCR 3.x returns result objects with different structure
            # Each result has attributes like rec_texts, rec_scores, dt_polys
            # or can be accessed via dictionary-like interface
            
            if isinstance(results, list):
                for page_result in results:
                    if page_result is None:
                        continue
                    
                    # PaddleOCR 3.x result object - try to access as object first
                    rec_texts = []
                    rec_scores = []
                    rec_polys = []
                    
                    # Try object attribute access (PaddleOCR 3.x result objects)
                    if hasattr(page_result, 'rec_texts'):
                        rec_texts = getattr(page_result, 'rec_texts', []) or []
                        rec_scores = getattr(page_result, 'rec_scores', []) or []
                        rec_polys = getattr(page_result, 'dt_polys', []) or getattr(page_result, 'rec_polys', []) or []
                        logger.info(f"PaddleOCR 3.x object format: {len(rec_texts)} texts found")
                    # Try dictionary access
                    elif isinstance(page_result, dict):
                        rec_texts = page_result.get('rec_texts', []) or []
                        rec_scores = page_result.get('rec_scores', []) or []
                        rec_polys = page_result.get('dt_polys', []) or page_result.get('rec_polys', []) or []
                        logger.info(f"PaddleOCR dict format: {len(rec_texts)} texts found")
                    # Legacy format: list of [bbox, (text, confidence)] tuples
                    elif isinstance(page_result, (list, tuple)):
                        text_blocks.extend(self._parse_legacy_format(page_result))
                        continue
                    
                    # Process rec_texts format
                    for i, text in enumerate(rec_texts):
                        if not text or len(str(text).strip()) == 0:
                            continue
                        
                        confidence = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                        bbox = rec_polys[i] if i < len(rec_polys) else []
                        
                        # Convert bbox to list format
                        bbox_list = self._convert_bbox(bbox)
                        
                        text_blocks.append(OCRTextBlock(
                            text=str(text),
                            confidence=confidence,
                            bbox=bbox_list
                        ))
                        logger.debug(f"OCR: '{text}' (conf: {confidence:.3f})")
            
            logger.info(f"PaddleOCR extracted {len(text_blocks)} text regions")
            
            # Log all extracted text for debugging
            if text_blocks:
                all_text = [b.text for b in text_blocks]
                logger.info(f"Extracted text: {all_text}")
            
            return OCRResult(
                success=True,
                text_blocks=text_blocks,
                provider=self.name
            )
            
        except Exception as e:
            logger.error(f"PaddleOCR processing failed: {e}")
            import traceback
            traceback.print_exc()
            return OCRResult(
                success=False,
                error=str(e),
                provider=self.name
            )
        finally:
            # Clean up temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
    
    def _convert_bbox(self, bbox) -> list:
        """Convert bbox to list format."""
        if bbox is None:
            return []
        if hasattr(bbox, 'tolist'):
            return bbox.tolist()
        if isinstance(bbox, (list, tuple)):
            try:
                return [[float(p[0]), float(p[1])] for p in bbox]
            except (TypeError, ValueError, IndexError):
                return list(bbox) if bbox else []
        return []
    
    def _parse_legacy_format(self, page_result) -> List[OCRTextBlock]:
        """Parse legacy PaddleOCR format: list of [bbox, (text, confidence)] tuples."""
        text_blocks = []
        for line in page_result:
            if line is None:
                continue
            
            try:
                if isinstance(line, (list, tuple)) and len(line) >= 2:
                    bbox = line[0]
                    text_info = line[1]
                    
                    if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                        text = str(text_info[0])
                        confidence = float(text_info[1])
                    else:
                        text = str(text_info)
                        confidence = 0.0
                    
                    if not text or len(text.strip()) == 0:
                        continue
                    
                    bbox_list = self._convert_bbox(bbox)
                    
                    text_blocks.append(OCRTextBlock(
                        text=text,
                        confidence=confidence,
                        bbox=bbox_list
                    ))
                    logger.debug(f"OCR (legacy): '{text}' (conf: {confidence:.3f})")
            except Exception as e:
                logger.warning(f"Failed to parse OCR line: {e}")
                continue
        
        return text_blocks
    
    def get_install_instructions(self) -> str:
        """Get installation instructions for PaddleOCR 3.x"""
        missing = []
        if not PADDLEOCR_AVAILABLE:
            # PaddleOCR 3.x installation
            missing.append("paddlepaddle paddleocr")
        if not PILLOW_AVAILABLE:
            missing.append("Pillow")
        if not NUMPY_AVAILABLE:
            missing.append("numpy")
        
        if missing:
            return f"pip install {' '.join(missing)}"
        return f"All dependencies installed (PaddleOCR {PADDLEOCR_VERSION})"


# Singleton instance
_default_provider: Optional[PaddleOCRProvider] = None


def get_paddle_provider() -> PaddleOCRProvider:
    """Get default PaddleOCR provider (singleton)"""
    global _default_provider
    if _default_provider is None:
        _default_provider = PaddleOCRProvider()
    return _default_provider
