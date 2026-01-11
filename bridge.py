"""
NFC Bridge Server - Main WebSocket Server Implementation
========================================================
WebSocket server for reading NFC cards from web applications.

Supports:
- Vietnamese CCCD (Căn cước công dân)
- Japanese Zairyu Card (在留カード)
- Japanese My Number Card (マイナンバーカード)
- Suica/Pasmo/ICOCA (FeliCa transit cards)
- Generic NFC cards (UID only)
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from enum import Enum
from functools import partial
from typing import Optional, Set, Dict, Any, Tuple

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed")
    print("Run: pip install websockets")
    exit(1)

from readers import (
    APDU, BACAuthentication, 
    CCCDReader, MyNumberCardReader, SuicaReader, ZairyuCardReader,
    SMARTCARD_AVAILABLE, CRYPTO_AVAILABLE
)
from readers.utils import get_hex_string, get_readers

if SMARTCARD_AVAILABLE:
    from smartcard.Exceptions import NoCardException, CardConnectionException
else:
    NoCardException = Exception
    CardConnectionException = Exception

# OCR providers (optional)
try:
    from ocr import EasyOCRProvider, ZairyuCardParser
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    EasyOCRProvider = None
    ZairyuCardParser = None

logger = logging.getLogger(__name__)


class OCRResultCache:
    """
    Simple LRU cache for OCR results.
    Caches OCR results by card number to speed up re-reads of the same card.
    
    Features:
    - Time-based expiry (default 5 minutes)
    - LRU eviction when max size reached
    - Thread-safe for basic operations
    """
    
    def __init__(self, max_size: int = 50, ttl_seconds: int = 300):
        """
        Args:
            max_size: Maximum number of cached results
            ttl_seconds: Time-to-live in seconds (default 5 minutes)
        """
        self._cache: OrderedDict[str, Tuple[float, Dict[str, Any]]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
    
    def _make_key(self, card_number: str, image_hash: str = "") -> str:
        """Create cache key from card number and optional image hash"""
        return f"{card_number}:{image_hash}" if image_hash else card_number
    
    def get(self, card_number: str, image_hash: str = "") -> Optional[Dict[str, Any]]:
        """Get cached OCR result if available and not expired"""
        key = self._make_key(card_number, image_hash)
        
        if key not in self._cache:
            return None
        
        timestamp, result = self._cache[key]
        
        # Check if expired
        if time.time() - timestamp > self._ttl:
            del self._cache[key]
            logger.debug(f"OCR cache expired for {card_number[:4]}****")
            return None
        
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        logger.info(f"OCR cache HIT for card {card_number[:4]}****")
        return result
    
    def set(self, card_number: str, result: Dict[str, Any], image_hash: str = ""):
        """Store OCR result in cache"""
        key = self._make_key(card_number, image_hash)
        
        # Remove oldest if at capacity
        while len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            logger.debug(f"OCR cache evicted oldest entry")
        
        self._cache[key] = (time.time(), result)
        logger.debug(f"OCR cache stored for card {card_number[:4]}****")
    
    def clear(self):
        """Clear all cached results"""
        self._cache.clear()
        logger.info("OCR cache cleared")
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl
        }


class CardType(Enum):
    """Card types that can be detected"""
    ZAIRYU = "zairyu"           # Japanese Residence Card (在留カード)
    MYNUMBER = "mynumber"       # Japanese My Number Card (マイナンバーカード)
    SUICA = "suica"             # Suica/Pasmo/ICOCA (FeliCa transit cards)
    CREDIT = "credit"           # EMV Credit/Debit cards
    PASSPORT = "passport"       # e-Passport / CCCD (ICAO 9303)
    GENERIC = "generic"         # Unknown NFC card
    NONE = "none"               # No card detected


class BridgeState(Enum):
    IDLE = "idle"
    WAITING_FOR_CARD = "waiting_for_card"
    READING = "reading"


class NFCBridge:
    """Main NFC Bridge WebSocket Server"""
    
    VERSION = "2.3.0"  # Updated: async-safe card reading
    
    # Thread pool for blocking smartcard operations
    # This prevents card reading from blocking the WebSocket event loop
    _executor: Optional[ThreadPoolExecutor] = None
    
    def __init__(self, ocr_provider=None):
        """
        Initialize NFC Bridge.
        
        Args:
            ocr_provider: Optional OCR provider for card text extraction.
                         If None, will try to use EasyOCR if available.
        """
        self.state = BridgeState.IDLE
        self.connected_clients: Set = set()
        self.scan_task: Optional[asyncio.Task] = None
        
        # Initialize thread pool executor for blocking operations
        if NFCBridge._executor is None:
            NFCBridge._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nfc_reader")
        
        # Initialize OCR result cache (speeds up re-reads of same card)
        self.ocr_cache = OCRResultCache(max_size=50, ttl_seconds=300)  # 5 min TTL
        
        # Initialize OCR provider
        if ocr_provider:
            self.ocr_provider = ocr_provider
        elif OCR_AVAILABLE:
            self.ocr_provider = EasyOCRProvider()
        else:
            self.ocr_provider = None
            logger.info("No OCR provider available")
    
    def set_ocr_provider(self, provider):
        """Set OCR provider for text extraction"""
        self.ocr_provider = provider
    
    async def run_blocking(self, func, *args, timeout: float = 60.0):
        """
        Run a blocking function in thread pool to avoid blocking the event loop.
        
        Args:
            func: Blocking function to run
            *args: Arguments to pass to the function
            timeout: Maximum time to wait for the operation (default 60s)
            
        Returns:
            Result from the function
            
        Raises:
            asyncio.TimeoutError if operation exceeds timeout
        """
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(NFCBridge._executor, partial(func, *args)),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Operation timed out after {timeout}s")
            raise
    
    async def broadcast(self, message: Dict[str, Any]):
        """Send message to all connected clients"""
        if not self.connected_clients:
            return
        msg = json.dumps(message, ensure_ascii=False)
        for client in list(self.connected_clients):
            try:
                await client.send(msg)
            except:
                self.connected_clients.discard(client)
    
    def get_reader(self):
        """Get first available NFC reader"""
        if not SMARTCARD_AVAILABLE:
            return None
        try:
            r = get_readers()
            return r[0] if r else None
        except:
            return None
    
    def check_card_present(self) -> bool:
        """Check if card is on reader"""
        if not SMARTCARD_AVAILABLE:
            return False
        reader = self.get_reader()
        if not reader:
            return False
        try:
            conn = reader.createConnection()
            conn.connect()
            conn.disconnect()
            return True
        except:
            return False
    
    def detect_card_type(self) -> Dict[str, Any]:
        """
        Quick card type detection without deep reading.
        Identifies card type by trying to select various applications.
        
        Returns:
            Dict with card_type, confidence, and basic info (UID, ATR)
        """
        if not SMARTCARD_AVAILABLE:
            return {
                "success": False,
                "card_type": CardType.NONE.value,
                "error": "Smart card library not available"
            }
        
        reader = self.get_reader()
        if not reader:
            return {
                "success": False,
                "card_type": CardType.NONE.value,
                "error": "No reader found"
            }
        
        try:
            conn = reader.createConnection()
            conn.connect()
            
            result = {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader)
            }
            
            # Get UID
            data, sw1, sw2 = conn.transmit(APDU.GET_UID)
            if sw1 == 0x90 and data:
                result["uid"] = get_hex_string(data).replace(" ", "")
            
            # Get ATR for initial classification
            atr = conn.getATR()
            if atr:
                result["atr"] = get_hex_string(atr)
                atr_hex = get_hex_string(atr).upper().replace(" ", "")
                
                # Check for FeliCa indicators in ATR
                if "FELICA" in str(reader).upper() or "F0" in atr_hex:
                    # Likely FeliCa card (Suica, etc.)
                    result["card_type"] = CardType.SUICA.value
                    result["card_type_name"] = "FeliCa (Suica/Pasmo/ICOCA)"
                    result["confidence"] = "high"
                    conn.disconnect()
                    return result
            
            # Test 1: Try My Number Card JPKI Application
            mynumber_aid = [0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x01]
            select_cmd = [0x00, 0xA4, 0x04, 0x0C, len(mynumber_aid)] + mynumber_aid
            data, sw1, sw2 = conn.transmit(select_cmd)
            if sw1 == 0x90:
                result["card_type"] = CardType.MYNUMBER.value
                result["card_type_name"] = "マイナンバーカード (My Number Card)"
                result["card_type_name_en"] = "My Number Card"
                result["confidence"] = "high"
                result["jpki_supported"] = True
                conn.disconnect()
                return result
            
            # Test 1b: Try My Number Profile AP
            profile_aid = [0xD3, 0x92, 0x10, 0x00, 0x31, 0x00, 0x01, 0x01, 0x04, 0x08]
            select_cmd = [0x00, 0xA4, 0x04, 0x0C, len(profile_aid)] + profile_aid
            data, sw1, sw2 = conn.transmit(select_cmd)
            if sw1 == 0x90:
                result["card_type"] = CardType.MYNUMBER.value
                result["card_type_name"] = "マイナンバーカード (My Number Card)"
                result["card_type_name_en"] = "My Number Card"
                result["confidence"] = "high"
                result["profile_ap_supported"] = True
                conn.disconnect()
                return result
            
            # Test 2: Try Zairyu Card (SELECT MF + DF1)
            # First SELECT MF
            mf_cmd = [0x00, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00]
            data, sw1, sw2 = conn.transmit(mf_cmd)
            mf_success = (sw1 == 0x90)
            
            if mf_success:
                # Try Zairyu DF1 AID
                zairyu_aid = [0xD3, 0x92, 0xF0, 0x00, 0x4F, 0x02, 0x00, 0x00, 
                              0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
                select_cmd = [0x00, 0xA4, 0x04, 0x0C, len(zairyu_aid)] + zairyu_aid
                data, sw1, sw2 = conn.transmit(select_cmd)
                if sw1 == 0x90:
                    result["card_type"] = CardType.ZAIRYU.value
                    result["card_type_name"] = "在留カード (Residence Card)"
                    result["card_type_name_en"] = "Residence Card"
                    result["confidence"] = "high"
                    conn.disconnect()
                    return result
            
            # Test 3: Try ICAO 9303 MRTD (Passport/CCCD)
            mrtd_aid = [0xA0, 0x00, 0x00, 0x02, 0x47, 0x10, 0x01]
            select_cmd = [0x00, 0xA4, 0x04, 0x0C, len(mrtd_aid)] + mrtd_aid
            data, sw1, sw2 = conn.transmit(select_cmd)
            if sw1 == 0x90:
                result["card_type"] = CardType.PASSPORT.value
                result["card_type_name"] = "e-Passport / CCCD"
                result["card_type_name_en"] = "e-Passport or National ID"
                result["confidence"] = "high"
                result["mrtd_supported"] = True
                conn.disconnect()
                return result
            
            # Test 4: Try EMV Credit Card applications
            emv_aids = [
                ([0xA0, 0x00, 0x00, 0x00, 0x04, 0x10, 0x10], "Mastercard"),
                ([0xA0, 0x00, 0x00, 0x00, 0x03, 0x10, 0x10], "Visa"),
                ([0xA0, 0x00, 0x00, 0x00, 0x25, 0x01, 0x01, 0x01], "American Express"),
                ([0xA0, 0x00, 0x00, 0x00, 0x65, 0x10, 0x10, 0x01], "JCB"),
            ]
            
            for aid, brand in emv_aids:
                select_cmd = [0x00, 0xA4, 0x04, 0x00, len(aid)] + aid
                data, sw1, sw2 = conn.transmit(select_cmd)
                if sw1 == 0x90 or sw1 == 0x61:
                    result["card_type"] = CardType.CREDIT.value
                    result["card_type_name"] = f"クレジットカード ({brand})"
                    result["card_type_name_en"] = f"Credit Card ({brand})"
                    result["card_brand"] = brand
                    result["confidence"] = "high"
                    conn.disconnect()
                    return result
            
            # If MF selection worked but no specific app found, might be Zairyu
            if mf_success:
                result["card_type"] = CardType.ZAIRYU.value
                result["card_type_name"] = "在留カード (Residence Card) - 推定"
                result["card_type_name_en"] = "Residence Card (estimated)"
                result["confidence"] = "medium"
                result["note"] = "MF selection succeeded, likely Zairyu card"
                conn.disconnect()
                return result
            
            # Unknown card
            result["card_type"] = CardType.GENERIC.value
            result["card_type_name"] = "不明なNFCカード"
            result["card_type_name_en"] = "Unknown NFC Card"
            result["confidence"] = "low"
            
            conn.disconnect()
            return result
            
        except NoCardException:
            return {
                "success": False,
                "card_type": CardType.NONE.value,
                "error": "NO_CARD",
                "error_ja": "カードが検出されません",
                "error_en": "No card detected on reader"
            }
        except Exception as e:
            logger.error(f"Card detection error: {e}")
            return {
                "success": False,
                "card_type": CardType.NONE.value,
                "error": str(e)
            }
    
    def read_generic_card(self) -> Dict[str, Any]:
        """Read any NFC card - try multiple methods"""
        if not SMARTCARD_AVAILABLE:
            return {
                "success": True,
                "data": {
                    "uid": "SIMULATED_" + datetime.now().strftime("%H%M%S"),
                    "simulated": True
                }
            }
        
        reader = self.get_reader()
        if not reader:
            return {"success": False, "error": "No reader found"}
        
        try:
            conn = reader.createConnection()
            conn.connect()
            
            card_data = {
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader)
            }
            
            # Method 1: Standard GET UID
            data, sw1, sw2 = conn.transmit(APDU.GET_UID)
            if sw1 == 0x90:
                card_data["uid"] = get_hex_string(data).replace(" ", "")
            else:
                card_data["uid_status"] = f"SW={sw1:02X}{sw2:02X}"
            
            # Method 2: Get ATR
            atr = conn.getATR()
            if atr:
                card_data["atr"] = get_hex_string(atr)
                atr_hex = get_hex_string(atr).replace(" ", "")
                if "80" in atr_hex:
                    card_data["protocol_hint"] = "T=0 or T=1"
            
            # Method 3: Try MRTD application
            data, sw1, sw2 = conn.transmit(APDU.SELECT_MRTD_APP)
            if sw1 == 0x90:
                card_data["card_type"] = "ICAO 9303 (CCCD/ePassport)"
                card_data["mrtd_supported"] = True
            else:
                card_data["mrtd_status"] = f"SW={sw1:02X}{sw2:02X}"
                card_data["mrtd_supported"] = False
            
            # Method 4: SELECT MF
            select_mf = [0x00, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00]
            data, sw1, sw2 = conn.transmit(select_mf)
            if sw1 == 0x90 or sw1 == 0x61:
                card_data["master_file"] = True
            
            # Determine card type from ATR
            if atr:
                atr_str = get_hex_string(atr).upper()
                if "FELICA" in str(reader).upper() or "3B8F8001804F" in atr_str.replace(" ", ""):
                    card_data["card_type"] = "Possibly FeliCa or Type-B"
                elif "3B" in atr_str[:2]:
                    card_data["card_type"] = "ISO 14443 Smart Card"
            
            conn.disconnect()
            
            return {"success": True, "data": card_data}
            
        except Exception as e:
            logger.error(f"Read error: {e}")
            return {"success": False, "error": str(e)}
    
    def read_cccd_card(self, card_number: str, birth_date: str, expiry_date: str) -> Dict[str, Any]:
        """Read Vietnamese CCCD card with BAC authentication."""
        if not SMARTCARD_AVAILABLE:
            return {
                "success": True,
                "data": {
                    "uid": "SIMULATED_CCCD",
                    "card_number": card_number,
                    "card_type": "CCCD (Simulated)",
                    "authenticated": True,
                    "simulated": True
                }
            }
        
        reader = self.get_reader()
        if not reader:
            return {"success": False, "error": "No reader found"}
        
        try:
            conn = reader.createConnection()
            conn.connect()
            
            card_data = {
                "card_number_input": card_number,
                "birth_date_input": birth_date,
                "expiry_date_input": expiry_date,
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader)
            }
            
            # Get ATR
            atr = conn.getATR()
            if atr:
                card_data["atr"] = get_hex_string(atr)
            
            # Get UID
            data, sw1, sw2 = conn.transmit(APDU.GET_UID)
            if sw1 == 0x90:
                card_data["uid"] = get_hex_string(data).replace(" ", "")
            
            # Select MRTD application
            data, sw1, sw2 = conn.transmit(APDU.SELECT_MRTD_APP)
            if sw1 != 0x90:
                card_data["app_selected"] = False
                card_data["error"] = f"Cannot select MRTD app: SW={sw1:02X}{sw2:02X}"
                conn.disconnect()
                return {"success": True, "data": card_data}
            
            card_data["app_selected"] = True
            card_data["card_type"] = "CCCD (ICAO 9303)"
            
            # Get challenge from card
            data, sw1, sw2 = conn.transmit(APDU.GET_CHALLENGE)
            if sw1 != 0x90:
                card_data["bac_error"] = f"Cannot get challenge: SW={sw1:02X}{sw2:02X}"
                conn.disconnect()
                return {"success": True, "data": card_data}
            
            rnd_ic = bytes(data)
            card_data["challenge_received"] = True
            
            if not CRYPTO_AVAILABLE:
                card_data["bac_error"] = "pycryptodome not installed"
                card_data["install_hint"] = "pip install pycryptodome"
                conn.disconnect()
                return {"success": True, "data": card_data}
            
            # Perform BAC authentication
            rnd_ifd = os.urandom(8)
            k_ifd = os.urandom(16)
            
            k_enc, k_mac = BACAuthentication.derive_keys(card_number, birth_date, expiry_date)
            
            s = rnd_ifd + rnd_ic + k_ifd
            e_ifd = BACAuthentication.encrypt_data(k_enc, s)
            m_ifd = BACAuthentication.compute_mac(k_mac, e_ifd)
            
            cmd_data = e_ifd + m_ifd
            ext_auth = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data)
            
            data, sw1, sw2 = conn.transmit(ext_auth)
            
            if sw1 == 0x67:
                ext_auth_with_le = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data) + [0x28]
                data, sw1, sw2 = conn.transmit(ext_auth_with_le)
            
            if sw1 == 0x6C:
                correct_le = sw2
                ext_auth_correct = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data) + [correct_le]
                data, sw1, sw2 = conn.transmit(ext_auth_correct)
            
            if sw1 != 0x90:
                card_data["authenticated"] = False
                card_data["auth_error"] = f"Authentication failed: SW={sw1:02X}{sw2:02X}"
                card_data["hint"] = "Check card number, birth date, and expiry date"
                conn.disconnect()
                return {"success": True, "data": card_data}
            
            card_data["authenticated"] = True
            
            response = bytes(data)
            e_ic = response[:32]
            m_ic = response[32:40]
            
            computed_mac = BACAuthentication.compute_mac(k_mac, e_ic)
            if computed_mac != m_ic:
                card_data["mac_verify"] = "WARNING: MAC mismatch"
            
            decrypted = BACAuthentication.decrypt_data(k_enc, e_ic)
            k_ic = decrypted[16:32]
            
            key_seed = bytes(a ^ b for a, b in zip(k_ifd, k_ic))
            ks_enc = BACAuthentication.compute_key(key_seed, "ENC")
            ks_mac = BACAuthentication.compute_key(key_seed, "MAC")
            
            card_data["session_established"] = True
            
            # Try to read data files
            select_com = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x1E]
            data, sw1, sw2 = conn.transmit(select_com)
            if sw1 == 0x90 or sw1 == 0x61:
                read_cmd = [0x00, 0xB0, 0x00, 0x00, 0x04]
                data, sw1, sw2 = conn.transmit(read_cmd)
                if sw1 == 0x90:
                    card_data["ef_com_header"] = get_hex_string(data)
            
            select_dg1 = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x01]
            data, sw1, sw2 = conn.transmit(select_dg1)
            if sw1 == 0x90 or sw1 == 0x61:
                card_data["dg1_selected"] = True
                
                read_cmd = [0x00, 0xB0, 0x00, 0x00, 0x00]
                data, sw1, sw2 = conn.transmit(read_cmd)
                
                if sw1 == 0x90:
                    card_data["dg1_raw"] = get_hex_string(data)
                    try:
                        raw_bytes = bytes(data)
                        mrz_start = raw_bytes.find(b'\x5F\x1F')
                        if mrz_start >= 0:
                            length = raw_bytes[mrz_start + 2]
                            mrz_data = raw_bytes[mrz_start + 3:mrz_start + 3 + length]
                            card_data["mrz"] = mrz_data.decode('utf-8', errors='replace')
                    except:
                        pass
                elif sw1 == 0x6C:
                    read_cmd = [0x00, 0xB0, 0x00, 0x00, sw2]
                    data, sw1, sw2 = conn.transmit(read_cmd)
                    if sw1 == 0x90:
                        card_data["dg1_raw"] = get_hex_string(data)
                elif sw1 == 0x69 and sw2 == 0x88:
                    card_data["dg1_note"] = "Secure messaging required"
            
            select_dg11 = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x0B]
            data, sw1, sw2 = conn.transmit(select_dg11)
            if sw1 == 0x90:
                card_data["dg11_available"] = True
            
            conn.disconnect()
            return {"success": True, "data": card_data}
            
        except NoCardException:
            return {"success": False, "error": "No card on reader"}
        except Exception as e:
            logger.error(f"CCCD read error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def read_mynumber_card(self, pin: str = "") -> Dict[str, Any]:
        """Read Japanese My Number Card."""
        if not SMARTCARD_AVAILABLE:
            return {
                "success": True,
                "data": {
                    "uid": "SIMULATED_MYNUMBER",
                    "card_type": "マイナンバーカード (Simulated)",
                    "my_number": "123456789012",
                    "name": "テスト 太郎",
                    "address": "東京都渋谷区...",
                    "birthdate": "19900101",
                    "gender": "男性",
                    "simulated": True
                }
            }
        
        reader = self.get_reader()
        if not reader:
            return {"success": False, "error": "No reader found"}
        
        try:
            conn = reader.createConnection()
            conn.connect()
            
            card_data = {
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader),
                "card_type": "マイナンバーカード"
            }
            
            atr = conn.getATR()
            if atr:
                card_data["atr"] = get_hex_string(atr)
            
            data, sw1, sw2 = conn.transmit(APDU.GET_UID)
            if sw1 == 0x90:
                card_data["uid"] = get_hex_string(data).replace(" ", "")
            
            mynumber_reader = MyNumberCardReader(conn)
            
            basic_info = mynumber_reader.read_basic_info()
            card_data.update(basic_info)
            
            if pin and len(pin) == 4:
                logger.info("Reading personal info with PIN...")
                
                personal_info = mynumber_reader.read_personal_info(pin)
                
                if "error" in personal_info:
                    card_data["personal_info_error"] = personal_info.get("error")
                    if "remaining_tries" in personal_info:
                        card_data["pin_remaining_tries"] = personal_info["remaining_tries"]
                    if "warning" in personal_info:
                        card_data["warning"] = personal_info["warning"]
                else:
                    if "my_number" in personal_info:
                        card_data["my_number"] = personal_info["my_number"]
                    if "name" in personal_info:
                        card_data["name"] = personal_info["name"]
                    if "address" in personal_info:
                        card_data["address"] = personal_info["address"]
                    if "birthdate" in personal_info:
                        bd = personal_info["birthdate"]
                        if len(bd) == 8:
                            card_data["birthdate"] = f"{bd[:4]}/{bd[4:6]}/{bd[6:8]}"
                        else:
                            card_data["birthdate"] = bd
                    if "gender" in personal_info:
                        card_data["gender"] = personal_info["gender"]
                    
                    card_data["pin_verified"] = True
                    card_data["personal_info_read"] = True
            else:
                card_data["note"] = "4桁のPINを入力すると個人番号・氏名・住所などが読み取れます"
            
            conn.disconnect()
            return {"success": True, "data": card_data}
            
        except NoCardException:
            return {"success": False, "error": "No card on reader"}
        except Exception as e:
            logger.error(f"My Number card read error: {e}")
            return {"success": False, "error": str(e)}
    
    def read_suica_card(self, use_nfcpy: bool = True) -> Dict[str, Any]:
        """Read Suica/Pasmo/ICOCA transit cards."""
        from readers.suica import SuicaReader, NfcpySuicaReader
        from readers.utils import NFCPY_AVAILABLE
        
        # Try nfcpy subprocess for full access
        if use_nfcpy and NFCPY_AVAILABLE:
            logger.info("Attempting Suica read via nfcpy subprocess...")
            try:
                import subprocess
                import sys
                
                script_path = os.path.join(os.path.dirname(__file__), 'suica_subprocess.py')
                
                if os.path.exists(script_path):
                    result = subprocess.run(
                        [sys.executable, script_path],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=os.path.dirname(__file__)
                    )
                    
                    if result.returncode == 0 and result.stdout:
                        try:
                            data = json.loads(result.stdout)
                            if data.get("success"):
                                return {"success": True, "data": data.get("data", {})}
                            else:
                                logger.warning(f"Suica subprocess error: {data.get('error')}")
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON from subprocess")
                    
                    if result.stderr:
                        logger.info(f"Subprocess stderr: {result.stderr[:500]}")
                else:
                    logger.warning(f"suica_subprocess.py not found")
                    
            except subprocess.TimeoutExpired:
                logger.warning("Suica subprocess timed out")
            except Exception as e:
                logger.warning(f"nfcpy subprocess error: {e}")
        
        # Fallback to PC/SC
        if not SMARTCARD_AVAILABLE:
            return {
                "success": True,
                "data": {
                    "idm": "SIMULATED_SUICA",
                    "card_type": "Suica (Simulated)",
                    "balance": "¥1,234",
                    "simulated": True
                }
            }
        
        reader = self.get_reader()
        if not reader:
            return {"success": False, "error": "No reader found"}
        
        try:
            conn = reader.createConnection()
            conn.connect()
            
            card_data = {
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader),
                "access_method": "PC/SC (limited)"
            }
            
            atr = conn.getATR()
            if atr:
                card_data["atr"] = get_hex_string(atr)
            
            suica_reader = SuicaReader(conn)
            result = suica_reader.read_card()
            card_data.update(result)
            
            if "error" in result:
                data, sw1, sw2 = conn.transmit(APDU.GET_UID)
                if sw1 == 0x90:
                    card_data["uid"] = get_hex_string(data).replace(" ", "")
                    card_data["note"] = "FeliCa commands failed - showing UID only"
            
            conn.disconnect()
            return {"success": True, "data": card_data}
            
        except NoCardException:
            return {"success": False, "error": "No card on reader"}
        except Exception as e:
            logger.error(f"Suica card read error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def read_zairyu_card(self, card_number: str = "") -> Dict[str, Any]:
        """Read Japanese Zairyu (Residence) Card."""
        if not SMARTCARD_AVAILABLE:
            return {
                "success": True,
                "data": {
                    "uid": "SIMULATED_ZAIRYU",
                    "card_type": "在留カード",
                    "card_type_en": "Residence Card",
                    "authenticated": True,
                    "simulated": True,
                    "card_number_input": card_number,
                    "note": "Simulation mode - pyscard not installed"
                }
            }
        
        reader = self.get_reader()
        if not reader:
            return {"success": False, "error": "No reader found"}
        
        try:
            conn = reader.createConnection()
            conn.connect()
            
            zairyu_reader = ZairyuCardReader(conn, ocr_provider=self.ocr_provider)
            
            if card_number:
                if len(card_number) != 12:
                    conn.disconnect()
                    return {
                        "success": False,
                        "error": "INVALID_CARD_NUMBER",
                        "error_ja": "在留カード番号は12桁である必要があります",
                        "error_en": "Card number must be 12 characters",
                        "hint": "Example: AB12345678CD"
                    }
                
                result = zairyu_reader.read_all_data(card_number)
            else:
                result = zairyu_reader.read_basic_info()
            
            conn.disconnect()
            return {"success": True, "data": result}
            
        except NoCardException:
            return {
                "success": False,
                "error": "NO_CARD",
                "error_ja": "カードが検出されません",
                "error_en": "No card detected on reader"
            }
        except Exception as e:
            logger.error(f"Zairyu card read error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def _blocking_read_mynumber(self, pin: str) -> Dict[str, Any]:
        """
        Blocking implementation of My Number card reading.
        This runs in a thread pool to avoid blocking the event loop.
        All blocking operations (including card presence check) happen here.
        """
        reader = self.get_reader()
        if not reader:
            return {
                "success": False,
                "error": "NO_READER",
                "error_ja": "カードリーダーが接続されていません",
                "error_en": "No card reader connected"
            }
        
        # Check if card is present (this is blocking, so we do it here in the thread)
        if not self.check_card_present():
            return {
                "success": False,
                "error": "NO_CARD",
                "error_ja": "カードが検出されません",
                "error_en": "No card detected on reader"
            }
        
        conn = None
        try:
            conn = reader.createConnection()
            conn.connect()
            
            mynumber_reader = MyNumberCardReader(conn)
            
            logger.info("API: Reading My Number card personal info...")
            result = mynumber_reader.read_personal_info(pin)
            
            if "error" in result:
                error_msg = result.get("error", "")
                remaining = result.get("remaining_tries", -1)
                
                if "PIN verification failed" in error_msg:
                    if remaining == 0:
                        return {
                            "success": False,
                            "error": "CARD_LOCKED",
                            "error_ja": "カードがロックされています",
                            "error_en": "Card is locked",
                            "remaining_tries": 0
                        }
                    else:
                        return {
                            "success": False,
                            "error": "WRONG_PIN",
                            "error_ja": f"PINが間違っています（残り{remaining}回）",
                            "error_en": f"Wrong PIN ({remaining} tries remaining)",
                            "remaining_tries": remaining
                        }
                elif "Cannot select Profile AP" in error_msg:
                    return {
                        "success": False,
                        "error": "NOT_MYNUMBER_CARD",
                        "error_ja": "マイナンバーカードではありません",
                        "error_en": "This is not a My Number card"
                    }
                else:
                    return {
                        "success": False,
                        "error": "READ_ERROR",
                        "error_ja": f"読み取りエラー: {error_msg}",
                        "error_en": f"Read error: {error_msg}"
                    }
            
            response = {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader)
            }
            
            if "my_number" in result:
                response["my_number"] = result["my_number"]
            if "name" in result:
                response["name"] = result["name"]
            if "address" in result:
                response["address"] = result["address"]
            if "birthdate" in result:
                bd = result["birthdate"]
                if len(bd) == 8:
                    response["birthdate"] = f"{bd[:4]}/{bd[4:6]}/{bd[6:8]}"
                else:
                    response["birthdate"] = bd
            if "gender" in result:
                response["gender"] = result["gender"]
            
            logger.info(f"API: Successfully read My Number card")
            return response
            
        except NoCardException:
            return {
                "success": False,
                "error": "CARD_REMOVED",
                "error_ja": "カードが取り除かれました",
                "error_en": "Card was removed during reading"
            }
        except CardConnectionException as e:
            return {
                "success": False,
                "error": "CONNECTION_ERROR",
                "error_ja": "カードとの通信エラー",
                "error_en": "Communication error with card",
                "detail": str(e)
            }
        except Exception as e:
            logger.error(f"Blocking read_mynumber error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": "UNKNOWN_ERROR",
                "error_ja": f"予期しないエラー: {str(e)}",
                "error_en": f"Unexpected error: {str(e)}"
            }
        finally:
            # CRITICAL: Always disconnect to release the reader
            if conn:
                try:
                    conn.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting card: {e}")
    
    async def api_read_mynumber(self, pin: str) -> Dict[str, Any]:
        """API endpoint for reading My Number card."""
        if not SMARTCARD_AVAILABLE:
            return {
                "success": False,
                "error": "NO_SMARTCARD_LIB",
                "error_ja": "スマートカードライブラリが利用できません",
                "error_en": "Smart card library not available"
            }
        
        # Quick validation (non-blocking)
        if not pin:
            return {
                "success": False,
                "error": "NO_PIN",
                "error_ja": "PINが入力されていません",
                "error_en": "PIN is required"
            }
        
        if len(pin) != 4 or not pin.isdigit():
            return {
                "success": False,
                "error": "INVALID_PIN_FORMAT",
                "error_ja": "PINは4桁の数字である必要があります",
                "error_en": "PIN must be 4 digits"
            }
        
        try:
            # Run ALL blocking operations in thread pool (including card presence check)
            result = await self.run_blocking(
                self._blocking_read_mynumber, 
                pin,
                timeout=30.0  # 30 second timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.error("My Number card read timed out")
            return {
                "success": False,
                "error": "TIMEOUT",
                "error_ja": "カード読み取りがタイムアウトしました",
                "error_en": "Card reading timed out"
            }
        except Exception as e:
            logger.error(f"API read_mynumber error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": "UNKNOWN_ERROR",
                "error_ja": f"予期しないエラー: {str(e)}",
                "error_en": f"Unexpected error: {str(e)}"
            }
    
    def _blocking_read_zairyu(self, card_number: str) -> Dict[str, Any]:
        """
        Blocking implementation of Zairyu card reading.
        This runs in a thread pool to avoid blocking the event loop.
        All blocking operations (including card presence check) happen here.
        """
        reader = self.get_reader()
        if not reader:
            return {
                "success": False,
                "error": "NO_READER",
                "error_ja": "カードリーダーが接続されていません",
                "error_en": "No card reader connected"
            }
        
        # Check if card is present (this is blocking, so we do it here in the thread)
        if not self.check_card_present():
            return {
                "success": False,
                "error": "NO_CARD",
                "error_ja": "カードが検出されません",
                "error_en": "No card detected on reader"
            }
        
        conn = None
        try:
            conn = reader.createConnection()
            conn.connect()
            
            zairyu_reader = ZairyuCardReader(conn, ocr_provider=self.ocr_provider)
            
            logger.info(f"API: Reading Zairyu card with number {card_number[:4]}****{card_number[-2:]}")
            
            result = zairyu_reader.read_all_data(card_number)
            
            if "error" in result:
                error_msg = result.get("error", "")
                
                if "Mutual authentication failed" in error_msg:
                    return {
                        "success": False,
                        "error": "AUTH_FAILED",
                        "error_ja": "カードとの相互認証に失敗しました",
                        "error_en": "Failed mutual authentication with card",
                        "hint": result.get("hint", "")
                    }
                elif "Card number verification failed" in error_msg:
                    return {
                        "success": False,
                        "error": "WRONG_CARD_NUMBER",
                        "error_ja": "在留カード番号が一致しません",
                        "error_en": "Card number does not match"
                    }
                elif "Cannot select MF" in error_msg:
                    return {
                        "success": False,
                        "error": "NOT_ZAIRYU_CARD",
                        "error_ja": "在留カードではありません",
                        "error_en": "This is not a Residence Card"
                    }
                else:
                    return {
                        "success": False,
                        "error": "READ_ERROR",
                        "error_ja": f"読み取りエラー: {error_msg}",
                        "error_en": f"Read error: {error_msg}"
                    }
            
            response = {
                "success": True,
                "authenticated": result.get("authenticated", False),
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader)
            }
            response.update(result)
            
            logger.info(f"API: Successfully read Zairyu card")
            return response
            
        except NoCardException:
            return {
                "success": False,
                "error": "CARD_REMOVED",
                "error_ja": "カードが取り除かれました",
                "error_en": "Card was removed during reading"
            }
        except CardConnectionException as e:
            return {
                "success": False,
                "error": "CONNECTION_ERROR",
                "error_ja": "カードとの通信エラー",
                "error_en": "Communication error with card",
                "detail": str(e)
            }
        except Exception as e:
            logger.error(f"Blocking read_zairyu error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": "UNKNOWN_ERROR",
                "error_ja": f"予期しないエラー: {str(e)}",
                "error_en": f"Unexpected error: {str(e)}"
            }
        finally:
            # CRITICAL: Always disconnect to release the reader
            if conn:
                try:
                    conn.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting card: {e}")
    
    async def api_read_zairyu(self, card_number: str) -> Dict[str, Any]:
        """API endpoint for reading Zairyu (Residence) Card."""
        if not SMARTCARD_AVAILABLE:
            return {
                "success": False,
                "error": "NO_SMARTCARD_LIB",
                "error_ja": "スマートカードライブラリが利用できません",
                "error_en": "Smart card library not available"
            }
        
        # Quick validation (non-blocking)
        if not card_number:
            return {
                "success": False,
                "error": "NO_CARD_NUMBER",
                "error_ja": "在留カード番号が入力されていません",
                "error_en": "Card number is required"
            }
        
        if len(card_number) != 12:
            return {
                "success": False,
                "error": "INVALID_CARD_NUMBER_FORMAT",
                "error_ja": "在留カード番号は12桁である必要があります",
                "error_en": "Card number must be 12 characters",
                "hint": "Example: AB12345678CD"
            }
        
        # Check OCR cache first (instant if same card was read recently)
        cached_result = self.ocr_cache.get(card_number)
        if cached_result:
            logger.info(f"Using cached OCR result for card {card_number[:4]}****")
            # Update timestamp for cached result
            cached_result["timestamp"] = datetime.now().isoformat()
            cached_result["from_cache"] = True
            return cached_result
        
        try:
            # Run ALL blocking operations in thread pool (including card presence check)
            # This prevents blocking the event loop during polling
            result = await self.run_blocking(
                self._blocking_read_zairyu, 
                card_number,
                timeout=90.0  # 90 second timeout for OCR processing
            )
            
            # Cache successful results with OCR data
            if result.get("success") and result.get("authenticated"):
                self.ocr_cache.set(card_number, result)
                logger.info(f"Cached OCR result for card {card_number[:4]}****")
            
            return result
        except asyncio.TimeoutError:
            logger.error("Zairyu card read timed out")
            return {
                "success": False,
                "error": "TIMEOUT",
                "error_ja": "カード読み取りがタイムアウトしました",
                "error_en": "Card reading timed out"
            }
        except Exception as e:
            logger.error(f"API read_zairyu error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": "UNKNOWN_ERROR",
                "error_ja": f"予期しないエラー: {str(e)}",
                "error_en": f"Unexpected error: {str(e)}"
            }
    
    async def api_test_ocr(self, image_base64: str, filename: str = "uploaded") -> Dict[str, Any]:
        """API endpoint for testing OCR on an uploaded image."""
        logger.info(f"API: Testing OCR on uploaded image: {filename}")
        
        if not self.ocr_provider:
            return {
                "success": False,
                "error": "OCR_NOT_AVAILABLE",
                "error_ja": "OCRプロバイダーが設定されていません",
                "error_en": "No OCR provider configured"
            }
        
        if not image_base64:
            return {
                "success": False,
                "error": "NO_IMAGE",
                "error_ja": "画像データがありません",
                "error_en": "No image data provided"
            }
        
        try:
            import base64
            image_data = base64.b64decode(image_base64)
            logger.info(f"Decoded image: {len(image_data)} bytes")
            
            # Run OCR
            ocr_result = self.ocr_provider.process_image(image_data)
            
            if not ocr_result.success:
                return {
                    "success": False,
                    "error": "OCR_ERROR",
                    "error_ja": f"OCRエラー: {ocr_result.error}",
                    "error_en": f"OCR error: {ocr_result.error}"
                }
            
            # Parse structured fields
            parsed_fields = {}
            if OCR_AVAILABLE and ZairyuCardParser:
                parser = ZairyuCardParser()
                parsed_fields = parser.parse(ocr_result)
            
            logger.info(f"OCR extracted {len(ocr_result.text_blocks)} text regions")
            logger.info(f"Parsed fields: {list(parsed_fields.keys())}")
            
            return {
                "success": True,
                "filename": filename,
                "image_size": len(image_data),
                "ocr_result": {
                    "ocr_success": True,
                    "raw_text": ocr_result.raw_text,
                    "parsed_fields": parsed_fields
                }
            }
            
        except Exception as e:
            logger.error(f"OCR test error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": "OCR_ERROR",
                "error_ja": f"OCRエラー: {str(e)}",
                "error_en": f"OCR error: {str(e)}"
            }
    
    async def wait_for_card(self, card_type: str, params: Dict, timeout: int = 30) -> Dict[str, Any]:
        """Wait for card and read it"""
        self.state = BridgeState.WAITING_FOR_CARD
        
        await self.broadcast({
            "type": "status",
            "status": "waiting_for_card",
            "message": "Đặt thẻ lên đầu đọc / Place card on reader"
        })
        
        start = asyncio.get_event_loop().time()
        
        while True:
            if asyncio.get_event_loop().time() - start > timeout:
                self.state = BridgeState.IDLE
                return {"success": False, "error": "Timeout"}
            
            if self.check_card_present():
                self.state = BridgeState.READING
                await self.broadcast({
                    "type": "status",
                    "status": "reading",
                    "message": "Đang đọc thẻ / Reading card..."
                })
                
                await asyncio.sleep(0.3)
                
                if card_type == "cccd":
                    result = self.read_cccd_card(
                        params.get('card_number', ''),
                        params.get('birth_date', ''),
                        params.get('expiry_date', '')
                    )
                elif card_type == "zairyu":
                    result = self.read_zairyu_card(params.get('card_number', ''))
                elif card_type == "mynumber":
                    result = self.read_mynumber_card(params.get('pin', ''))
                elif card_type == "suica":
                    result = self.read_suica_card()
                else:
                    result = self.read_generic_card()
                
                self.state = BridgeState.IDLE
                return result
            
            await asyncio.sleep(0.3)
    
    async def handle_message(self, websocket, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")
            
            logger.info(f"Message: {msg_type}")
            
            if msg_type == "start_scan":
                if self.scan_task and not self.scan_task.done():
                    self.scan_task.cancel()
                    try:
                        await self.scan_task
                    except asyncio.CancelledError:
                        pass
                
                card_type = data.get("card_type", "generic")
                timeout = data.get("timeout", 30)
                
                params = {
                    "card_number": data.get("card_number", ""),
                    "birth_date": data.get("birth_date", ""),
                    "expiry_date": data.get("expiry_date", ""),
                    "pin": data.get("pin", "")
                }
                
                async def do_scan():
                    result = await self.wait_for_card(card_type, params, timeout)
                    await websocket.send(json.dumps({
                        "type": "scan_result",
                        **result
                    }))
                
                self.scan_task = asyncio.create_task(do_scan())
                
            elif msg_type == "cancel_scan":
                if self.scan_task and not self.scan_task.done():
                    self.scan_task.cancel()
                self.state = BridgeState.IDLE
                await websocket.send(json.dumps({
                    "type": "status",
                    "status": "cancelled"
                }))
                
            elif msg_type == "read_now":
                card_type = data.get("card_type", "generic")
                params = {
                    "card_number": data.get("card_number", ""),
                    "birth_date": data.get("birth_date", ""),
                    "expiry_date": data.get("expiry_date", ""),
                    "pin": data.get("pin", "")
                }
                
                if card_type == "cccd":
                    result = self.read_cccd_card(
                        params['card_number'],
                        params['birth_date'],
                        params['expiry_date']
                    )
                elif card_type == "zairyu":
                    result = self.read_zairyu_card(params.get('card_number', ''))
                elif card_type == "mynumber":
                    result = self.read_mynumber_card(params.get('pin', ''))
                elif card_type == "suica":
                    result = self.read_suica_card()
                else:
                    result = self.read_generic_card()
                
                await websocket.send(json.dumps({
                    "type": "scan_result",
                    **result
                }))
                
            elif msg_type == "read_mynumber":
                result = await self.api_read_mynumber(data.get("pin", ""))
                await websocket.send(json.dumps({
                    "type": "mynumber_result",
                    **result
                }))
            
            elif msg_type == "read_zairyu":
                result = await self.api_read_zairyu(data.get("card_number", ""))
                await websocket.send(json.dumps({
                    "type": "zairyu_result",
                    **result
                }))
            
            elif msg_type == "test_ocr":
                result = await self.api_test_ocr(
                    data.get("image_base64", ""),
                    data.get("filename", "uploaded_image")
                )
                await websocket.send(json.dumps({
                    "type": "ocr_result",
                    **result
                }))
            
            elif msg_type == "detect_card_type":
                # Quick card type detection without deep reading
                result = await self.run_blocking(self.detect_card_type, timeout=10.0)
                await websocket.send(json.dumps({
                    "type": "card_type_result",
                    **result
                }))
            
            elif msg_type == "get_status":
                reader = self.get_reader()
                await websocket.send(json.dumps({
                    "type": "status_response",
                    "state": self.state.value,
                    "reader_available": reader is not None,
                    "reader_name": str(reader) if reader else None,
                    "card_present": self.check_card_present(),
                    "ocr_available": self.ocr_provider is not None
                }))
                
            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
                
        except json.JSONDecodeError:
            await websocket.send(json.dumps({"type": "error", "error": "Invalid JSON"}))
        except Exception as e:
            logger.error(f"Error: {e}")
            await websocket.send(json.dumps({"type": "error", "error": str(e)}))
    
    async def handler(self, websocket):
        """Handle WebSocket connection"""
        self.connected_clients.add(websocket)
        logger.info(f"Client connected. Total: {len(self.connected_clients)}")
        
        reader = self.get_reader()
        await websocket.send(json.dumps({
            "type": "connected",
            "state": self.state.value,
            "reader_available": reader is not None,
            "reader_name": str(reader) if reader else None,
            "supported_cards": ["generic", "cccd", "zairyu", "mynumber", "suica"],
            "supported_features": ["detect_card_type"],
            "version": self.VERSION,
            "zairyu_auth": "card_number_only",
            "ocr_available": self.ocr_provider is not None
        }))
        
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connected_clients.discard(websocket)
            logger.info(f"Client disconnected. Total: {len(self.connected_clients)}")
