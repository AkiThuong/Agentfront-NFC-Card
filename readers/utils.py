"""
Shared utilities and dependency checks for card readers.
"""

import logging

logger = logging.getLogger(__name__)

# Check for pycryptodome
try:
    from Crypto.Cipher import DES3, DES
    from Crypto.Hash import SHA1
    CRYPTO_AVAILABLE = True
except ImportError:
    try:
        from Cryptodome.Cipher import DES3, DES
        from Cryptodome.Hash import SHA1
        CRYPTO_AVAILABLE = True
    except ImportError:
        CRYPTO_AVAILABLE = False
        DES3 = None
        DES = None
        logger.warning("pycryptodome not installed - BAC authentication limited")

# Check for pyscard
try:
    from smartcard.System import readers
    from smartcard.util import toHexString, toBytes
    from smartcard.Exceptions import NoCardException, CardConnectionException
    SMARTCARD_AVAILABLE = True
except ImportError:
    SMARTCARD_AVAILABLE = False
    readers = None
    toHexString = lambda x: ' '.join(f'{b:02X}' for b in x)
    toBytes = lambda x: bytes.fromhex(x.replace(' ', ''))
    NoCardException = Exception
    CardConnectionException = Exception
    logger.warning("pyscard not installed - running in simulation mode")

# Check for nfcpy
try:
    import nfc
    from nfc.tag.tt3_sony import FelicaStandard
    NFCPY_AVAILABLE = True
except ImportError:
    NFCPY_AVAILABLE = False
    nfc = None
    FelicaStandard = None
    logger.info("nfcpy not installed - Suica balance reading limited")

# Check for Pillow
try:
    from PIL import Image
    import io
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    Image = None
    logger.warning("Pillow not installed - image conversion disabled")


def get_hex_string(data):
    """Convert bytes/list to hex string"""
    if SMARTCARD_AVAILABLE:
        return toHexString(data)
    return ' '.join(f'{b:02X}' for b in data)


def get_readers():
    """Get list of available card readers"""
    if not SMARTCARD_AVAILABLE:
        return []
    try:
        return readers()
    except Exception as e:
        logger.error(f"Error getting readers: {e}")
        return []
