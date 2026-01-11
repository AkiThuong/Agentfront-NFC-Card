"""
NFC Card Readers Module
=======================
Implementations for reading various NFC card types.

Supported cards:
- CCCD (Vietnamese Căn cước công dân)
- Zairyu (Japanese 在留カード Residence Card)
- My Number (Japanese マイナンバーカード)
- Suica/Pasmo/ICOCA (FeliCa transit cards)
- Generic NFC cards (UID only)
"""

from .apdu import APDU
from .bac import BACAuthentication
from .cccd import CCCDReader
from .mynumber import MyNumberCardReader
from .suica import SuicaReader, NfcpySuicaReader
from .zairyu import ZairyuCardReader
from .utils import SMARTCARD_AVAILABLE, CRYPTO_AVAILABLE, NFCPY_AVAILABLE

__all__ = [
    'APDU',
    'BACAuthentication',
    'CCCDReader',
    'MyNumberCardReader',
    'SuicaReader',
    'NfcpySuicaReader',
    'ZairyuCardReader',
    'SMARTCARD_AVAILABLE',
    'CRYPTO_AVAILABLE',
    'NFCPY_AVAILABLE',
]
