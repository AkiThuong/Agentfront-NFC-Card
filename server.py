"""
NFC Bridge Server - Entry Point
================================
WebSocket server for reading NFC cards from web applications.

Supports:
- Vietnamese CCCD (Căn cước công dân)
- Japanese Zairyu Card (在留カード)
- Japanese My Number Card (マイナンバーカード)
- Suica/Pasmo/ICOCA (FeliCa transit cards)
- Generic NFC cards (UID only)

Port: localhost:3005

Usage:
    python server.py

OCR Configuration:
    Uses PaddleOCR by default for best Japanese text accuracy.
    Install: pip install paddlepaddle paddleocr
"""

import asyncio
import logging
import sys
import io
import os

# Skip PaddleOCR network connectivity check (slows startup significantly)
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'

# Fix Windows console encoding for Japanese/Unicode output
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed")
    print("Run: pip install websockets")
    exit(1)

from bridge import NFCBridge
from readers import SMARTCARD_AVAILABLE

# Configuration
HOST = "localhost"
PORT = 3005

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('nfc_bridge.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


def create_ocr_provider():
    """
    Create OCR provider for card text extraction.
    
    Priority:
    1. PaddleOCR (best for Japanese)
    2. EasyOCR (fallback)
    
    Returns:
        OCR provider instance or None if not available
    """
    # Try PaddleOCR first (better for Japanese)
    try:
        from ocr import PaddleOCRProvider
        # Fast configuration: disable slow features for quick startup
        # Models will load on first OCR request
        provider = PaddleOCRProvider(
            preprocess=True,
            lang='japan',
            use_doc_orientation_classify=False,  # Skip document orientation (slow)
            use_doc_unwarping=False,              # Skip unwarping (slow)
            use_textline_orientation=False,       # Skip textline orientation (slow)
        )
        if provider.is_available():
            logger.info("OCR: PaddleOCR ready (models load on first use)")
            return provider
        else:
            logger.warning("OCR: PaddleOCR dependencies not available")
            logger.info(f"OCR: Install with: {provider.get_install_instructions()}")
    except ImportError as e:
        logger.warning(f"OCR: PaddleOCR module not available: {e}")
    
    # Fallback to EasyOCR
    try:
        from ocr import EasyOCRProvider
        provider = EasyOCRProvider(languages=['ja', 'en'])
        if provider.is_available():
            logger.info("OCR: Using EasyOCR provider (fallback)")
            return provider
        else:
            logger.warning("OCR: EasyOCR dependencies not available")
            logger.info(f"OCR: Install with: {provider.get_install_instructions()}")
    except ImportError as e:
        logger.warning(f"OCR: EasyOCR module not available: {e}")
    
    logger.warning("OCR: No OCR provider available")
    return None


async def warmup_ocr_in_background(ocr_provider):
    """
    Warm up OCR models in background thread.
    This preloads all models so first card read is fast.
    """
    if not ocr_provider:
        return
    
    loop = asyncio.get_event_loop()
    
    def do_warmup():
        logger.info("OCR: Starting background warmup (preloading models)...")
        try:
            # This loads all models into memory
            success = ocr_provider.initialize(warmup=True)
            if success:
                logger.info("OCR: ✅ Models preloaded - first read will be fast!")
            else:
                logger.warning("OCR: Warmup failed - first read may be slow")
        except Exception as e:
            logger.error(f"OCR: Warmup error: {e}")
    
    # Run warmup in thread pool to not block the server
    await loop.run_in_executor(None, do_warmup)


async def main():
    """Main server entry point"""
    
    # Create OCR provider (fast - no model loading yet)
    ocr_provider = create_ocr_provider()
    
    # Create bridge with OCR provider
    bridge = NFCBridge(ocr_provider=ocr_provider)
    
    # Determine OCR status message
    if ocr_provider:
        ocr_status = f"{ocr_provider.name} (warming up in background)"
    else:
        ocr_status = "Not available"
    
    # Print startup banner
    print("=" * 60)
    print(f"  NFC Bridge Server v{bridge.VERSION}")
    print("  Supports: CCCD, Zairyu (在留カード), My Number, Suica")
    print("=" * 60)
    print(f"  URL    : ws://{HOST}:{PORT}")
    print(f"  Reader : {bridge.get_reader() or 'Not detected'}")
    print(f"  Status : {'Ready' if SMARTCARD_AVAILABLE else 'Simulation mode'}")
    print(f"  OCR    : {ocr_status}")
    print("=" * 60)
    print()
    
    # Start WebSocket server first (so it can accept connections immediately)
    async with websockets.serve(bridge.handler, HOST, PORT):
        logger.info(f"Server started on ws://{HOST}:{PORT}")
        
        # Start OCR warmup in background (doesn't block server)
        if ocr_provider:
            asyncio.create_task(warmup_ocr_in_background(ocr_provider))
            print("  OCR models loading in background... first read will be fast!")
            print("=" * 60)
            print()
        
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
