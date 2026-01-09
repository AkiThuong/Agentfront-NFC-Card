"""
NFC Bridge Server - Vietnamese CCCD & Zairyu Card Support
=========================================================
WebSocket server for reading NFC cards from web applications.
Supports:
- Vietnamese CCCD (Căn cước công dân) 
- Japanese Zairyu Card (在留カード)
- Generic NFC cards (UID only)

Port: localhost:3005
"""

import asyncio
import json
import logging
import hashlib
import os
from datetime import datetime
from enum import Enum
from typing import Optional, Set, Dict, Any, List

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed")
    print("Run: pip install websockets")
    exit(1)

# Try to import cryptography for BAC authentication
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
        print("WARNING: pycryptodome not installed - BAC authentication limited")
        print("Install: pip install pycryptodome")

try:
    from smartcard.System import readers
    from smartcard.util import toHexString, toBytes
    from smartcard.Exceptions import NoCardException, CardConnectionException
    SMARTCARD_AVAILABLE = True
except ImportError:
    print("WARNING: pyscard not installed - running in simulation mode")
    print("Install: pip install pyscard --only-binary :all:")
    SMARTCARD_AVAILABLE = False

# Try to import nfcpy for direct FeliCa access (Suica reading)
try:
    import nfc
    from nfc.tag.tt3_sony import FelicaStandard
    NFCPY_AVAILABLE = True
except ImportError:
    NFCPY_AVAILABLE = False
    print("INFO: nfcpy not installed - Suica balance reading limited")
    print("Install: pip install nfcpy")

# Try to import Pillow for JP2 (JPEG 2000) to JPEG conversion
# Zairyu cards store images in JPEG 2000 format which browsers don't support
try:
    from PIL import Image
    import io
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("WARNING: Pillow not installed - JP2 images may not display in browsers")
    print("Install: pip install Pillow")

# Try to import EasyOCR for extracting text from card images
# Zairyu card personal info (name, nationality, etc.) is only in images
try:
    import easyocr
    EASYOCR_AVAILABLE = True
    # Initialize OCR reader (lazy loading - created on first use)
    _ocr_reader = None
except ImportError:
    EASYOCR_AVAILABLE = False
    _ocr_reader = None
    print("INFO: EasyOCR not installed - card text extraction disabled")
    print("Install: pip install easyocr")

import re
import numpy as np

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


# =============================================================================
# APDU Commands
# =============================================================================

class APDU:
    """Common APDU commands for NFC cards"""
    
    # Basic commands
    GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
    
    # ICAO 9303 (e-Passport / CCCD) commands
    SELECT_MRTD_APP = [0x00, 0xA4, 0x04, 0x0C, 0x07, 0xA0, 0x00, 0x00, 0x02, 0x47, 0x10, 0x01]
    GET_CHALLENGE = [0x00, 0x84, 0x00, 0x00, 0x08]
    
    # File IDs for ICAO 9303
    EF_COM = [0x01, 0x1E]      # Common data
    EF_DG1 = [0x01, 0x01]      # MRZ data
    EF_DG2 = [0x01, 0x02]      # Photo
    EF_DG11 = [0x01, 0x0B]     # Additional personal details
    EF_DG12 = [0x01, 0x0C]     # Additional document details
    EF_SOD = [0x01, 0x1D]      # Security Object
    
    @staticmethod
    def select_file(file_id: List[int]) -> List[int]:
        """Create SELECT FILE command"""
        return [0x00, 0xA4, 0x02, 0x0C, len(file_id)] + file_id
    
    @staticmethod
    def read_binary(offset: int, length: int) -> List[int]:
        """Create READ BINARY command"""
        p1 = (offset >> 8) & 0xFF
        p2 = offset & 0xFF
        return [0x00, 0xB0, p1, p2, length]


# =============================================================================
# BAC (Basic Access Control) Implementation
# =============================================================================

class BACAuthentication:
    """
    Basic Access Control for ICAO 9303 documents (e-Passport, CCCD)
    Uses document number, date of birth, and expiry date to derive keys.
    """
    
    @staticmethod
    def calculate_check_digit(data: str) -> str:
        """Calculate check digit for MRZ data"""
        weights = [7, 3, 1]
        values = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<"
        total = 0
        for i, char in enumerate(data):
            value = values.index(char.upper()) if char.upper() in values else 0
            total += value * weights[i % 3]
        return str(total % 10)
    
    @staticmethod
    def build_mrz_info(doc_number: str, birth_date: str, expiry_date: str) -> bytes:
        """
        Build MRZ information for key derivation.
        
        Args:
            doc_number: Document number (CCCD: 12 digits, use first 9)
            birth_date: Date of birth in YYMMDD format
            expiry_date: Expiry date in YYMMDD format
        """
        # Use first 9 chars of document number, pad with <
        doc_num_mrz = doc_number[:9].ljust(9, '<')
        
        # Calculate check digits
        doc_check = BACAuthentication.calculate_check_digit(doc_num_mrz)
        birth_check = BACAuthentication.calculate_check_digit(birth_date)
        expiry_check = BACAuthentication.calculate_check_digit(expiry_date)
        
        # MRZ info: doc_number + check + birth_date + check + expiry_date + check
        mrz_info = f"{doc_num_mrz}{doc_check}{birth_date}{birth_check}{expiry_date}{expiry_check}"
        return mrz_info.encode('utf-8')
    
    @staticmethod
    def compute_key(key_seed: bytes, key_type: str) -> bytes:
        """Compute 3DES key from key seed"""
        if key_type == "ENC":
            c = bytes([0x00, 0x00, 0x00, 0x01])
        else:  # MAC
            c = bytes([0x00, 0x00, 0x00, 0x02])
        
        d = key_seed + c
        h = hashlib.sha1(d).digest()
        
        # Take first 16 bytes and adjust parity
        key = bytearray(h[:16])
        for i in range(16):
            b = key[i]
            parity = bin(b).count('1') % 2
            if parity == 0:
                key[i] ^= 1
        
        return bytes(key)
    
    @staticmethod
    def derive_keys(doc_number: str, birth_date: str, expiry_date: str) -> tuple:
        """
        Derive encryption and MAC keys from MRZ data.
        Returns (k_enc, k_mac)
        """
        mrz_info = BACAuthentication.build_mrz_info(doc_number, birth_date, expiry_date)
        
        # SHA-1 hash of MRZ info
        key_seed = hashlib.sha1(mrz_info).digest()[:16]
        
        k_enc = BACAuthentication.compute_key(key_seed, "ENC")
        k_mac = BACAuthentication.compute_key(key_seed, "MAC")
        
        return k_enc, k_mac
    
    @staticmethod
    def pad_data(data: bytes) -> bytes:
        """Apply ISO 9797-1 padding (method 2)"""
        padded = data + bytes([0x80])
        while len(padded) % 8 != 0:
            padded += bytes([0x00])
        return padded
    
    @staticmethod
    def unpad_data(data: bytes) -> bytes:
        """Remove ISO 9797-1 padding"""
        i = len(data) - 1
        while i >= 0 and data[i] == 0x00:
            i -= 1
        if i >= 0 and data[i] == 0x80:
            return data[:i]
        return data
    
    @staticmethod
    def compute_mac(key: bytes, data: bytes) -> bytes:
        """Compute retail MAC (ISO 9797-1 MAC Algorithm 3)"""
        if not CRYPTO_AVAILABLE:
            return bytes(8)
        
        padded = BACAuthentication.pad_data(data)
        
        # Split key
        ka = key[:8]
        kb = key[8:16]
        
        # Initial vector
        h = bytes(8)
        
        # Process all blocks with single DES using ka
        cipher_a = DES.new(ka, DES.MODE_ECB)
        for i in range(0, len(padded), 8):
            block = padded[i:i+8]
            xored = bytes(a ^ b for a, b in zip(h, block))
            h = cipher_a.encrypt(xored)
        
        # Final block: decrypt with kb, encrypt with ka
        cipher_b = DES.new(kb, DES.MODE_ECB)
        h = cipher_b.decrypt(h)
        h = cipher_a.encrypt(h)
        
        return h
    
    @staticmethod
    def encrypt_data(key: bytes, data: bytes) -> bytes:
        """Encrypt data with 3DES in CBC mode"""
        if not CRYPTO_AVAILABLE:
            return data
        
        iv = bytes(8)
        cipher = DES3.new(key, DES3.MODE_CBC, iv)
        padded = BACAuthentication.pad_data(data)
        return cipher.encrypt(padded)
    
    @staticmethod
    def decrypt_data(key: bytes, data: bytes) -> bytes:
        """Decrypt data with 3DES in CBC mode"""
        if not CRYPTO_AVAILABLE:
            return data
        
        iv = bytes(8)
        cipher = DES3.new(key, DES3.MODE_CBC, iv)
        decrypted = cipher.decrypt(data)
        return BACAuthentication.unpad_data(decrypted)


# =============================================================================
# CCCD Card Reader
# =============================================================================

class CCCDReader:
    """Vietnamese CCCD (Căn cước công dân) card reader"""
    
    def __init__(self, connection):
        self.connection = connection
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        """Send APDU command and return response"""
        data, sw1, sw2 = self.connection.transmit(apdu)
        return data, sw1, sw2
    
    def select_mrtd_application(self) -> bool:
        """Select the MRTD application"""
        data, sw1, sw2 = self.send_apdu(APDU.SELECT_MRTD_APP)
        return sw1 == 0x90 and sw2 == 0x00
    
    def get_uid(self) -> Optional[str]:
        """Get card UID"""
        data, sw1, sw2 = self.send_apdu(APDU.GET_UID)
        if sw1 == 0x90:
            return toHexString(data).replace(" ", "")
        return None
    
    def read_file(self, file_id: List[int], max_length: int = 256) -> Optional[bytes]:
        """Read a file from the card"""
        data, sw1, sw2 = self.send_apdu(APDU.select_file(file_id))
        if sw1 != 0x90:
            return None
        
        result = bytearray()
        offset = 0
        
        while offset < max_length:
            read_len = min(256, max_length - offset)
            data, sw1, sw2 = self.send_apdu(APDU.read_binary(offset, read_len))
            
            if sw1 == 0x90:
                result.extend(data)
                if len(data) < read_len:
                    break
                offset += len(data)
            elif sw1 == 0x6C:
                data, sw1, sw2 = self.send_apdu(APDU.read_binary(offset, sw2))
                if sw1 == 0x90:
                    result.extend(data)
                break
            else:
                break
        
        return bytes(result) if result else None
    
    def read_basic_info(self) -> Dict[str, Any]:
        """Read basic card information without authentication"""
        info = {}
        
        uid = self.get_uid()
        if uid:
            info['uid'] = uid
        
        if self.select_mrtd_application():
            info['app_selected'] = True
            info['card_type'] = 'ICAO 9303 (CCCD/ePassport)'
        else:
            info['app_selected'] = False
            info['card_type'] = 'Unknown or protected'
        
        return info


# =============================================================================
# My Number Card (マイナンバーカード) - Japan JPKI
# =============================================================================

class MyNumberCardReader:
    """
    Japanese My Number Card (マイナンバーカード) reader.
    Uses JPKI (Japanese Public Key Infrastructure).
    Supports:
    - Reading certificates (no PIN required)
    - Reading 個人番号 (My Number) - requires 4-digit profile PIN
    - Reading 基本4情報 (name, address, birthdate, gender) - requires 4-digit profile PIN
    """
    
    # JPKI Application IDs
    AID_JPKI_AP = [0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x01]  # 公的個人認証AP
    AID_CARD_INFO = [0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x02]
    AID_PROFILE_AP = [0xD3, 0x92, 0x10, 0x00, 0x31, 0x00, 0x01, 0x01, 0x04, 0x08]  # 券面入力補助AP
    AID_JPKI_SIGN = [0xD3, 0x92, 0x10, 0x00, 0x31, 0x00, 0x01, 0x01, 0x01, 0x00]
    AID_MYNUMBER = [0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x03]
    
    # EF IDs for Profile AP
    EF_PROFILE_PIN = [0x00, 0x11]   # 券面入力補助用PIN
    EF_MY_NUMBER = [0x00, 0x01]     # マイナンバー
    EF_BASIC_4_INFO = [0x00, 0x02]  # 基本4情報
    
    # Manifest positions for Basic 4 Info parsing (corrected offsets)
    # These are byte positions in the header that contain pointers to each segment
    NAME_SEGMENT_PTR = 7
    ADDRESS_SEGMENT_PTR = 9
    BIRTHDATE_SEGMENT_PTR = 11
    GENDER_SEGMENT_PTR = 13
    
    def __init__(self, connection):
        self.connection = connection
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        data, sw1, sw2 = self.connection.transmit(apdu)
        logger.debug(f"APDU: {toHexString(apdu)} -> SW={sw1:02X}{sw2:02X}")
        return data, sw1, sw2
    
    def select_application(self, aid: List[int]) -> bool:
        select_cmd = [0x00, 0xA4, 0x04, 0x0C, len(aid)] + aid
        data, sw1, sw2 = self.send_apdu(select_cmd)
        return sw1 == 0x90
    
    def select_ef(self, ef_id: List[int]) -> bool:
        select_cmd = [0x00, 0xA4, 0x02, 0x0C, len(ef_id)] + ef_id
        data, sw1, sw2 = self.send_apdu(select_cmd)
        return sw1 == 0x90 or sw1 == 0x61
    
    def read_binary(self, length: int = 0) -> Optional[bytes]:
        read_cmd = [0x00, 0xB0, 0x00, 0x00, length if length > 0 else 0x00]
        data, sw1, sw2 = self.send_apdu(read_cmd)
        
        if sw1 == 0x90:
            return bytes(data)
        elif sw1 == 0x6C:
            read_cmd = [0x00, 0xB0, 0x00, 0x00, sw2]
            data, sw1, sw2 = self.send_apdu(read_cmd)
            if sw1 == 0x90:
                return bytes(data)
        return None
    
    def verify_pin(self, pin: str) -> tuple:
        """Verify PIN. Returns (success, remaining_tries)"""
        pin_bytes = [ord(c) for c in pin]
        
        verify_cmd = [0x00, 0x20, 0x00, 0x80, len(pin_bytes)] + pin_bytes
        data, sw1, sw2 = self.send_apdu(verify_cmd)
        
        if sw1 == 0x90:
            return True, -1
        elif sw1 == 0x63 and (sw2 & 0xC0) == 0xC0:
            return False, sw2 & 0x0F
        elif sw1 == 0x69 and sw2 == 0x84:
            return False, 0  # Locked
        return False, -1
    
    def get_remaining_tries(self) -> tuple:
        """
        Get remaining PIN tries without consuming a try.
        Returns (remaining_tries, status_message)
        -1 means unknown/couldn't determine
        """
        # Send VERIFY command without data to check remaining tries
        verify_cmd = [0x00, 0x20, 0x00, 0x80]
        data, sw1, sw2 = self.send_apdu(verify_cmd)
        
        if sw1 == 0x63 and (sw2 & 0xC0) == 0xC0:
            # 63 Cx = x tries remaining
            return sw2 & 0x0F, "OK"
        elif sw1 == 0x69 and sw2 == 0x84:
            # Card is locked
            return 0, "LOCKED"
        elif sw1 == 0x69 and sw2 == 0x82:
            # Security status not satisfied (need to select file first)
            return -1, "Need to select EF first"
        elif sw1 == 0x69 and sw2 == 0x85:
            # Conditions not satisfied
            return -1, "Conditions not satisfied"
        elif sw1 == 0x6A and sw2 == 0x88:
            # Referenced data not found
            return -1, "PIN not set"
        elif sw1 == 0x90:
            # Already authenticated
            return -1, "Already authenticated"
        else:
            return -1, f"Unknown status: {sw1:02X}{sw2:02X}"
    
    def read_binary_long(self, max_length: int = 4096) -> Optional[bytes]:
        """Read binary data with extended length support"""
        result = bytearray()
        offset = 0
        
        while offset < max_length:
            # Read in chunks of 256 bytes max
            read_len = min(256, max_length - offset)
            p1 = (offset >> 8) & 0x7F  # High byte of offset (mask to 7 bits for short EF)
            p2 = offset & 0xFF         # Low byte of offset
            read_cmd = [0x00, 0xB0, p1, p2, read_len if read_len < 256 else 0x00]
            data, sw1, sw2 = self.send_apdu(read_cmd)
            
            if sw1 == 0x90:
                result.extend(data)
                if len(data) < read_len:
                    break  # End of file
                offset += len(data)
            elif sw1 == 0x6C:
                # Wrong length, retry with correct length
                read_cmd = [0x00, 0xB0, p1, p2, sw2]
                data, sw1, sw2 = self.send_apdu(read_cmd)
                if sw1 == 0x90:
                    result.extend(data)
                break
            elif sw1 == 0x6B:
                # Wrong parameters (offset beyond file) - end of file
                break
            else:
                break
        
        return bytes(result) if result else None
    
    def parse_certificate_info(self, cert_data: bytes) -> Dict[str, Any]:
        """Parse basic info from X.509 certificate DER data"""
        info = {}
        try:
            # Find common name in subject (simplified parsing)
            # Look for OID 2.5.4.3 (CN) = 55 04 03
            hex_data = cert_data.hex()
            cn_oid = "550403"
            cn_pos = hex_data.find(cn_oid)
            if cn_pos > 0:
                # Skip OID and length bytes to get value
                pos = cn_pos + 6  # Skip OID
                # Next byte is type (usually 0C for UTF8 or 13 for PrintableString)
                type_byte = int(hex_data[pos:pos+2], 16)
                pos += 2
                # Get length
                length = int(hex_data[pos:pos+2], 16)
                pos += 2
                # Get value
                if length < 128:
                    cn_bytes = bytes.fromhex(hex_data[pos:pos+length*2])
                    info["certificate_cn"] = cn_bytes.decode('utf-8', errors='replace')
            
            # Certificate validity dates are harder to parse without a proper ASN.1 library
            info["certificate_size"] = len(cert_data)
            info["certificate_available"] = True
            
        except Exception as e:
            info["parse_error"] = str(e)
        
        return info
    
    def _decode_japanese_text(self, data: bytes) -> str:
        """Decode Japanese text trying multiple encodings"""
        for encoding in ["utf-8", "cp932", "shift-jis", "euc-jp"]:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        # Fallback: decode with errors replaced
        return data.decode("cp932", errors="replace")
    
    def _parse_attr(self, data: List[int], segment_start: int) -> str:
        """
        Parse an attribute from the basic 4 info data.
        
        TLV format:
        - pos 0: 0xDF (tag byte 1)
        - pos 1: 0x2X (tag byte 2, X = 2-5 for name/address/birthdate/gender)
        - pos 2: length
        - pos 3+: attribute data
        """
        try:
            attr_length = data[segment_start + 2]
            attr_start = segment_start + 3
            attr_data = data[attr_start:attr_start + attr_length]
            return self._decode_japanese_text(bytes(attr_data))
        except Exception as e:
            logger.error(f"Error parsing attribute at {segment_start}: {e}")
            return ""
    
    def read_my_number(self, profile_pin: str) -> Dict[str, Any]:
        """
        Read マイナンバー (個人番号) from the card.
        
        Args:
            profile_pin: 4-digit 券面入力補助用PIN
            
        Returns:
            Dict with my_number or error
        """
        result = {}
        
        # Select Profile AP (券面入力補助AP)
        if not self.select_application(self.AID_PROFILE_AP):
            result["error"] = "Cannot select Profile AP"
            return result
        
        # Select Profile PIN file
        if not self.select_ef(self.EF_PROFILE_PIN):
            result["error"] = "Cannot select Profile PIN file"
            return result
        
        # Verify PIN
        success, remaining = self.verify_pin(profile_pin)
        if not success:
            result["error"] = f"PIN verification failed"
            result["remaining_tries"] = remaining
            if remaining == 0:
                result["warning"] = "⚠️ カードがロックされています"
            return result
        
        # Select My Number file
        if not self.select_ef(self.EF_MY_NUMBER):
            result["error"] = "Cannot select My Number file"
            return result
        
        # Read My Number data (bytes 3-14 contain the 12-digit number)
        data = self.read_binary(16)
        if data:
            my_number = ''.join([chr(b) for b in data[3:15]])
            result["my_number"] = my_number
            logger.info(f"Read My Number: {my_number[:4]}****{my_number[-4:]}")
        else:
            result["error"] = "Cannot read My Number data"
        
        return result
    
    def read_basic_4_info(self, profile_pin: str) -> Dict[str, Any]:
        """
        Read 基本4情報 (name, address, birthdate, gender) from the card.
        
        Args:
            profile_pin: 4-digit 券面入力補助用PIN
            
        Returns:
            Dict with name, address, birthdate, gender or error
        """
        result = {}
        
        # Select Profile AP (券面入力補助AP)
        if not self.select_application(self.AID_PROFILE_AP):
            result["error"] = "Cannot select Profile AP"
            return result
        
        # Select Profile PIN file
        if not self.select_ef(self.EF_PROFILE_PIN):
            result["error"] = "Cannot select Profile PIN file"
            return result
        
        # Verify PIN
        success, remaining = self.verify_pin(profile_pin)
        if not success:
            result["error"] = f"PIN verification failed"
            result["remaining_tries"] = remaining
            if remaining == 0:
                result["warning"] = "⚠️ カードがロックされています"
            return result
        
        # Select Basic 4 Info file
        if not self.select_ef(self.EF_BASIC_4_INFO):
            result["error"] = "Cannot select Basic 4 Info file"
            return result
        
        # Read 256 bytes of data
        data = self.read_binary(0)  # 0 = max available
        if not data:
            result["error"] = "Cannot read Basic 4 Info data"
            return result
        
        data_list = list(data)
        
        try:
            # Parse each attribute using the pointer values at the manifest positions
            name_ptr = data_list[self.NAME_SEGMENT_PTR]
            address_ptr = data_list[self.ADDRESS_SEGMENT_PTR]
            birthdate_ptr = data_list[self.BIRTHDATE_SEGMENT_PTR]
            gender_ptr = data_list[self.GENDER_SEGMENT_PTR]
            
            result["name"] = self._parse_attr(data_list, name_ptr)
            result["address"] = self._parse_attr(data_list, address_ptr)
            result["birthdate"] = self._parse_attr(data_list, birthdate_ptr)
            
            # Gender is a single digit: 1=男性, 2=女性, 3=その他
            gender_raw = self._parse_attr(data_list, gender_ptr)
            gender_map = {"1": "男性", "2": "女性", "3": "その他"}
            result["gender"] = gender_map.get(gender_raw.strip(), gender_raw)
            result["gender_code"] = gender_raw.strip()
            
            logger.info(f"Read Basic 4 Info: name={result.get('name', 'N/A')}")
            
        except Exception as e:
            logger.error(f"Error parsing Basic 4 Info: {e}")
            result["parse_error"] = str(e)
        
        return result
    
    def read_personal_info(self, profile_pin: str) -> Dict[str, Any]:
        """
        Read both My Number and Basic 4 Info in one call.
        
        Args:
            profile_pin: 4-digit 券面入力補助用PIN
            
        Returns:
            Dict with all personal info
        """
        result = {}
        
        # Read My Number
        my_number_result = self.read_my_number(profile_pin)
        if "error" in my_number_result:
            return my_number_result
        result.update(my_number_result)
        
        # Read Basic 4 Info
        basic_info_result = self.read_basic_4_info(profile_pin)
        if "error" in basic_info_result:
            result["basic_info_error"] = basic_info_result.get("error")
        else:
            result.update(basic_info_result)
        
        return result
    
    def read_basic_info(self) -> Dict[str, Any]:
        """Read card info without PIN"""
        info = {}
        
        # Try Card Info AP (券面情報AP)
        if self.select_application(self.AID_CARD_INFO):
            info["card_info_available"] = True
            
            # EF 00 06: Card serial number
            if self.select_ef([0x00, 0x06]):
                data = self.read_binary(20)
                if data:
                    info["card_serial"] = toHexString(list(data))
            
            # EF 00 11: Card expiry date (YYYYMMDD format)
            if self.select_ef([0x00, 0x11]):
                data = self.read_binary(8)
                if data:
                    try:
                        expiry_str = data.decode('ascii').strip()
                        info["card_expiry"] = expiry_str
                    except:
                        info["card_expiry_raw"] = toHexString(list(data))
        
        # Try JPKI Auth AP (公的個人認証 - 利用者証明用)
        if self.select_application(self.AID_JPKI_AP):
            info["jpki_auth_available"] = True
            
            # Select PIN file for auth (EF 00 18)
            if self.select_ef([0x00, 0x18]):
                # Get remaining PIN tries (doesn't consume a try)
                remaining, status = self.get_remaining_tries()
                info["auth_pin_remaining_tries"] = remaining
                info["auth_pin_status"] = status
                if remaining == 0:
                    info["auth_pin_warning"] = "⚠️ LOCKED - Visit city hall to reset"
                elif remaining > 0 and remaining <= 2:
                    info["auth_pin_warning"] = f"⚠️ Only {remaining} tries left!"
            
            # EF 00 0A: User Authentication Certificate (公開鍵証明書)
            # This certificate CAN be read without PIN!
            if self.select_ef([0x00, 0x0A]):
                cert_data = self.read_binary_long(2048)
                if cert_data and len(cert_data) > 0:
                    cert_info = self.parse_certificate_info(cert_data)
                    info.update(cert_info)
                    # Store first 32 bytes as preview (don't send entire cert)
                    info["auth_cert_preview"] = toHexString(list(cert_data[:32]))
            
            # EF 00 0B: CA Certificate (認証局の証明書)
            if self.select_ef([0x00, 0x0B]):
                ca_data = self.read_binary_long(2048)
                if ca_data and len(ca_data) > 0:
                    info["ca_cert_size"] = len(ca_data)
                    info["ca_cert_available"] = True
        
        # Try JPKI Sign AP (公的個人認証 - 署名用) - check if available
        if self.select_application(self.AID_JPKI_SIGN):
            info["jpki_sign_available"] = True
            
            # Select PIN file for sign (EF 00 1B)
            if self.select_ef([0x00, 0x1B]):
                remaining, status = self.get_remaining_tries()
                info["sign_pin_remaining_tries"] = remaining
                info["sign_pin_status"] = status
                if remaining == 0:
                    info["sign_pin_warning"] = "⚠️ LOCKED"
        
        return info


# =============================================================================
# Suica / FeliCa Card Reader (交通系ICカード)
# =============================================================================

class SuicaReader:
    """
    Suica/Pasmo/ICOCA and other FeliCa-based transit IC cards reader.
    Uses PC/SC transparent commands for FeliCa access via Sony PaSoRi.
    """
    
    # FeliCa System Codes
    SYSTEM_CODE_SUICA = [0x00, 0x03]  # Suica/Pasmo/ICOCA etc.
    SYSTEM_CODE_COMMON = [0x88, 0xB4]  # Common area
    
    # Service Codes for Suica (little-endian format)
    # 0x008B = Balance service
    # 0x090F = History service (Read Without Encryption)
    SERVICE_HISTORY = 0x090F  # 履歴
    
    def __init__(self, connection):
        self.connection = connection
        self.idm = None  # Card ID (8 bytes)
        self.pmm = None  # Manufacturing parameters (8 bytes)
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        data, sw1, sw2 = self.connection.transmit(apdu)
        logger.debug(f"APDU: {toHexString(apdu)} -> {toHexString(data)} SW={sw1:02X}{sw2:02X}")
        return data, sw1, sw2
    
    def felica_command(self, cmd_data: List[int]) -> Optional[List[int]]:
        """
        Send FeliCa command via PC/SC transparent command.
        Sony PaSoRi uses: FF 00 00 00 Lc [Length + Command Data]
        
        Note: Many Sony PaSoRi readers do NOT support transparent FeliCa 
        commands through PC/SC - they return 6A81 (function not supported).
        For full FeliCa access, use nfcpy library instead.
        """
        try:
            # Try format 1: Length includes itself
            cmd_with_len = [len(cmd_data) + 1] + cmd_data
            apdu = [0xFF, 0x00, 0x00, 0x00, len(cmd_with_len)] + cmd_with_len
            
            data, sw1, sw2 = self.send_apdu(apdu)
            
            if sw1 == 0x90 and len(data) > 0:
                return list(data)
            
            if sw1 == 0x6A and sw2 == 0x81:
                # Function not supported - this reader doesn't support transparent commands
                logger.warning("PC/SC transparent FeliCa commands not supported by this reader")
                return None
            
            # Try format 2: Direct command without length byte
            apdu2 = [0xFF, 0x00, 0x00, 0x00, len(cmd_data)] + cmd_data
            data, sw1, sw2 = self.send_apdu(apdu2)
            
            if sw1 == 0x90 and len(data) > 0:
                return list(data)
                
        except Exception as e:
            logger.warning(f"FeliCa command failed: {e}")
            
        return None
    
    def felica_polling(self) -> bool:
        """
        Poll for FeliCa card using Polling command (0x00).
        Returns True if card found.
        """
        # Try GET_DATA command first (most compatible with PaSoRi)
        # FF CA 00 00 00 - Get card UID/IDm
        data, sw1, sw2 = self.send_apdu([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if sw1 == 0x90 and len(data) >= 8:
            self.idm = bytes(data[:8])
            logger.info(f"FeliCa IDm: {toHexString(list(self.idm))}")
            return True
        
        # Try FeliCa Polling command
        # Command: 00 [System Code (2)] [Request Code] [Time Slot]
        # System Code 0003 = Suica, 88B4 = Common
        for system_code in [[0x00, 0x03], [0x88, 0xB4], [0xFF, 0xFF]]:
            polling_cmd = [0x00] + system_code + [0x01, 0x0F]
            response = self.felica_command(polling_cmd)
            
            if response and len(response) >= 17:
                # Response: Length + 01 + IDm(8) + PMm(8) + [RD(2)]
                self.idm = bytes(response[1:9])
                self.pmm = bytes(response[9:17])
                logger.info(f"FeliCa IDm: {toHexString(list(self.idm))}")
                return True
        
        return False
    
    def read_blocks(self, service_code: int, block_numbers: List[int]) -> Optional[List[bytes]]:
        """
        Read blocks from FeliCa card using Read Without Encryption (0x06).
        
        Args:
            service_code: 16-bit service code (e.g., 0x090F for history)
            block_numbers: List of block numbers to read (max 15 per command)
        
        Returns:
            List of 16-byte block data, or None if failed
        """
        if not self.idm:
            logger.warning("No IDm available")
            return None
        
        # Limit to 1 block per read for maximum compatibility
        block_numbers = block_numbers[:1]
        num_blocks = len(block_numbers)
        
        # Build block list elements (2-byte format for block numbers < 256)
        block_list = []
        for block_num in block_numbers:
            # Block List Element: [Length/Access Mode] [Block Number]
            # 0x80 = 2-byte format, no access mode bits
            block_list.extend([0x80, block_num & 0xFF])
        
        # Read Without Encryption command (0x06)
        # Format: 06 + IDm(8) + NumServices(1) + ServiceCodeList + NumBlocks(1) + BlockList
        cmd = (
            [0x06] +                           # Command code
            list(self.idm) +                   # IDm (8 bytes)
            [0x01] +                           # Number of services = 1
            [service_code & 0xFF, (service_code >> 8) & 0xFF] +  # Service code (little-endian)
            [num_blocks] +                     # Number of blocks
            block_list                         # Block list elements
        )
        
        logger.info(f"Read cmd for service {service_code:04X}: {toHexString(cmd)}")
        
        response = self.felica_command(cmd)
        
        if not response:
            logger.warning(f"No response for Read Without Encryption")
            return None
        
        logger.info(f"Read response ({len(response)} bytes): {toHexString(response[:min(32, len(response))])}")
        
        # Response format: Length + 07 + IDm(8) + StatusFlag1 + StatusFlag2 + NumBlocks + BlockData
        # Or without length: 07 + IDm(8) + StatusFlag1 + StatusFlag2 + NumBlocks + BlockData
        
        # Check first byte to determine format
        first_byte = response[0]
        
        if first_byte == 0x07:
            # No length byte in response
            offset = 0
        elif first_byte == len(response) or first_byte == len(response) - 1:
            # Length byte present
            offset = 1
        else:
            offset = 0
        
        if len(response) < offset + 12:
            logger.warning(f"Response too short: {len(response)} bytes")
            return None
        
        resp_code = response[offset]
        if resp_code != 0x07:
            logger.warning(f"Unexpected response code: {resp_code:02X} (expected 0x07)")
            return None
        
        status1 = response[offset + 9]
        status2 = response[offset + 10]
        
        if status1 != 0x00:
            logger.warning(f"FeliCa error: Status1={status1:02X} Status2={status2:02X}")
            return None
        
        resp_num_blocks = response[offset + 11]
        logger.info(f"FeliCa read success: {resp_num_blocks} blocks")
        
        # Extract block data (16 bytes each)
        blocks = []
        data_offset = offset + 12
        for i in range(resp_num_blocks):
            if data_offset + 16 <= len(response):
                block_data = bytes(response[data_offset:data_offset + 16])
                blocks.append(block_data)
                logger.info(f"Block {i}: {toHexString(list(block_data))}")
                data_offset += 16
        
        return blocks if blocks else None
    
    def parse_suica_balance(self, block_data: bytes) -> int:
        """Parse balance from Suica block data"""
        if len(block_data) < 12:
            return -1
        # Balance is at bytes 10-11 (little-endian)
        return block_data[11] << 8 | block_data[10]
    
    def parse_suica_history(self, block_data: bytes) -> Dict[str, Any]:
        """Parse history entry from Suica block data"""
        if len(block_data) < 16:
            return {"error": "Invalid data"}
        
        entry = {}
        
        # Byte 0: Terminal type
        terminal_type = block_data[0]
        terminal_names = {
            0x03: "精算機",
            0x05: "バス",
            0x07: "券売機",
            0x08: "精算機",
            0x12: "券売機",
            0x14: "券売機等",
            0x15: "券売機等",
            0x16: "改札機",
            0x17: "券売機",
            0x18: "券売機",
            0x1A: "改札機",
            0x1B: "バス等",
            0x1C: "バス等",
            0x1F: "物販",
            0x46: "VIEW ALTTE",
            0x48: "VIEW ALTTE",
            0xC7: "物販",
            0xC8: "物販",
        }
        entry["terminal"] = terminal_names.get(terminal_type, f"Unknown({terminal_type:02X})")
        
        # Byte 1: Process type
        process_type = block_data[1]
        process_names = {
            0x01: "運賃支払",
            0x02: "チャージ",
            0x03: "物販購入",
            0x04: "精算",
            0x05: "精算 (入場)",
            0x06: "物販取消",
            0x07: "入金精算",
            0x0F: "バス",
            0x11: "バス",
            0x13: "バス/路面等",
            0x14: "オートチャージ",
            0x15: "バス等",
            0x1F: "バスチャージ",
            0x46: "物販現金",
            0x49: "入金",
        }
        entry["process"] = process_names.get(process_type, f"Unknown({process_type:02X})")
        
        # Bytes 4-5: Date (days since 2000/1/1, but format varies)
        date_raw = (block_data[4] << 8) | block_data[5]
        year = ((date_raw >> 9) & 0x7F) + 2000
        month = (date_raw >> 5) & 0x0F
        day = date_raw & 0x1F
        if 1 <= month <= 12 and 1 <= day <= 31:
            entry["date"] = f"{year}/{month:02d}/{day:02d}"
        else:
            entry["date_raw"] = f"{date_raw:04X}"
        
        # Bytes 10-11: Balance after transaction (little-endian)
        balance = (block_data[11] << 8) | block_data[10]
        entry["balance"] = balance
        
        return entry
    
    def read_card(self) -> Dict[str, Any]:
        """Read Suica card data"""
        card_data = {}
        
        # Try polling
        if not self.felica_polling():
            return {"error": "FeliCa polling failed"}
        
        if self.idm:
            card_data["idm"] = toHexString(list(self.idm)).replace(" ", "")
            # Decode IDm - manufacturer code is bytes 0-1
            manufacturer = (self.idm[0] << 8) | self.idm[1]
            card_data["manufacturer"] = f"0x{manufacturer:04X}"
        
        if self.pmm:
            card_data["pmm"] = toHexString(list(self.pmm)).replace(" ", "")
        
        card_data["card_type"] = "Suica/Pasmo/ICOCA (交通系IC)"
        
        # Try to read balance using FeliCa Read Without Encryption
        # Note: Sony PaSoRi PC/SC driver often returns 6A81 (not supported)
        history_blocks = self.read_blocks(self.SERVICE_HISTORY, [0])
        
        if history_blocks and len(history_blocks) > 0:
            # Successfully read data!
            first_block = history_blocks[0]
            card_data["block0_raw"] = toHexString(list(first_block))
            
            if len(first_block) >= 12:
                balance = (first_block[11] << 8) | first_block[10]
                card_data["balance"] = f"¥{balance:,}"
                card_data["balance_raw"] = balance
            
            # Parse history entry
            entry = self.parse_suica_history(first_block)
            card_data["last_transaction"] = entry
        else:
            # PC/SC transparent commands not supported - need nfcpy for full access
            card_data["balance"] = "🔒 暗号化エリア"
            card_data["limitation"] = "Suicaの残高・履歴は暗号化されており、特殊な認証が必要です"
            card_data["reason"] = "Sony PaSoRiのPC/SCドライバはFeliCa暗号化エリアの読取に非対応"
            card_data["solutions"] = [
                "1. スマホアプリ「Suica」で確認",
                "2. suica-viewerを使用 (nfcpy + リモート認証)",
                "3. 駅の券売機で残高確認"
            ]
        
        return card_data


# =============================================================================
# nfcpy-based Suica Reader (Full Access with Remote Auth)
# =============================================================================

class NfcpySuicaReader:
    """
    Full Suica reader using nfcpy for direct USB access.
    Uses remote authentication server for encrypted area access.
    """
    
    SYSTEM_CODE = 0x0003
    AUTH_SERVER_URL = "https://felica-auth.nyaa.ws"
    
    # Service node IDs for authentication
    AREA_NODE_IDS = (0x0000, 0x0040, 0x0800, 0x0FC0, 0x1000)
    SERVICE_NODE_IDS = (0x0048, 0x0088, 0x0810, 0x08C8, 0x090C, 0x1008, 0x1048, 0x108C, 0x10C8)
    
    # Card type labels
    CARD_TYPE_LABELS = {
        0: "せたまる/IruCa",
        2: "Suica/PiTaPa/TOICA/PASMO",
        3: "ICOCA",
    }
    
    # Equipment types
    EQUIPMENT_TYPES = {
        0x00: "未定義", 0x03: "のりこし精算機", 0x05: "バス車載機",
        0x07: "カード発売機", 0x08: "自動券売機", 0x16: "自動改札機",
        0x17: "簡易改札機", 0x1A: "有人改札", 0x46: "VIEW ALTTE",
        0xC7: "物販端末", 0xC8: "物販端末",
    }
    
    # Transaction types
    TRANSACTION_TYPES = {
        0x01: "改札出場", 0x02: "チャージ", 0x03: "きっぷ購入",
        0x04: "磁気券精算", 0x05: "乗越精算", 0x07: "新規",
        0x0F: "バス", 0x14: "オートチャージ", 0x46: "物販",
    }
    
    def __init__(self):
        self.clf = None
        self.tag = None
        self.session_id = None
        self.authenticated = False
        self.http_timeout = 10.0
    
    @staticmethod
    def is_available() -> bool:
        """Check if nfcpy is available"""
        return NFCPY_AVAILABLE
    
    def _http_post(self, path: str, payload: dict) -> dict:
        """Send HTTP POST request to auth server"""
        import http.client
        import urllib.parse
        
        parsed = urllib.parse.urlsplit(self.AUTH_SERVER_URL)
        
        if parsed.scheme == "https":
            conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=self.http_timeout)
        else:
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=self.http_timeout)
        
        try:
            headers = {"Content-Type": "application/json"}
            body = json.dumps(payload).encode("utf-8")
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            
            if response.status >= 400:
                raise RuntimeError(f"Server error: {response.status} {response.reason}")
            
            return json.loads(data.decode("utf-8"))
        finally:
            conn.close()
    
    def _mutual_authentication(self, tag) -> dict:
        """Perform mutual authentication with remote server"""
        idm = tag.idm
        pmm = tag.pmm
        
        # Initial request
        request = {
            "session_id": self.session_id,
            "idm": idm.hex(),
            "pmm": pmm.hex(),
            "system_code": self.SYSTEM_CODE,
            "areas": list(self.AREA_NODE_IDS),
            "services": list(self.SERVICE_NODE_IDS),
        }
        
        response = self._http_post("/mutual-authentication", request)
        self.session_id = response.get("session_id", self.session_id)
        
        # Authentication loop
        while True:
            step = response.get("step")
            
            if step in ("auth1", "auth2"):
                # Get command from server and send to card
                command = response.get("command", {})
                frame = bytes.fromhex(command.get("frame", ""))
                timeout = command.get("timeout", 1.0)
                
                logger.debug(f"Auth step {step}: sending {frame.hex()}")
                card_response = tag.clf.exchange(frame, timeout)
                logger.debug(f"Card response: {card_response.hex()}")
                
                # Send card response back to server
                response = self._http_post("/mutual-authentication", {
                    "session_id": self.session_id,
                    "card_response": card_response.hex(),
                })
                self.session_id = response.get("session_id", self.session_id)
                
            elif step == "complete":
                self.authenticated = True
                return response.get("result", {})
            else:
                raise RuntimeError(f"Unexpected auth step: {step}")
    
    def _read_encrypted_blocks(self, tag, service_index: int, block_indexes: list) -> list:
        """Read encrypted blocks via remote server"""
        if not self.authenticated:
            raise RuntimeError("Not authenticated")
        
        # Build payload for read command
        elements = []
        for block_idx in block_indexes:
            elements.append(0x80 | service_index)
            elements.append(block_idx & 0xFF)
        
        payload = bytes([len(block_indexes)]) + bytes(elements)
        
        # Send to server
        response = self._http_post("/encryption-exchange", {
            "session_id": self.session_id,
            "cmd_code": 0x14,  # Read command
            "payload": payload.hex(),
        })
        self.session_id = response.get("session_id", self.session_id)
        
        # Get encrypted command and send to card
        command = response.get("command", {})
        frame = bytes.fromhex(command.get("frame", ""))
        timeout = command.get("timeout", 1.0)
        
        card_response = tag.clf.exchange(frame, timeout)
        
        # Send card response to server for decryption
        final_response = self._http_post("/encryption-exchange", {
            "session_id": self.session_id,
            "card_response": card_response.hex(),
        })
        
        # Parse decrypted response
        response_hex = final_response.get("response", "")
        response_bytes = bytes.fromhex(response_hex)
        
        if len(response_bytes) < 3:
            raise RuntimeError("Invalid response from server")
        
        status1, status2 = response_bytes[0], response_bytes[1]
        if status1 != 0x00:
            raise RuntimeError(f"Card error: 0x{status1:02X}{status2:02X}")
        
        block_count = response_bytes[2]
        block_data = response_bytes[3:]
        
        blocks = []
        for i in range(block_count):
            offset = i * 16
            if offset + 16 <= len(block_data):
                blocks.append(block_data[offset:offset + 16])
        
        return blocks
    
    def _parse_date(self, value: int) -> str:
        """Parse Suica date format"""
        year = (value >> 9) & 0x7F
        month = (value >> 5) & 0x0F
        day = value & 0x1F
        return f"{year:02d}-{month:02d}-{day:02d}"
    
    def _format_station(self, line_code: int, station_order: int) -> str:
        """Format station code"""
        return f"線区:{line_code:02X} 駅順:{station_order:02X}"
    
    def read_card(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Read Suica card using nfcpy with remote authentication"""
        if not NFCPY_AVAILABLE:
            return {"error": "nfcpy not installed"}
        
        card_data = {
            "timestamp": datetime.now().isoformat(),
            "reader_type": "nfcpy (USB direct)",
        }
        
        try:
            # Open NFC reader
            with nfc.ContactlessFrontend("usb") as clf:
                logger.info("nfcpy: Waiting for card...")
                
                # Container for tag
                tag_holder = [None]
                
                def on_connect(tag):
                    if isinstance(tag, FelicaStandard):
                        tag_holder[0] = tag
                        return True  # Keep tag connected
                    return False
                
                # Try to connect
                connected = clf.connect(
                    rdwr={
                        "targets": ["212F", "424F"],
                        "on-connect": on_connect,
                    },
                    terminate=lambda: tag_holder[0] is not None,
                )
                
                tag = tag_holder[0]
                if tag is None:
                    return {"error": "No FeliCa card detected"}
                
                # Get card ID
                polling_result = tag.polling(self.SYSTEM_CODE)
                if len(polling_result) >= 2:
                    tag.idm, tag.pmm = polling_result[0], polling_result[1]
                
                card_data["idm"] = tag.idm.hex().upper()
                card_data["pmm"] = tag.pmm.hex().upper()
                card_data["card_type"] = "Suica/Pasmo/ICOCA"
                
                # Perform mutual authentication
                logger.info("nfcpy: Starting mutual authentication...")
                auth_result = self._mutual_authentication(tag)
                
                idi = auth_result.get("issue_id", auth_result.get("idi", ""))
                pmi = auth_result.get("issue_parameter", auth_result.get("pmi", ""))
                
                card_data["idi"] = idi.upper() if idi else None
                card_data["pmi"] = pmi.upper() if pmi else None
                card_data["authenticated"] = True
                
                # Read attribute info (balance)
                logger.info("nfcpy: Reading balance...")
                try:
                    attr_blocks = self._read_encrypted_blocks(tag, 1, [0])
                    if attr_blocks and len(attr_blocks) > 0:
                        block = attr_blocks[0]
                        card_type_code = block[8] >> 4
                        card_data["card_type_detail"] = self.CARD_TYPE_LABELS.get(card_type_code, "不明")
                        
                        balance = int.from_bytes(block[11:13], byteorder="little")
                        card_data["balance"] = f"¥{balance:,}"
                        card_data["balance_raw"] = balance
                        
                        transaction_number = int.from_bytes(block[14:16], byteorder="big")
                        card_data["transaction_count"] = transaction_number
                except Exception as e:
                    logger.warning(f"Failed to read balance: {e}")
                    card_data["balance_error"] = str(e)
                
                # Read transaction history
                logger.info("nfcpy: Reading transaction history...")
                try:
                    history_blocks = self._read_encrypted_blocks(tag, 4, list(range(10)))
                    history = []
                    
                    for i, block in enumerate(history_blocks):
                        if block[0] == 0x00:
                            continue  # Empty entry
                        
                        recorded_by = block[0]
                        transaction_type = block[1] & 0x7F
                        recorded_at = int.from_bytes(block[4:6], byteorder="big")
                        
                        entry_line, entry_station = block[6], block[7]
                        exit_line, exit_station = block[8], block[9]
                        
                        amount = int.from_bytes(block[10:12], byteorder="little")
                        
                        history.append({
                            "no": i,
                            "date": self._parse_date(recorded_at),
                            "type": self.TRANSACTION_TYPES.get(transaction_type, f"不明({transaction_type:02X})"),
                            "device": self.EQUIPMENT_TYPES.get(recorded_by, f"不明({recorded_by:02X})"),
                            "entry": self._format_station(entry_line, entry_station),
                            "exit": self._format_station(exit_line, exit_station),
                            "balance_after": amount,
                        })
                    
                    if history:
                        card_data["history_count"] = len(history)
                        card_data["recent_history"] = history[:5]
                except Exception as e:
                    logger.warning(f"Failed to read history: {e}")
                    card_data["history_error"] = str(e)
                
                return card_data
                
        except Exception as e:
            logger.error(f"nfcpy Suica read error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": str(e),
                "error_type": type(e).__name__,
                "hint": "Make sure PC/SC service is stopped or no other program is using the reader"
            }


# =============================================================================
# Zairyu Card Reader (在留カード) - Based on Official Spec Ver 1.5
# =============================================================================

class ZairyuCardReader:
    """
    Japanese Residence Card (在留カード) reader.
    Based on 在留カード等仕様書 Ver 1.5 (令和6年3月) - Immigration Services Agency
    
    Authentication: Card number only (12 characters)
    Protocol: SELECT MF → GET CHALLENGE → MUTUAL AUTH → VERIFY(card#) → READ
    
    No PIN retry limit - uses card number printed on card.
    """
    
    # AIDs from official specification (Section 3.3.2)
    AID_MF = []  # Master File - no AID needed, select with P1=00
    AID_DF1 = [0xD3, 0x92, 0xF0, 0x00, 0x4F, 0x02, 0x00, 0x00, 
               0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]  # 券面イメージ, 顔写真
    AID_DF2 = [0xD3, 0x92, 0xF0, 0x00, 0x4F, 0x03, 0x00, 0x00,
               0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]  # 券面(様式)テキスト
    AID_DF3 = [0xD3, 0x92, 0xF0, 0x00, 0x4F, 0x04, 0x00, 0x00,
               0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]  # 電子署名
    
    # EF Short IDs (from Section 3.3.4)
    # MF files
    EF_MF_COMMON = 0x01      # 共通データ要素 (free access)
    EF_MF_CARD_TYPE = 0x02   # カード種別 (free access)
    
    # DF1 files (needs auth)
    EF_DF1_FRONT_IMAGE = 0x05   # 券面(表)イメージ - ~7000 bytes JPEG
    EF_DF1_PHOTO = 0x06         # 顔写真 - ~3000 bytes JPEG
    
    # DF2 files (needs auth) - Per 在留カード等仕様書 Ver 1.5 Section 3.3.4
    # DF2 contains ADDRESS and ENDORSEMENTS only, NOT personal info!
    EF_DF2_ADDRESS = 0x01           # 住居地（裏面追記）- Address (back of card)
    EF_DF2_ENDORSEMENT_1 = 0x02     # 裏面資格外活動包括許可欄 - Endorsement section 1
    EF_DF2_ENDORSEMENT_2 = 0x03     # 裏面資格外活動個別許可欄 - Endorsement section 2  
    EF_DF2_ENDORSEMENT_3 = 0x04     # 裏面在留期間等更新申請欄 - Endorsement section 3
    
    # DF3 files (free access after auth)
    EF_DF3_SIGNATURE = 0x02     # 電子署名 (checkcode + certificate)
    
    
    def __init__(self, connection):
        self.connection = connection
        self.ks_enc = None  # Session encryption key
        self.ks_mac = None  # Session MAC key (not used in this spec)
        self.authenticated = False
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        """Send APDU and return response"""
        try:
            data, sw1, sw2 = self.connection.transmit(apdu)
            # Log at INFO level for important commands
            if apdu[1] in [0xA4, 0x84, 0x82, 0x20]:  # SELECT, GET CHALLENGE, MUTUAL AUTH, VERIFY
                logger.info(f"APDU TX: {toHexString(apdu)}")
                logger.info(f"APDU RX: data={toHexString(data) if data else 'empty'}, SW={sw1:02X}{sw2:02X}")
            else:
                logger.debug(f"APDU: {toHexString(apdu)} -> SW={sw1:02X}{sw2:02X}")
            return data, sw1, sw2
        except Exception as e:
            logger.error(f"APDU transmit error: {e}")
            raise
    
    def get_uid(self) -> Optional[str]:
        """Get card UID"""
        data, sw1, sw2 = self.send_apdu(APDU.GET_UID)
        if sw1 == 0x90:
            return toHexString(data).replace(" ", "")
        return None
    
    def select_mf(self) -> bool:
        """
        Select Master File (MF).
        Per 在留カード等仕様書 Ver 1.5 別添2:
        SELECT MF by File ID: 00 A4 00 00 02 3F 00
        """
        # SELECT MF by File ID 3F00 (per spec 別添2)
        cmd = [0x00, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00]
        logger.info(f"SELECT MF (by File ID 3F00): {toHexString(cmd)}")
        data, sw1, sw2 = self.send_apdu(cmd)
        logger.info(f"SELECT MF response: SW={sw1:02X}{sw2:02X}")
        if sw1 != 0x90:
            logger.error(f"SELECT MF failed with SW={sw1:02X}{sw2:02X}")
        return sw1 == 0x90
    
    def select_df(self, aid: List[int]) -> bool:
        """Select Dedicated File by AID"""
        # SELECT DF: 00 A4 04 0C Lc [AID]
        cmd = [0x00, 0xA4, 0x04, 0x0C, len(aid)] + aid
        logger.info(f"SELECT DF: AID={toHexString(aid[:8])}...")
        data, sw1, sw2 = self.send_apdu(cmd)
        if sw1 == 0x90:
            logger.info("DF selected successfully")
            return True
        else:
            logger.error(f"SELECT DF failed: SW={sw1:02X}{sw2:02X}")
            return False
    
    def get_challenge(self) -> Optional[bytes]:
        """Get 8-byte challenge from card"""
        # GET CHALLENGE: 00 84 00 00 08
        cmd = [0x00, 0x84, 0x00, 0x00, 0x08]
        logger.info(f"GET CHALLENGE: {toHexString(cmd)}")
        data, sw1, sw2 = self.send_apdu(cmd)
        logger.info(f"GET CHALLENGE response: SW={sw1:02X}{sw2:02X}, data_len={len(data)}")
        if data:
            logger.info(f"GET CHALLENGE data: {toHexString(data)}")
        if sw1 == 0x90 and len(data) == 8:
            return bytes(data)
        elif sw1 == 0x6A and sw2 == 0x82:
            logger.error("GET CHALLENGE failed: File not found - MF may not be selected")
        elif sw1 == 0x69 and sw2 == 0x85:
            logger.error("GET CHALLENGE failed: Conditions not satisfied")
        elif sw1 == 0x6D and sw2 == 0x00:
            logger.error("GET CHALLENGE failed: Command not supported")
        else:
            logger.error(f"GET CHALLENGE failed: SW={sw1:02X}{sw2:02X}")
        return None
    
    
    def _pad_data(self, data: bytes) -> bytes:
        """Apply ISO 9797-1 padding (method 2)"""
        padded = data + bytes([0x80])
        while len(padded) % 8 != 0:
            padded += bytes([0x00])
        return padded
    
    def _unpad_data(self, data: bytes) -> bytes:
        """Remove ISO 9797-1 padding"""
        i = len(data) - 1
        while i >= 0 and data[i] == 0x00:
            i -= 1
        if i >= 0 and data[i] == 0x80:
            return data[:i]
        return data
    
    def _compute_retail_mac(self, key: bytes, data: bytes) -> bytes:
        """
        Compute Retail MAC (ISO 9797-1 Algorithm 3).
        Uses two-key variant: Ka for CBC-MAC, then D_Kb(H), then E_Ka(H).
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome required")
        
        padded = self._pad_data(data)
        ka = key[:8]
        kb = key[8:16]
        
        logger.debug(f"Retail MAC: Ka={toHexString(list(ka))}, Kb={toHexString(list(kb))}")
        logger.debug(f"Retail MAC: padded data ({len(padded)} bytes)")
        
        # CBC-MAC with Ka
        h = bytes(8)
        cipher_a = DES.new(ka, DES.MODE_ECB)
        for i in range(0, len(padded), 8):
            block = padded[i:i+8]
            xored = bytes(a ^ b for a, b in zip(h, block))
            h = cipher_a.encrypt(xored)
        
        logger.debug(f"Retail MAC after CBC-MAC: {toHexString(list(h))}")
        
        # Final: D_Kb(H) then E_Ka(H)
        cipher_b = DES.new(kb, DES.MODE_ECB)
        h = cipher_b.decrypt(h)
        logger.debug(f"Retail MAC after D_Kb: {toHexString(list(h))}")
        h = cipher_a.encrypt(h)
        logger.debug(f"Retail MAC final: {toHexString(list(h))}")
        
        return h
    
    def _tdes_ede_block(self, k1: bytes, k2: bytes, block: bytes, encrypt: bool = True) -> bytes:
        """
        Single block 3DES-EDE2 operation (no CBC, just one 8-byte block).
        EDE = Encrypt-Decrypt-Encrypt with K1, K2, K1
        """
        cipher_k1 = DES.new(k1, DES.MODE_ECB)
        cipher_k2 = DES.new(k2, DES.MODE_ECB)
        
        if encrypt:
            # E_K1(D_K2(E_K1(plaintext)))
            step1 = cipher_k1.encrypt(block)
            step2 = cipher_k2.decrypt(step1)
            step3 = cipher_k1.encrypt(step2)
            return step3
        else:
            # D_K1(E_K2(D_K1(ciphertext)))
            step1 = cipher_k1.decrypt(block)
            step2 = cipher_k2.encrypt(step1)
            step3 = cipher_k1.decrypt(step2)
            return step3
    
    def _tdes_encrypt(self, key: bytes, data: bytes) -> bytes:
        """
        3DES-EDE2 CBC encrypt with zero IV.
        Manually implements EDE to handle any key (including K1=K2).
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome required")
        
        k1 = key[:8]
        k2 = key[8:16]
        
        logger.debug(f"TDES encrypt: K1={toHexString(list(k1))}, K2={toHexString(list(k2))}")
        logger.debug(f"TDES encrypt: data ({len(data)} bytes) = {toHexString(list(data[:32]))}")
        
        # CBC mode with manual EDE
        iv = bytes(8)
        result = bytearray()
        prev_block = iv
        
        for i in range(0, len(data), 8):
            block = data[i:i+8]
            # XOR with previous ciphertext (or IV for first block)
            xored = bytes(a ^ b for a, b in zip(block, prev_block))
            # 3DES-EDE encrypt
            encrypted = self._tdes_ede_block(k1, k2, xored, encrypt=True)
            result.extend(encrypted)
            prev_block = encrypted
        
        logger.debug(f"TDES encrypt result: {toHexString(list(result))}")
        return bytes(result)
    
    def _tdes_decrypt(self, key: bytes, data: bytes) -> bytes:
        """
        3DES-EDE2 CBC decrypt with zero IV.
        Manually implements EDE to handle any key (including K1=K2).
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome required")
        
        k1 = key[:8]
        k2 = key[8:16]
        
        # CBC mode with manual EDE
        iv = bytes(8)
        result = bytearray()
        prev_block = iv
        
        for i in range(0, len(data), 8):
            block = data[i:i+8]
            # 3DES-EDE decrypt
            decrypted = self._tdes_ede_block(k1, k2, block, encrypt=False)
            # XOR with previous ciphertext (or IV for first block)
            xored = bytes(a ^ b for a, b in zip(decrypted, prev_block))
            result.extend(xored)
            prev_block = block
        
        return bytes(result)
    
    def _compute_session_key(self, key_material: bytes) -> bytes:
        """
        Compute session key from key material.
        KSenc = SHA1(K.IFD XOR K.ICC || 00000001)[:16] with parity adjustment
        """
        d = key_material + bytes([0x00, 0x00, 0x00, 0x01])
        h = hashlib.sha1(d).digest()
        
        # Take first 16 bytes and adjust parity
        key = bytearray(h[:16])
        for i in range(16):
            b = key[i]
            parity = bin(b).count('1') % 2
            if parity == 0:
                key[i] ^= 1
        
        return bytes(key)
    
    def _derive_auth_keys(self, card_number: str) -> tuple:
        """
        Derive Kenc and Kmac from card number for Mutual Authentication.
        Per 在留カード等仕様書 Ver 1.5 別添1:
        Kenc = Kmac = SHA-1(Card Number)[0:16]
        
        Args:
            card_number: 12-character card number (在留カード番号)
        
        Returns:
            (k_enc, k_mac) tuple - both are the same 16-byte key
        """
        if len(card_number) != 12:
            raise ValueError("Card number must be 12 characters")
        
        # SHA-1 hash of the card number (ASCII bytes)
        h = hashlib.sha1(card_number.encode('ascii')).digest()
        
        # Use first 16 bytes as the key (TDES 2-key)
        key = h[:16]
        
        logger.info(f"Derived key from card number: {toHexString(list(key))}")
        
        # Kenc and Kmac are identical for mutual authentication
        return key, key
    
    def mutual_authenticate(self, card_number: str) -> bool:
        """
        Perform Mutual Authentication to establish session key.
        Based on 別添1 セキュアメッセージングセッション鍵交換
        
        Args:
            card_number: 12-character card number for key derivation
        
        Returns True if successful, sets self.ks_enc
        """
        if not CRYPTO_AVAILABLE:
            logger.error("pycryptodome required for mutual authentication")
            return False
        
        # Derive initial keys from card number (per 在留カード等仕様書 Ver 1.5)
        k_enc, k_mac = self._derive_auth_keys(card_number)
        
        logger.info(f"K_ENC for auth: {toHexString(list(k_enc))}")
        logger.info(f"K_MAC for auth: {toHexString(list(k_mac))}")
        
        # Step 1: Get challenge from card
        logger.info("Mutual Auth Step 1: Getting challenge from card...")
        rnd_icc = self.get_challenge()
        if not rnd_icc:
            logger.error("Failed to get challenge from card - check card positioning and type")
            return False
        
        logger.info(f"RND.ICC (8 bytes): {toHexString(list(rnd_icc))}")
        
        # Step 2: Generate terminal random and key material
        rnd_ifd = os.urandom(8)
        k_ifd = os.urandom(16)
        
        logger.info(f"RND.IFD: {toHexString(list(rnd_ifd))}")
        logger.info(f"K.IFD: {toHexString(list(k_ifd))}")
        
        # Step 3: Build and encrypt S = RND.IFD || RND.ICC || K.IFD
        # Per 在留カード等仕様書 Ver 1.5, S is 32 bytes and encrypted WITHOUT padding
        # E_IFD should be exactly 32 bytes
        s = rnd_ifd + rnd_icc + k_ifd  # 32 bytes (8 + 8 + 16)
        
        e_ifd = self._tdes_encrypt(k_enc, s)  # No padding - 32 bytes in, 32 bytes out
        m_ifd = self._compute_retail_mac(k_mac, e_ifd)
        
        logger.info(f"E_IFD: {toHexString(list(e_ifd))}")
        logger.info(f"M_IFD: {toHexString(list(m_ifd))}")
        
        # Step 4: Send MUTUAL AUTHENTICATE command
        # Per spec: 00 82 00 00 28 [E_IFD 32 bytes] [M_IFD 8 bytes] 00
        cmd_data = list(e_ifd) + list(m_ifd)  # 32 + 8 = 40 bytes
        cmd = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + cmd_data + [0x00]
        
        logger.info(f"MUTUAL AUTH cmd length: {len(cmd_data)} (E_IFD={len(e_ifd)}, M_IFD={len(m_ifd)})")
        
        data, sw1, sw2 = self.send_apdu(cmd)
        
        if sw1 != 0x90:
            logger.error(f"MUTUAL AUTHENTICATE failed: SW={sw1:02X}{sw2:02X}")
            return False
        
        if len(data) != 40:
            logger.error(f"Invalid response length: {len(data)} (expected 40)")
            return False
        
        # Step 5: Parse response - E_ICC is 32 bytes, M_ICC is 8 bytes
        e_icc = bytes(data[:32])
        m_icc = bytes(data[32:40])
        
        logger.info(f"E_ICC: {toHexString(list(e_icc))}")
        logger.info(f"M_ICC: {toHexString(list(m_icc))}")
        
        # Step 6: Verify MAC
        computed_mac = self._compute_retail_mac(k_mac, e_icc)
        if computed_mac != m_icc:
            logger.error("MAC verification failed")
            logger.error(f"Computed: {toHexString(list(computed_mac))}")
            logger.error(f"Received: {toHexString(list(m_icc))}")
            return False
        
        # Step 7: Decrypt response - no padding was applied, so 32 bytes decrypt to 32 bytes
        # Result is: RND.ICC || RND.IFD || K.ICC
        decrypted = self._tdes_decrypt(k_enc, e_icc)
        
        logger.info(f"Decrypted ({len(decrypted)} bytes): {toHexString(list(decrypted))}")
        
        if len(decrypted) != 32:
            logger.error(f"Invalid decrypted length: {len(decrypted)} (expected 32)")
            return False
        
        rnd_icc_resp = decrypted[:8]
        rnd_ifd_resp = decrypted[8:16]
        k_icc = decrypted[16:32]
        
        # Step 8: Verify RND values
        # Per spec, response contains: RND.ICC || RND.IFD || K.ICC
        logger.info(f"RND.ICC from response: {toHexString(list(rnd_icc_resp))}")
        logger.info(f"RND.IFD from response: {toHexString(list(rnd_ifd_resp))}")
        logger.info(f"K.ICC: {toHexString(list(k_icc))}")
        
        if rnd_icc_resp != rnd_icc:
            logger.error(f"RND.ICC mismatch!")
            logger.error(f"  Expected: {toHexString(list(rnd_icc))}")
            logger.error(f"  Got:      {toHexString(list(rnd_icc_resp))}")
            return False
        
        if rnd_ifd_resp != rnd_ifd:
            logger.error(f"RND.IFD mismatch!")
            logger.error(f"  Expected: {toHexString(list(rnd_ifd))}")
            logger.error(f"  Got:      {toHexString(list(rnd_ifd_resp))}")
            return False
        
        logger.info("RND values verified successfully")
        
        # Step 9: Compute session key
        # KSenc = h(K.IFD XOR K.ICC || "00000001")[:16] with parity adjustment
        key_material = bytes(a ^ b for a, b in zip(k_ifd, k_icc))
        logger.info(f"Key material (K.IFD XOR K.ICC): {toHexString(list(key_material))}")
        
        self.ks_enc = self._compute_session_key(key_material)
        
        logger.info(f"Session key KSenc established: {toHexString(list(self.ks_enc))}")
        
        return True
    
    def verify_card_number(self, card_number: str) -> bool:
        """
        Verify card number (在留カード等番号による認証).
        Card number is 12 characters (e.g., "AB12345678CD").
        
        Must be called after mutual_authenticate().
        Uses Secure Messaging with session key.
        """
        if not self.ks_enc:
            logger.error("Session key not established")
            return False
        
        if len(card_number) != 12:
            logger.error(f"Invalid card number length: {len(card_number)} (expected 12)")
            return False
        
        # Step 1: Pad card number to 16 bytes
        card_bytes = card_number.encode('ascii')
        card_padded = self._pad_data(card_bytes)  # 12 + 0x80 + padding = 16 bytes
        
        logger.info(f"Card number padded: {toHexString(list(card_padded))}")
        
        # Step 2: Encrypt with session key
        encrypted_card = self._tdes_encrypt(self.ks_enc, card_padded)
        
        logger.info(f"Encrypted card#: {toHexString(list(encrypted_card))}")
        
        # Step 3: Build VERIFY command with Secure Messaging
        # CLA=08 (SM), INS=20, P1=00, P2=86
        # Data: 86 11 01 [encrypted card# 16 bytes]
        # 86 = Cryptogram tag, 11 = length (17), 01 = padding indicator
        sm_data = [0x86, 0x11, 0x01] + list(encrypted_card)
        cmd = [0x08, 0x20, 0x00, 0x86, len(sm_data)] + sm_data
        
        data, sw1, sw2 = self.send_apdu(cmd)
        
        if sw1 == 0x90:
            self.authenticated = True
            logger.info("Card number verified successfully")
            return True
        else:
            logger.error(f"VERIFY failed: SW={sw1:02X}{sw2:02X}")
            return False
    
    def read_binary_sm(self, ef_id: int, max_length: int = 8000) -> Optional[bytes]:
        """
        Read binary data with Secure Messaging.
        Per 在留カード等仕様書 Ver 1.5 別添2.
        
        Args:
            ef_id: Short EF ID (0x01-0x1F)
            max_length: Maximum bytes to read
        
        Returns:
            Decrypted data or None
        """
        if not self.ks_enc or not self.authenticated:
            logger.error("Not authenticated")
            return None
        
        # READ BINARY with SM
        # CLA=08, INS=B0, P1=0x80|ef_id (short EF), P2=00 (offset)
        # Data field for SM: 96 02 [expected length 2 bytes]
        # Le = 00 00 (extended)
        
        all_data = bytearray()
        offset = 0
        
        logger.info(f"Reading EF {ef_id:02X} with SM...")
        
        while offset < max_length:
            # P1 = 0x80 | ef_id for first read, then use offset
            if offset == 0:
                p1 = 0x80 | ef_id
                p2 = 0x00
            else:
                p1 = (offset >> 8) & 0x7F
                p2 = offset & 0xFF
            
            # SM data: 96 02 [expected length]
            chunk_size = min(256, max_length - offset)
            sm_data = [0x96, 0x02, (chunk_size >> 8) & 0xFF, chunk_size & 0xFF]
            
            # Extended length APDU
            cmd = [0x08, 0xB0, p1, p2, 0x00, 0x00, len(sm_data)] + sm_data + [0x00, 0x00]
            
            data, sw1, sw2 = self.send_apdu(cmd)
            
            if sw1 != 0x90:
                if offset == 0:
                    logger.error(f"READ BINARY EF{ef_id:02X} failed: SW={sw1:02X}{sw2:02X}")
                    return None
                else:
                    logger.info(f"READ BINARY EF{ef_id:02X} ended at offset {offset}: SW={sw1:02X}{sw2:02X}")
                    break  # End of file
            
            if len(data) < 4:
                logger.warning(f"Response too short: {len(data)} bytes")
                break
            
            logger.debug(f"SM response: {toHexString(list(data[:32]))}...")
            
            # Parse SM response: 86 [len] 01 [encrypted data]
            if data[0] != 0x86:
                logger.warning(f"Unexpected tag: {data[0]:02X} (expected 86)")
                break
            
            # Get length (could be 1, 2, or 3 bytes)
            idx = 1
            if data[idx] == 0x82:
                data_len = (data[idx+1] << 8) | data[idx+2]
                idx += 3
            elif data[idx] == 0x81:
                data_len = data[idx+1]
                idx += 2
            else:
                data_len = data[idx]
                idx += 1
            
            # Get the cryptogram content (includes padding indicator)
            enc_content = bytes(data[idx:idx+data_len])
            
            # First byte is padding indicator (01 = padding present)
            if len(enc_content) > 0 and enc_content[0] == 0x01:
                enc_data = enc_content[1:]
            else:
                enc_data = enc_content
                logger.debug(f"No padding indicator byte in cryptogram")
            
            logger.debug(f"Encrypted data: {len(enc_data)} bytes")
            
            # Decrypt (data should already be 8-byte aligned from card)
            if len(enc_data) % 8 != 0:
                # Pad to 8-byte boundary for decryption if needed
                padding_needed = 8 - (len(enc_data) % 8)
                enc_data = enc_data + bytes(padding_needed)
                logger.debug(f"Added {padding_needed} bytes padding for decryption")
            
            decrypted = self._tdes_decrypt(self.ks_enc, enc_data)
            
            # Remove ISO 9797-1 padding (0x80 followed by zeros)
            decrypted = self._unpad_data(decrypted)
            
            logger.debug(f"Decrypted {len(decrypted)} bytes: {toHexString(list(decrypted[:32]))}...")
            
            all_data.extend(decrypted)
            offset += len(decrypted)
            
            if len(decrypted) < chunk_size:
                logger.info(f"EF{ef_id:02X} read complete: {len(all_data)} bytes total")
                break  # End of file
        
        return bytes(all_data) if all_data else None
    
    def read_binary_plain(self, ef_id: int, max_length: int = 256) -> Optional[bytes]:
        """Read binary without SM (for free access files)"""
        all_data = bytearray()
        offset = 0
        
        while offset < max_length:
            p1 = 0x80 | ef_id if offset == 0 else (offset >> 8) & 0x7F
            p2 = 0x00 if offset == 0 else offset & 0xFF
            
            # Standard READ BINARY
            cmd = [0x00, 0xB0, p1, p2, 0x00]
            data, sw1, sw2 = self.send_apdu(cmd)
            
            if sw1 == 0x6C:
                # Retry with correct length
                cmd = [0x00, 0xB0, p1, p2, sw2]
                data, sw1, sw2 = self.send_apdu(cmd)
            
            if sw1 != 0x90:
                break
            
            all_data.extend(data)
            offset += len(data)
            
            if len(data) < 256:
                break
        
        return bytes(all_data) if all_data else None
    
    def _parse_tlv_data(self, data: bytes, tag: int) -> Optional[bytes]:
        """Extract data from TLV structure"""
        i = 0
        while i < len(data):
            t = data[i]
            i += 1
            
            if i >= len(data):
                break
            
            # Get length
            l = data[i]
            i += 1
            
            if l == 0x81:
                if i >= len(data):
                    break
                l = data[i]
                i += 1
            elif l == 0x82:
                if i + 1 >= len(data):
                    break
                l = (data[i] << 8) | data[i + 1]
                i += 2
            
            if i + l > len(data):
                break
            
            v = data[i:i + l]
            i += l
            
            if t == tag:
                return v
        
        return None
    
    def read_common_data(self) -> Dict[str, Any]:
        """
        Read common data (共通データ要素) - no authentication required.
        Returns card version, issuer info, etc.
        """
        result = {}
        
        if not self.select_mf():
            result["error"] = "Cannot select MF"
            return result
        
        data = self.read_binary_plain(self.EF_MF_COMMON)
        if data:
            result["common_data_raw"] = toHexString(list(data))
            result["common_data_available"] = True
        
        return result
    
    def read_card_type(self) -> Dict[str, Any]:
        """
        Read card type (カード種別) - no authentication required.
        Returns whether this is 在留カード or 特別永住者証明書.
        """
        result = {}
        
        if not self.select_mf():
            result["error"] = "Cannot select MF"
            return result
        
        data = self.read_binary_plain(self.EF_MF_CARD_TYPE)
        if data:
            result["card_type_raw"] = toHexString(list(data))
            # Parse card type
            if len(data) >= 1:
                card_type_code = data[0]
                if card_type_code == 0x01:
                    result["card_type"] = "在留カード"
                    result["card_type_en"] = "Residence Card"
                elif card_type_code == 0x02:
                    result["card_type"] = "特別永住者証明書"
                    result["card_type_en"] = "Special Permanent Resident Certificate"
                else:
                    result["card_type"] = f"Unknown ({card_type_code:02X})"
        
        return result
    
    def read_front_image(self) -> Optional[bytes]:
        """
        Read front card image (券面(表)イメージ) - requires authentication.
        Returns JPEG image data (~7000 bytes).
        Per 在留カード等仕様書 Ver 1.5, stored in DF1/EF05.
        """
        logger.info("Reading 券面(表)イメージ from DF1/EF05...")
        
        if not self.select_df(self.AID_DF1):
            logger.error("Cannot select DF1 for front image")
            return None
        
        logger.info("DF1 selected for front image")
        data = self.read_binary_sm(self.EF_DF1_FRONT_IMAGE, 8000)
        
        if data:
            logger.info(f"Front image raw data: {len(data)} bytes")
            # Parse TLV: D0 82 [len] [JPEG data]
            jpeg = self._parse_tlv_data(data, 0xD0)
            if jpeg:
                logger.info(f"Front image JPEG extracted: {len(jpeg)} bytes")
                # Verify JPEG header (FFD8)
                if len(jpeg) >= 2 and jpeg[0] == 0xFF and jpeg[1] == 0xD8:
                    logger.info("Front image has valid JPEG header")
                else:
                    logger.warning(f"Front image doesn't have JPEG header: {toHexString(list(jpeg[:4]))}")
                return jpeg
            else:
                logger.warning("Could not extract JPEG from TLV (tag D0)")
                return data
        else:
            logger.warning("Could not read front image data")
        
        return None
    
    def read_photo(self) -> Optional[bytes]:
        """
        Read face photo (顔写真) - requires authentication.
        Returns JPEG image data (~3000 bytes).
        Per 在留カード等仕様書 Ver 1.5, stored in DF1/EF06.
        """
        logger.info("Reading 顔写真 from DF1/EF06...")
        
        if not self.select_df(self.AID_DF1):
            logger.error("Cannot select DF1 for photo")
            return None
        
        logger.info("DF1 selected for photo")
        data = self.read_binary_sm(self.EF_DF1_PHOTO, 4000)
        
        if data:
            logger.info(f"Photo raw data: {len(data)} bytes")
            # Parse TLV: D1 82 [len] [JPEG data]
            jpeg = self._parse_tlv_data(data, 0xD1)
            if jpeg:
                logger.info(f"Photo JPEG extracted: {len(jpeg)} bytes")
                # Verify JPEG header (FFD8)
                if len(jpeg) >= 2 and jpeg[0] == 0xFF and jpeg[1] == 0xD8:
                    logger.info("Photo has valid JPEG header")
                else:
                    logger.warning(f"Photo doesn't have JPEG header: {toHexString(list(jpeg[:4]))}")
                return jpeg
            else:
                logger.warning("Could not extract JPEG from TLV (tag D1)")
                return data
        else:
            logger.warning("Could not read photo data")
        
        return None
    
    def _decode_text(self, data: bytes) -> str:
        """
        Decode text data trying multiple Japanese encodings.
        Zairyu cards typically use Shift-JIS (CP932) for Japanese text.
        """
        # Try Shift-JIS first (most common for Japanese government cards)
        for encoding in ['cp932', 'shift-jis', 'utf-8', 'euc-jp', 'iso-2022-jp']:
            try:
                decoded = data.decode(encoding)
                # Check if decoding looks valid (no replacement chars)
                if '\ufffd' not in decoded:
                    return decoded
            except (UnicodeDecodeError, LookupError):
                continue
        # Fallback: use cp932 with errors replaced
        return data.decode('cp932', errors='replace')
    
    def _get_ocr_reader(self):
        """
        Get or create EasyOCR reader instance (lazy loading).
        Supports Japanese and English for Zairyu card reading.
        """
        global _ocr_reader
        
        if not EASYOCR_AVAILABLE:
            return None
        
        if _ocr_reader is None:
            logger.info("Initializing EasyOCR reader (first time, may take a moment)...")
            try:
                # Japanese + English for mixed text on Zairyu cards
                _ocr_reader = easyocr.Reader(['ja', 'en'], gpu=False)
                logger.info("EasyOCR reader initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize EasyOCR: {e}")
                return None
        
        return _ocr_reader
    
    def extract_text_from_image(self, image_data: bytes) -> Dict[str, Any]:
        """
        Extract text from Zairyu card front image using OCR.
        
        The front card image contains:
        - Name (氏名) - e.g., "BUI NGOC YEN"
        - Card Number (在留カード番号) - e.g., "UH17622299ER"
        - Date of Birth (生年月日) - e.g., "2005年06月01日"
        - Gender (性別) - e.g., "女 F." or "男 M."
        - Nationality (国籍・地域) - e.g., "ベトナム"
        - Address (住居地) - e.g., "埼玉県川越市..."
        - Status of Residence (在留資格) - e.g., "留学"
        - Period of Stay (在留期間) - e.g., "3年11月"
        - Expiration Date (在留期間の満了日) - e.g., "2029年05月17日"
        - Work Permission (就労制限) - e.g., "就労不可" or "就労制限なし"
        
        Returns:
            Dict with extracted fields and raw OCR text
        """
        result = {
            "ocr_available": EASYOCR_AVAILABLE,
            "ocr_success": False,
            "raw_text": [],
            "parsed_fields": {}
        }
        
        if not EASYOCR_AVAILABLE:
            result["error"] = "EasyOCR not installed. Run: pip install easyocr"
            return result
        
        reader = self._get_ocr_reader()
        if not reader:
            result["error"] = "Failed to initialize OCR reader"
            return result
        
        try:
            logger.info(f"Running OCR on image ({len(image_data)} bytes)...")
            
            # Convert bytes to numpy array for EasyOCR
            img = Image.open(io.BytesIO(image_data))
            img_array = np.array(img)
            
            # Run OCR
            ocr_results = reader.readtext(img_array)
            
            # Extract all text - convert numpy types to native Python for JSON serialization
            all_text = []
            for (bbox, text, confidence) in ocr_results:
                # Convert numpy types to native Python types
                conf_value = float(confidence) if hasattr(confidence, 'item') else confidence
                # Convert bbox (list of [x,y] points) - each point may be numpy array
                bbox_native = []
                for point in bbox:
                    if hasattr(point, 'tolist'):
                        bbox_native.append(point.tolist())
                    elif isinstance(point, (list, tuple)):
                        bbox_native.append([int(x) if hasattr(x, 'item') else x for x in point])
                    else:
                        bbox_native.append(point)
                
                all_text.append({
                    "text": text,
                    "confidence": round(conf_value, 3),
                    "bbox": bbox_native
                })
                logger.info(f"OCR: '{text}' (conf: {conf_value:.2f})")
            
            result["raw_text"] = all_text
            result["ocr_success"] = True
            
            # Parse structured fields from OCR results
            parsed = self._parse_ocr_results(ocr_results)
            result["parsed_fields"] = parsed
            
            logger.info(f"OCR extracted {len(all_text)} text regions")
            
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            import traceback
            traceback.print_exc()
            result["error"] = str(e)
        
        return result
    
    def _parse_ocr_results(self, ocr_results: list) -> Dict[str, str]:
        """
        Parse OCR results by grouping text into visual lines.
        Uses Spatial Analysis - optimized for Zairyu Card layout.
        """
        parsed = {}

        # ---------------------------------------------------------
        # 1. HELPER: Group blocks into lines based on Y-coordinate
        # ---------------------------------------------------------
        sorted_blocks = sorted(ocr_results, key=lambda x: x[0][0][1])
        
        lines = []
        if sorted_blocks:
            current_line = [sorted_blocks[0]]
            current_y = sorted_blocks[0][0][0][1]
            
            for block in sorted_blocks[1:]:
                y = block[0][0][1]
                # If Y difference is small (< 20px), consider it the same line
                if abs(y - current_y) < 20:
                    current_line.append(block)
                else:
                    # Sort the completed line by X position (left to right)
                    current_line.sort(key=lambda x: x[0][0][0])
                    lines.append(current_line)
                    current_line = [block]
                    current_y = y
            
            # Append the last line
            current_line.sort(key=lambda x: x[0][0][0])
            lines.append(current_line)

        # Convert blocks to simple text strings per line
        text_lines = []
        for line in lines:
            line_text = " ".join([b[1] for b in line])
            text_lines.append(line_text)
            logger.info(f"OCR Line: {line_text}")

        # Combine all for fallback regex
        full_text = " ".join(text_lines)

        # ---------------------------------------------------------
        # 2. HELPER: Fix Japanese Date Typos (日 often read as 月)
        # ---------------------------------------------------------
        def fix_date_typo(date_str):
            if not date_str:
                return None
            # Replace common OCR errors where '日' is read as '月' at the end
            if re.match(r'.+\d{1,2}月$', date_str) and date_str.count('月') > 1:
                return date_str[:-1] + "日"
            return date_str

        # ---------------------------------------------------------
        # 3. PARSING LOGIC
        # ---------------------------------------------------------

        # --- A. Card Number (Top Right) ---
        # Pattern: UH17622299ER
        card_num_match = re.search(r'([A-Z]{2}\d{8}[A-Z]{2})', full_text.replace(" ", ""))
        if card_num_match:
            parsed["card_number"] = card_num_match.group(1)
            logger.info(f"Extracted card number: {parsed['card_number']}")

        # --- B. Name (Top Left) ---
        # Strategy: The name is typically the first line that:
        # 1. Is primarily Latin characters (may have mixed case due to OCR errors)
        # 2. Is NOT the card number
        # 3. Does not contain numbers or Japanese characters
        for line in text_lines:
            clean_line = line.strip()
            check_content = clean_line.replace(" ", "")
            
            # Skip if it's the card number
            if parsed.get("card_number") and check_content.upper() == parsed["card_number"]:
                continue
                
            # Skip if line contains numbers (like 2005, 3年)
            if re.search(r'\d', check_content):
                continue
            
            # Skip if line contains Japanese characters (hiragana, katakana, kanji)
            if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', check_content):
                continue

            # Check if it looks like a name:
            # - Primarily Latin letters (allow mixed case due to OCR errors like "NGoc")
            # - At least 3 chars total
            # - Exclude footer text
            check_upper = check_content.upper()
            if (check_content.isalpha() and 
                len(check_content) > 3 and 
                "VALIDITY" not in check_upper and 
                "PERIOD" not in check_upper and
                "CARD" not in check_upper and
                "FERICD" not in check_upper and
                "STUDENT" not in check_upper and
                "SRUDENT" not in check_upper):
                
                # Normalize to uppercase for consistency
                parsed["name"] = clean_line.upper()
                logger.info(f"Extracted name: {parsed['name']}")
                break

        # --- C. Date of Birth, Gender, Nationality (Middle Line) ---
        # Pattern: 2005年06月01日   女 F.   ベトナム
        dob_pattern = r'(\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?[日月])'
        
        for line in text_lines:
            dob_match = re.search(dob_pattern, line)
            if dob_match:
                # 1. Extract DOB
                raw_dob = dob_match.group(1).replace(" ", "")
                raw_dob = fix_date_typo(raw_dob)
                if raw_dob:
                    parsed["date_of_birth"] = raw_dob.replace("年", "-").replace("月", "-").replace("日", "")
                    logger.info(f"Extracted DOB: {parsed['date_of_birth']}")
                
                # 2. Extract Gender (on the same line)
                if '女' in line or 'F.' in line:
                    parsed["gender"] = "女"
                elif '男' in line or 'M.' in line:
                    parsed["gender"] = "男"
                
                # 3. Extract Nationality (on the same line, after Gender)
                remaining = re.sub(dob_pattern, '', line)
                remaining = re.sub(r'(女|F\.|男|M\.)', '', remaining)
                remaining = re.sub(r'[YMD]', '', remaining).strip()  # Remove OCR noise
                
                # Map known nationalities
                nationalities = [
                    'ベトナム', 'ヴェトナム', '中国', '韓国', 'フィリピン', 
                    'インドネシア', 'ネパール', 'ミャンマー', 'タイ', 
                    'スリランカ', 'バングラデシュ', 'インド', 'ブラジル', 
                    'ペルー', '米国', 'アメリカ',
                ]
                for nationality in nationalities:
                    if nationality in remaining or nationality in line:
                        parsed["nationality"] = nationality
                        break
                
                break  # Found DOB line

        # --- D. Period of Stay & Expiration ---
        # Pattern: 3年11月 (2029年05月17日)
        # Use STRICT regex to extract actual date inside parens, ignoring garbage
        # The key is to match the specific date format, not just "anything in parens"
        period_pattern = r'(\d+\s?年(?:\s?\d+\s?月)?)\s*[（\(].*?(\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?[日月]).*?[）\)]'
        
        found_period = False
        for line in text_lines:
            match = re.search(period_pattern, line)
            if match:
                duration = match.group(1).replace(" ", "")  # e.g., 3年11月
                expiry_raw = match.group(2).replace(" ", "")  # e.g., 2029年05月17日
                
                # Fix common OCR typo where 日 is read as 月
                expiry_raw = fix_date_typo(expiry_raw)
                
                parsed["period_of_stay"] = f"{duration} ({expiry_raw}まで)"
                parsed["expiration_date"] = expiry_raw
                logger.info(f"Extracted period: {parsed['period_of_stay']}")
                found_period = True
                break
        
        # Fallback if strict regex failed (due to OCR garbage in parens - underlined text)
        if not found_period:
            # Just extract the duration (X年Y月) - don't try to get the corrupted underlined date
            # Pattern: X年 or X年Y月 where X is 1-2 digits (not 4-digit like DOB)
            dur_match = re.search(r'(?<!\d)(\d{1,2}年(?:\d{1,2}月)?)(?!\d)', full_text)
            if dur_match:
                parsed["period_of_stay"] = dur_match.group(1)
                logger.info(f"Extracted period: {parsed['period_of_stay']}")
        
        # Try to get expiration from the bottom "XXXX年XX月XX日まで有効" line (usually readable)
        if "expiration_date" not in parsed:
            valid_pattern = r'(\d{4}年\d{1,2}月\d{1,2}日)まで有効'
            valid_match = re.search(valid_pattern, full_text)
            if valid_match:
                parsed["expiration_date"] = valid_match.group(1)
                logger.info(f"Extracted expiration from まで有効: {parsed['expiration_date']}")

        # --- E. Status (e.g. 留学) ---
        known_statuses = [
            '留学', '技能実習', '技術・人文知識・国際業務', '家族滞在',
            '永住者', '定住者', '特定技能', '経営・管理', '高度専門職',
        ]
        for line in text_lines:
            for status in known_statuses:
                if status in line:
                    parsed["status_of_residence"] = status
                    logger.info(f"Extracted status: {parsed['status_of_residence']}")
                    break
            if "status_of_residence" in parsed:
                break

        # --- F. Address ---
        address_pattern = r'(?:東京都|北海道|京都府|大阪府|.{2,3}県).+?(?:市|区|町|村).+'
        for line in text_lines:
            if re.search(address_pattern, line) and not re.search(r'\d{4}年', line):
                parsed["address"] = line.strip()
                logger.info(f"Extracted address: {parsed['address']}")
                break

        # --- G. Work Restrictions ---
        if '就労不可' in full_text:
            parsed["work_permission"] = "就労不可"
        elif '就労制限なし' in full_text:
            parsed["work_permission"] = "就労制限なし"
        elif '指定書' in full_text:
            parsed["work_permission"] = "指定書により指定"

        # --- H. Valid Until (Fallback) ---
        if "expiration_date" not in parsed:
            valid_pattern = r'(\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?[日月])\s*まで'
            valid_match = re.search(valid_pattern, full_text)
            if valid_match:
                exp = valid_match.group(1).replace(" ", "")
                exp = fix_date_typo(exp)
                parsed["expiration_date"] = exp

        logger.info(f"Final Parsed Data: {parsed}")
        return parsed

    def _convert_image_to_jpeg(self, data: bytes) -> bytes:
        """
        Convert various image formats to standard JPEG for browser display.
        Zairyu cards store images in formats browsers don't natively support:
        
        Per 在留カード等仕様書:
        - Front image: Often TIFF format (header: 49 49 2A 00 = "II*")
        - Face photo: JPEG 2000 (JP2) format (header: 00 00 00 0C 6A 50)
        
        Returns:
            Standard JPEG bytes, or original data if already JPEG or conversion fails.
        """
        if not PILLOW_AVAILABLE:
            logger.warning("Pillow not available - cannot convert images to JPEG")
            return data
        
        if len(data) < 4:
            logger.warning("Image data too short")
            return data
        
        # Check image format by header/signature
        header = data[:12]
        
        # JPEG: starts with FF D8
        if data[0:2] == b'\xff\xd8':
            logger.info("Image is already JPEG format")
            return data
        
        # JP2 (JPEG 2000): starts with 00 00 00 0C 6A 50 20 20 (jP  )
        jp2_signature = b'\x00\x00\x00\x0cjP  '
        is_jp2 = data.startswith(jp2_signature)
        
        # TIFF: starts with 49 49 2A 00 (II*, little-endian) or 4D 4D 00 2A (MM, big-endian)
        is_tiff_le = data[0:4] == b'II*\x00'  # Little-endian TIFF
        is_tiff_be = data[0:4] == b'MM\x00*'  # Big-endian TIFF
        is_tiff = is_tiff_le or is_tiff_be
        
        if is_jp2:
            format_name = "JP2 (JPEG 2000)"
        elif is_tiff:
            format_name = "TIFF"
        else:
            # Try to open with Pillow anyway - it might recognize other formats
            format_name = f"Unknown (header: {header[:4].hex()})"
            logger.info(f"Image format: {format_name}, attempting conversion...")
        
        try:
            logger.info(f"Converting {format_name} image ({len(data)} bytes) to JPEG...")
            
            # Open image with Pillow (auto-detects format)
            img = Image.open(io.BytesIO(data))
            logger.info(f"Pillow detected format: {img.format}, mode: {img.mode}, size: {img.size}")
            
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                # Handle transparency by compositing on white background
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode == 'L':
                img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save as JPEG to bytes buffer
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=90)
            jpeg_data = output_buffer.getvalue()
            
            logger.info(f"Successfully converted {format_name} to JPEG ({len(jpeg_data)} bytes)")
            return jpeg_data
            
        except Exception as e:
            logger.error(f"Failed to convert image to JPEG: {e}")
            import traceback
            traceback.print_exc()
            # Return original data as fallback
            return data
    
    def _parse_all_tlv(self, data: bytes) -> Dict[int, bytes]:
        """
        Parse all TLV (Tag-Length-Value) entries from data.
        Returns dict mapping tag -> value.
        Per 在留カード等仕様書 Ver 1.5, text data uses TLV format.
        """
        result = {}
        i = 0
        while i < len(data):
            if i >= len(data):
                break
            
            # Get tag (1 byte)
            tag = data[i]
            i += 1
            
            if i >= len(data):
                break
            
            # Get length (1 or 3 bytes)
            length_byte = data[i]
            i += 1
            
            if length_byte == 0x81:
                # 1 byte extended length
                if i >= len(data):
                    break
                length = data[i]
                i += 1
            elif length_byte == 0x82:
                # 2 byte extended length
                if i + 1 >= len(data):
                    break
                length = (data[i] << 8) | data[i + 1]
                i += 2
            else:
                length = length_byte
            
            # Get value
            if i + length > len(data):
                break
            
            value = data[i:i + length]
            result[tag] = value
            i += length
        
        return result
    
    def _parse_address_data(self, data: bytes) -> Dict[str, str]:
        """
        Parse 住居地 (Address) from DF2/EF01.
        Per 在留カード等仕様書 Ver 1.5 Section 3.3.4.5:
        
        Tags in address file (DF2/EF01):
        - D2: 追記書き込み年月日 (Write date - YYYYMMDD)
        - D3: 市町村コード (City/municipality code)  
        - D4: 住居地 (Address text)
        
        Note: Personal info (name, nationality, status) is NOT in text files!
              It's only in DF1 images (front card image and photo).
        """
        fields = {}
        tlv_data = self._parse_all_tlv(data)
        
        logger.info(f"Parsed TLV tags from address data: {[f'0x{t:02X}' for t in tlv_data.keys()]}")
        
        # Field tag mapping per specification Section 3.3.4.5
        field_tags = {
            0xD2: ('address_write_date', '追記書き込み年月日'),
            0xD3: ('city_code', '市町村コード'),
            0xD4: ('address', '住居地'),
        }
        
        for tag, (field_key, field_label) in field_tags.items():
            if tag in tlv_data:
                raw_value = tlv_data[tag]
                # Check if value is all zeros (empty field)
                if all(b == 0 for b in raw_value):
                    logger.info(f"Tag 0x{tag:02X} ({field_label}): empty (all zeros)")
                    continue
                
                value = self._decode_text(raw_value)
                if value.strip() and value.strip('\x00'):
                    fields[field_key] = value.strip().strip('\x00')
                    logger.info(f"Tag 0x{tag:02X} ({field_label}): {value.strip()[:50]}...")
                else:
                    logger.info(f"Tag 0x{tag:02X} ({field_label}): empty after decode")
        
        return fields
    
    def _parse_endorsement_data(self, data: bytes) -> Optional[str]:
        """
        Parse 裏面追記欄 (Back endorsements) from DF2/EF02-04.
        Per 在留カード等仕様書 Ver 1.5 Section 3.3.4.6-8:
        
        Tags in endorsement files:
        - D5: 資格外活動許可 text (for EF02/03)
        - D6: 在留期間等更新申請 text (for EF04)
        """
        tlv_data = self._parse_all_tlv(data)
        
        logger.info(f"Parsed TLV tags from endorsement: {[f'0x{t:02X}' for t in tlv_data.keys()]}")
        
        # Try D5 first (most common), then D6
        for tag in [0xD5, 0xD6]:
            if tag in tlv_data:
                raw_value = tlv_data[tag]
                if all(b == 0 for b in raw_value):
                    continue
                value = self._decode_text(raw_value)
                if value.strip() and value.strip('\x00'):
                    return value.strip().strip('\x00')
        
        return None
    
    def read_text_data(self) -> Dict[str, Any]:
        """
        Read text data from DF2 - requires authentication.
        Per 在留カード等仕様書 Ver 1.5 Section 3.3.4:
        
        DF2 contains:
        - EF01: 住居地 (Address - back of card)
        - EF02: 裏面資格外活動包括許可欄 (General work permission endorsement)
        - EF03: 裏面資格外活動個別許可欄 (Specific work permission endorsement)
        - EF04: 裏面在留期間等更新申請欄 (Status update application endorsement)
        
        IMPORTANT: Personal info (name, nationality, status, DOB, gender) 
        is NOT in text files - it's ONLY in DF1 images!
        """
        result = {}
        
        logger.info("=" * 50)
        logger.info("Reading DF2 data (address and endorsements)...")
        logger.info("NOTE: Personal info is in DF1 images, not text files!")
        logger.info("=" * 50)
        
        if not self.select_df(self.AID_DF2):
            result["error"] = "Cannot select DF2"
            logger.error("Cannot select DF2")
            return result
        
        logger.info("DF2 selected successfully")
        
        # =========================================================
        # EF01: 住居地 (Address) - NOT "front text"!
        # Per spec 3.3.4.5: D2=write date, D3=city code, D4=address
        # =========================================================
        logger.info("Reading 住居地 (Address - DF2/EF01)...")
        address_data = self.read_binary_sm(self.EF_DF2_ADDRESS, 500)
        if address_data:
            result["address_raw"] = toHexString(list(address_data[:32])) + "..."
            logger.info(f"Address data read: {len(address_data)} bytes")
            
            try:
                parsed = self._parse_address_data(address_data)
                result.update(parsed)
                
                if 'address' in parsed:
                    logger.info(f"Address: {parsed['address'][:50]}...")
            except Exception as e:
                logger.warning(f"Error parsing address: {e}")
                # Try raw decode as fallback
                result["address"] = self._decode_text(address_data)
        else:
            logger.warning("Could not read address (DF2/EF01)")
        
        # =========================================================
        # EF02: 裏面資格外活動包括許可欄 (General work permission)
        # Per spec 3.3.4.6: D5=permission text
        # This is where "許可（原則週２８時間以内..." comes from
        # =========================================================
        logger.info("Reading 裏面資格外活動包括許可欄 (DF2/EF02)...")
        endorsement_1 = self.read_binary_sm(self.EF_DF2_ENDORSEMENT_1, 200)
        if endorsement_1:
            result["endorsement_1_raw"] = toHexString(list(endorsement_1[:32])) + "..."
            logger.info(f"Endorsement 1 read: {len(endorsement_1)} bytes")
            
            try:
                text = self._parse_endorsement_data(endorsement_1)
                if text:
                    result["work_permission_general"] = text
                    logger.info(f"General work permission: {text[:50]}...")
            except Exception as e:
                logger.warning(f"Error parsing endorsement 1: {e}")
        else:
            logger.info("No general work permission data (DF2/EF02)")
        
        # =========================================================
        # EF03: 裏面資格外活動個別許可欄 (Specific work permission)
        # Per spec 3.3.4.7
        # =========================================================
        logger.info("Reading 裏面資格外活動個別許可欄 (DF2/EF03)...")
        endorsement_2 = self.read_binary_sm(self.EF_DF2_ENDORSEMENT_2, 200)
        if endorsement_2:
            result["endorsement_2_raw"] = toHexString(list(endorsement_2[:32])) + "..."
            try:
                text = self._parse_endorsement_data(endorsement_2)
                if text:
                    result["work_permission_specific"] = text
                    logger.info(f"Specific work permission: {text[:50]}...")
            except Exception as e:
                logger.warning(f"Error parsing endorsement 2: {e}")
        else:
            logger.info("No specific work permission data (DF2/EF03)")
        
        # =========================================================
        # EF04: 裏面在留期間等更新申請欄 (Status update application)
        # Per spec 3.3.4.8
        # =========================================================
        logger.info("Reading 裏面在留期間等更新申請欄 (DF2/EF04)...")
        endorsement_3 = self.read_binary_sm(self.EF_DF2_ENDORSEMENT_3, 200)
        if endorsement_3:
            result["endorsement_3_raw"] = toHexString(list(endorsement_3[:32])) + "..."
            try:
                text = self._parse_endorsement_data(endorsement_3)
                if text:
                    result["status_update_application"] = text
                    logger.info(f"Status update application: {text[:50]}...")
            except Exception as e:
                logger.warning(f"Error parsing endorsement 3: {e}")
        else:
            logger.info("No status update application data (DF2/EF04)")
        
        # Add important note about where personal info is located
        result["personal_info_note"] = "氏名・国籍・在留資格などの個人情報はDF1の画像内にのみ存在します"
        
        return result
    
    def read_signature(self) -> Dict[str, Any]:
        """
        Read electronic signature (電子署名) - no SM required after auth.
        Returns check code and public key certificate.
        """
        result = {}
        
        if not self.select_df(self.AID_DF3):
            result["error"] = "Cannot select DF3"
            return result
        
        # Read signature file (plain read, no SM)
        data = self.read_binary_plain(self.EF_DF3_SIGNATURE, 2000)
        if data:
            result["signature_raw"] = toHexString(list(data[:64]))  # First 64 bytes preview
            result["signature_size"] = len(data)
            
            # Parse: DA 82 01 00 [checkcode 256] DB 82 04 B0 [certificate 1200]
            checkcode = self._parse_tlv_data(data, 0xDA)
            if checkcode:
                result["checkcode_size"] = len(checkcode)
            
            certificate = self._parse_tlv_data(data, 0xDB)
            if certificate:
                result["certificate_size"] = len(certificate)
                result["certificate_available"] = True
        
        return result
    
    def read_basic_info(self) -> Dict[str, Any]:
        """Read basic card information without authentication"""
        info = {}
        
        # Get UID
        logger.info("Reading basic info: Getting UID...")
        uid = self.get_uid()
        if uid:
            info['uid'] = uid
            logger.info(f"UID: {uid}")
        else:
            logger.warning("Could not get UID")
        
        # Get ATR
        try:
            atr = self.connection.getATR()
            if atr:
                info['atr'] = toHexString(atr)
                logger.info(f"ATR: {toHexString(atr)}")
        except Exception as e:
            logger.warning(f"Could not get ATR: {e}")
        
        # Select MF and read free access data
        logger.info("Selecting MF for basic info read...")
        if self.select_mf():
            info['mf_selected'] = True
            
            # Read card type (free access)
            card_type_info = self.read_card_type()
            info.update(card_type_info)
            
            # Read common data (free access)
            common_info = self.read_common_data()
            info.update(common_info)
            
            info['auth_hint'] = 'Card number only (12 characters)'
            info['auth_method'] = 'MUTUAL_AUTH + VERIFY'
        else:
            info['mf_selected'] = False
            info['error'] = 'Cannot select MF - may not be a Zairyu card'
        
        return info
    
    def read_all_data(self, card_number: str) -> Dict[str, Any]:
        """
        Read all data from Zairyu card with authentication.
        
        Args:
            card_number: 12-character card number (在留カード等番号)
                         e.g., "AB12345678CD"
        
        Returns:
            Dict with all card data including images (base64 encoded)
        """
        import base64
        
        result = {
            "timestamp": datetime.now().isoformat(),
            "card_number_input": card_number
        }
        
        # Step 1: Get basic info
        basic = self.read_basic_info()
        result.update(basic)
        
        # Step 2: Select MF for authentication
        logger.info("Step 2: Selecting MF for authentication...")
        if not self.select_mf():
            result["error"] = "Cannot select MF"
            result["hint"] = "Card may not be a Zairyu card or is not positioned correctly"
            return result
        
        logger.info("MF selected successfully")
        
        # Step 3: Mutual Authentication (using card number to derive keys)
        logger.info("Step 3: Starting mutual authentication...")
        if not self.mutual_authenticate(card_number):
            result["error"] = "Mutual authentication failed"
            result["hint"] = "Card may not support this protocol. Check server logs for details."
            result["mutual_auth"] = False
            return result
        
        result["mutual_auth"] = True
        logger.info("Mutual authentication successful!")
        
        # Step 4: Verify card number
        logger.info(f"Verifying card number: {card_number[:4]}****{card_number[-2:]}")
        if not self.verify_card_number(card_number):
            result["error"] = "Card number verification failed"
            result["hint"] = "Check that the card number is correct (12 characters, e.g., UH17622299ER)"
            result["authenticated"] = False
            return result
        
        result["authenticated"] = True
        
        # Step 5: Read all protected data
        
        # Read front image (stored as TIFF/JP2, convert to JPEG for browser)
        front_image = self.read_front_image()
        if front_image:
            result["front_image_size_original"] = len(front_image)
            # Convert to JPEG for browser compatibility (TIFF/JP2 not supported)
            front_image_jpeg = self._convert_image_to_jpeg(front_image)
            result["front_image_size"] = len(front_image_jpeg)
            result["front_image_base64"] = base64.b64encode(front_image_jpeg).decode('ascii')
            result["front_image_type"] = "image/jpeg"
        
        # Read photo (stored as JP2, convert to JPEG for browser)
        photo = self.read_photo()
        if photo:
            result["photo_size_original"] = len(photo)
            # Convert to JPEG for browser compatibility (JP2 not supported)
            photo_jpeg = self._convert_image_to_jpeg(photo)
            result["photo_size"] = len(photo_jpeg)
            result["photo_base64"] = base64.b64encode(photo_jpeg).decode('ascii')
            result["photo_type"] = "image/jpeg"
        
        # Read text data
        text_data = self.read_text_data()
        result.update(text_data)
        
        # Read signature
        signature = self.read_signature()
        result.update(signature)
        
        # OCR: Extract personal info from front card image
        # (Name, nationality, DOB, etc. are ONLY in the image, not in text files!)
        if front_image and EASYOCR_AVAILABLE:
            logger.info("Running OCR on front card image to extract personal info...")
            try:
                # Convert to JPEG first if needed for better OCR results
                jpeg_for_ocr = self._convert_image_to_jpeg(front_image)
                ocr_result = self.extract_text_from_image(jpeg_for_ocr)
                
                result["ocr_result"] = ocr_result
                
                # Copy parsed fields to top level for easy access
                if ocr_result.get("parsed_fields"):
                    for key, value in ocr_result["parsed_fields"].items():
                        # Prefix with 'ocr_' to distinguish from other sources
                        result[f"ocr_{key}"] = value
                    
                    logger.info(f"OCR extracted fields: {list(ocr_result['parsed_fields'].keys())}")
            except Exception as e:
                logger.error(f"OCR extraction failed: {e}")
                result["ocr_error"] = str(e)
        elif not EASYOCR_AVAILABLE:
            result["ocr_note"] = "EasyOCR not installed - install with: pip install easyocr"
        
        result["read_complete"] = True
        
        return result


# =============================================================================
# Main Bridge Server
# =============================================================================

class BridgeState(Enum):
    IDLE = "idle"
    WAITING_FOR_CARD = "waiting_for_card"
    READING = "reading"


class NFCBridge:
    def __init__(self):
        self.state = BridgeState.IDLE
        self.connected_clients: Set = set()
        self.scan_task: Optional[asyncio.Task] = None
        
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
            r = readers()
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
                card_data["uid"] = toHexString(data).replace(" ", "")
            else:
                card_data["uid_status"] = f"SW={sw1:02X}{sw2:02X}"
            
            # Method 2: Get ATR (Answer To Reset) - always available
            atr = conn.getATR()
            if atr:
                card_data["atr"] = toHexString(atr)
                # Parse ATR for card type hints
                atr_hex = toHexString(atr).replace(" ", "")
                if "80" in atr_hex:
                    card_data["protocol_hint"] = "T=0 or T=1"
            
            # Method 3: Try MRTD application (CCCD/ePassport)
            data, sw1, sw2 = conn.transmit(APDU.SELECT_MRTD_APP)
            if sw1 == 0x90:
                card_data["card_type"] = "ICAO 9303 (CCCD/ePassport)"
                card_data["mrtd_supported"] = True
            else:
                card_data["mrtd_status"] = f"SW={sw1:02X}{sw2:02X}"
                card_data["mrtd_supported"] = False
            
            # Method 4: Try to read any available data
            # SELECT MF (Master File)
            select_mf = [0x00, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00]
            data, sw1, sw2 = conn.transmit(select_mf)
            if sw1 == 0x90 or sw1 == 0x61:
                card_data["master_file"] = True
            
            # Determine card type from ATR
            if atr:
                atr_str = toHexString(atr).upper()
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
        """
        Read Vietnamese CCCD card with BAC authentication.
        
        Args:
            card_number: 12-digit card number
            birth_date: YYMMDD format
            expiry_date: YYMMDD format
        """
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
                card_data["atr"] = toHexString(atr)
            
            # Get UID
            data, sw1, sw2 = conn.transmit(APDU.GET_UID)
            if sw1 == 0x90:
                card_data["uid"] = toHexString(data).replace(" ", "")
            
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
                card_data["bac_error"] = "pycryptodome not installed - cannot perform BAC"
                card_data["install_hint"] = "pip install pycryptodome"
                conn.disconnect()
                return {"success": True, "data": card_data}
            
            # Perform BAC authentication
            rnd_ifd = os.urandom(8)  # Terminal random
            k_ifd = os.urandom(16)   # Terminal key material
            
            # Derive keys from MRZ data
            k_enc, k_mac = BACAuthentication.derive_keys(card_number, birth_date, expiry_date)
            
            # Build and encrypt authentication data
            # S = RND.IFD || RND.IC || K.IFD
            s = rnd_ifd + rnd_ic + k_ifd
            
            # Encrypt S
            e_ifd = BACAuthentication.encrypt_data(k_enc, s)
            
            # Compute MAC
            m_ifd = BACAuthentication.compute_mac(k_mac, e_ifd)
            
            # Build EXTERNAL AUTHENTICATE command
            # Format: CLA INS P1 P2 Lc Data [Le]
            # Some cards don't accept Le, try without first
            cmd_data = e_ifd + m_ifd  # 32 + 8 = 40 bytes
            
            # Try without Le first (Case 3)
            ext_auth = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data)
            
            data, sw1, sw2 = conn.transmit(ext_auth)
            
            # If wrong length, try with Le (Case 4)
            if sw1 == 0x67:
                card_data["note"] = "Trying alternative APDU format..."
                ext_auth_with_le = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data) + [0x28]
                data, sw1, sw2 = conn.transmit(ext_auth_with_le)
            
            # If still wrong length with specific value
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
            
            # Authentication successful!
            card_data["authenticated"] = True
            
            # Decrypt response and derive session keys
            response = bytes(data)
            e_ic = response[:32]
            m_ic = response[32:40]
            
            # Verify MAC
            computed_mac = BACAuthentication.compute_mac(k_mac, e_ic)
            if computed_mac != m_ic:
                card_data["mac_verify"] = "WARNING: MAC mismatch"
            
            # Decrypt response
            decrypted = BACAuthentication.decrypt_data(k_enc, e_ic)
            
            # Extract session key components
            # Response: RND.IC || RND.IFD || K.IC
            k_ic = decrypted[16:32]
            
            # Compute session keys
            key_seed = bytes(a ^ b for a, b in zip(k_ifd, k_ic))
            ks_enc = BACAuthentication.compute_key(key_seed, "ENC")
            ks_mac = BACAuthentication.compute_key(key_seed, "MAC")
            
            card_data["session_established"] = True
            
            # Now try to read data files using secure messaging
            # For now, try to read without secure messaging first (some cards allow this after auth)
            
            # Select EF.COM
            select_com = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x1E]
            data, sw1, sw2 = conn.transmit(select_com)
            if sw1 == 0x90 or sw1 == 0x61:
                # Read first bytes
                read_cmd = [0x00, 0xB0, 0x00, 0x00, 0x04]
                data, sw1, sw2 = conn.transmit(read_cmd)
                if sw1 == 0x90:
                    card_data["ef_com_header"] = toHexString(data)
            
            # Select EF.DG1 (MRZ data)
            select_dg1 = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x01]
            data, sw1, sw2 = conn.transmit(select_dg1)
            if sw1 == 0x90 or sw1 == 0x61:
                card_data["dg1_selected"] = True
                
                # Try to read DG1
                read_cmd = [0x00, 0xB0, 0x00, 0x00, 0x00]  # Read with max length
                data, sw1, sw2 = conn.transmit(read_cmd)
                
                if sw1 == 0x90:
                    card_data["dg1_raw"] = toHexString(data)
                    # Try to extract MRZ
                    try:
                        raw_bytes = bytes(data)
                        # Find MRZ data (usually starts after TLV header)
                        mrz_start = raw_bytes.find(b'\x5F\x1F')
                        if mrz_start >= 0:
                            length = raw_bytes[mrz_start + 2]
                            mrz_data = raw_bytes[mrz_start + 3:mrz_start + 3 + length]
                            card_data["mrz"] = mrz_data.decode('utf-8', errors='replace')
                    except:
                        pass
                elif sw1 == 0x6C:
                    # Wrong length, retry
                    read_cmd = [0x00, 0xB0, 0x00, 0x00, sw2]
                    data, sw1, sw2 = conn.transmit(read_cmd)
                    if sw1 == 0x90:
                        card_data["dg1_raw"] = toHexString(data)
                elif sw1 == 0x69 and sw2 == 0x88:
                    card_data["dg1_note"] = "Secure messaging required for full data access"
            
            # Select EF.DG11 (Additional personal details)
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
        """
        Read Japanese My Number Card (マイナンバーカード).
        
        Args:
            pin: 4-digit PIN for authentication (券面入力補助用PIN)
                 - Required to read 個人番号 (My Number)
                 - Required to read 基本4情報 (name, address, birthdate, gender)
        """
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
            
            # Get ATR
            atr = conn.getATR()
            if atr:
                card_data["atr"] = toHexString(atr)
            
            # Get UID
            data, sw1, sw2 = conn.transmit(APDU.GET_UID)
            if sw1 == 0x90:
                card_data["uid"] = toHexString(data).replace(" ", "")
            
            mynumber_reader = MyNumberCardReader(conn)
            
            # Read certificate info (no PIN required)
            basic_info = mynumber_reader.read_basic_info()
            card_data.update(basic_info)
            
            # If PIN provided, read personal info (My Number + Basic 4 Info)
            if pin and len(pin) == 4:
                logger.info("Reading personal info with PIN...")
                
                # Read personal info (My Number + Name/Address/Birthdate/Gender)
                personal_info = mynumber_reader.read_personal_info(pin)
                
                if "error" in personal_info:
                    card_data["personal_info_error"] = personal_info.get("error")
                    if "remaining_tries" in personal_info:
                        card_data["pin_remaining_tries"] = personal_info["remaining_tries"]
                    if "warning" in personal_info:
                        card_data["warning"] = personal_info["warning"]
                else:
                    # Add personal info to response
                    if "my_number" in personal_info:
                        card_data["my_number"] = personal_info["my_number"]
                    if "name" in personal_info:
                        card_data["name"] = personal_info["name"]
                    if "address" in personal_info:
                        card_data["address"] = personal_info["address"]
                    if "birthdate" in personal_info:
                        # Format birthdate nicely
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
        """
        Read Suica/Pasmo/ICOCA and other FeliCa transit IC cards.
        
        Args:
            use_nfcpy: If True, try nfcpy subprocess for full access (balance, history).
                      If False, use PC/SC (IDm only).
        """
        # Try nfcpy subprocess for full Suica access (balance, history)
        if use_nfcpy and NFCPY_AVAILABLE:
            logger.info("Attempting Suica read via nfcpy subprocess...")
            try:
                import subprocess
                import sys
                
                # Run suica_subprocess.py
                script_path = os.path.join(os.path.dirname(__file__), 'suica_subprocess.py')
                
                if os.path.exists(script_path):
                    # Use the same Python interpreter
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
                            logger.warning(f"Invalid JSON from subprocess: {result.stdout[:200]}")
                    
                    if result.stderr:
                        logger.info(f"Subprocess stderr: {result.stderr[:500]}")
                else:
                    logger.warning(f"suica_subprocess.py not found at {script_path}")
                    
            except subprocess.TimeoutExpired:
                logger.warning("Suica subprocess timed out")
            except Exception as e:
                logger.warning(f"nfcpy subprocess error: {e}")
        
        # Fallback to PC/SC (limited - IDm only)
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
            
            # Get ATR
            atr = conn.getATR()
            if atr:
                card_data["atr"] = toHexString(atr)
            
            # Try FeliCa reading (PC/SC - usually limited)
            suica_reader = SuicaReader(conn)
            result = suica_reader.read_card()
            card_data.update(result)
            
            # If FeliCa failed, try standard UID
            if "error" in result:
                data, sw1, sw2 = conn.transmit(APDU.GET_UID)
                if sw1 == 0x90:
                    card_data["uid"] = toHexString(data).replace(" ", "")
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
        """
        Read Japanese Zairyu (Residence) Card.
        Based on 在留カード等仕様書 Ver 1.5 (令和6年3月)
        
        Authentication: Card number only (12 characters)
        No PIN retry limit - card number is printed on the card.
        
        Args:
            card_number: 12-character card number (在留カード番号)
                         e.g., "AB12345678CD"
                         If empty, only reads basic info (free access data)
        
        Returns:
            Dict with card data including:
            - front_image_base64: Front card image (JPEG)
            - photo_base64: Face photo (JPEG)
            - text data: Name, nationality, status, address, etc.
            - signature: Electronic signature and certificate
        """
        if not SMARTCARD_AVAILABLE:
            import base64
            # Simulation mode
            return {
                "success": True,
                "data": {
                    "uid": "SIMULATED_ZAIRYU",
                    "card_type": "在留カード",
                    "card_type_en": "Residence Card",
                    "authenticated": True,
                    "simulated": True,
                    "card_number_input": card_number,
                    "front_text": "氏名: テスト 太郎\n国籍: ベトナム\n在留資格: 技術・人文知識・国際業務",
                    "address": "東京都渋谷区...",
                    "note": "Simulation mode - pyscard not installed"
                }
            }
        
        reader = self.get_reader()
        if not reader:
            return {"success": False, "error": "No reader found"}
        
        try:
            conn = reader.createConnection()
            conn.connect()
            
            zairyu_reader = ZairyuCardReader(conn)
            
            # If card number provided, read all data with authentication
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
                # Read only basic info (free access)
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
    
    async def api_read_mynumber(self, pin: str) -> Dict[str, Any]:
        """
        API endpoint for reading My Number card.
        Returns personal info or detailed error with instructions.
        
        Args:
            pin: 4-digit 券面入力補助用PIN
            
        Returns:
            Dict with success/error and data or instructions
        """
        # Step 1: Check if pyscard is available
        if not SMARTCARD_AVAILABLE:
            return {
                "success": False,
                "error": "NO_SMARTCARD_LIB",
                "error_ja": "スマートカードライブラリが利用できません",
                "error_en": "Smart card library not available",
                "instruction_ja": "pip install pyscard を実行してください",
                "instruction_en": "Please run: pip install pyscard"
            }
        
        # Step 2: Check if reader is connected
        reader = self.get_reader()
        if not reader:
            return {
                "success": False,
                "error": "NO_READER",
                "error_ja": "カードリーダーが接続されていません",
                "error_en": "No card reader connected",
                "instruction_ja": "NFCカードリーダーをUSBポートに接続してください",
                "instruction_en": "Please connect an NFC card reader to a USB port"
            }
        
        # Step 3: Check if card is present
        if not self.check_card_present():
            return {
                "success": False,
                "error": "NO_CARD",
                "error_ja": "カードが検出されません",
                "error_en": "No card detected on reader",
                "instruction_ja": "マイナンバーカードをカードリーダーの上に置いてください",
                "instruction_en": "Please place your My Number card on the reader",
                "reader": str(reader)
            }
        
        # Step 4: Validate PIN format
        if not pin:
            return {
                "success": False,
                "error": "NO_PIN",
                "error_ja": "PINが入力されていません",
                "error_en": "PIN is required",
                "instruction_ja": "4桁の券面入力補助用PINを入力してください",
                "instruction_en": "Please enter your 4-digit profile PIN"
            }
        
        if len(pin) != 4 or not pin.isdigit():
            return {
                "success": False,
                "error": "INVALID_PIN_FORMAT",
                "error_ja": "PINは4桁の数字である必要があります",
                "error_en": "PIN must be 4 digits",
                "instruction_ja": "市役所で設定した4桁の暗証番号を入力してください",
                "instruction_en": "Enter the 4-digit PIN you set at city hall"
            }
        
        # Step 5: Try to read the card
        try:
            conn = reader.createConnection()
            conn.connect()
            
            mynumber_reader = MyNumberCardReader(conn)
            
            # Read personal info (My Number + Basic 4 Info)
            logger.info("API: Reading My Number card personal info...")
            result = mynumber_reader.read_personal_info(pin)
            
            conn.disconnect()
            
            # Check for errors in result
            if "error" in result:
                error_msg = result.get("error", "")
                remaining = result.get("remaining_tries", -1)
                
                if "PIN verification failed" in error_msg:
                    if remaining == 0:
                        return {
                            "success": False,
                            "error": "CARD_LOCKED",
                            "error_ja": "カードがロックされています",
                            "error_en": "Card is locked due to too many wrong PIN attempts",
                            "instruction_ja": "市区町村役場でPINのリセットが必要です",
                            "instruction_en": "Visit your city hall to reset the PIN",
                            "remaining_tries": 0
                        }
                    else:
                        return {
                            "success": False,
                            "error": "WRONG_PIN",
                            "error_ja": f"PINが間違っています（残り{remaining}回）",
                            "error_en": f"Wrong PIN ({remaining} tries remaining)",
                            "instruction_ja": "正しい4桁の券面入力補助用PINを入力してください",
                            "instruction_en": "Please enter the correct 4-digit profile PIN",
                            "remaining_tries": remaining
                        }
                elif "Cannot select Profile AP" in error_msg:
                    return {
                        "success": False,
                        "error": "NOT_MYNUMBER_CARD",
                        "error_ja": "マイナンバーカードではありません",
                        "error_en": "This is not a My Number card",
                        "instruction_ja": "マイナンバーカードをカードリーダーに置いてください",
                        "instruction_en": "Please place your My Number card on the reader"
                    }
                else:
                    return {
                        "success": False,
                        "error": "READ_ERROR",
                        "error_ja": f"読み取りエラー: {error_msg}",
                        "error_en": f"Read error: {error_msg}",
                        "instruction_ja": "カードを置き直して再試行してください",
                        "instruction_en": "Please reposition the card and try again"
                    }
            
            # Success! Return personal info
            response = {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "reader": str(reader)
            }
            
            # Add personal info
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
            
            logger.info(f"API: Successfully read My Number card for {result.get('name', 'N/A')}")
            return response
            
        except NoCardException:
            return {
                "success": False,
                "error": "CARD_REMOVED",
                "error_ja": "カードが取り除かれました",
                "error_en": "Card was removed during reading",
                "instruction_ja": "カードをリーダーの上に置いたままにしてください",
                "instruction_en": "Keep the card on the reader during the entire process"
            }
        except CardConnectionException as e:
            return {
                "success": False,
                "error": "CONNECTION_ERROR",
                "error_ja": "カードとの通信エラー",
                "error_en": "Communication error with card",
                "instruction_ja": "カードを置き直して再試行してください",
                "instruction_en": "Please reposition the card and try again",
                "detail": str(e)
            }
        except Exception as e:
            logger.error(f"API read_mynumber error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": "UNKNOWN_ERROR",
                "error_ja": f"予期しないエラー: {str(e)}",
                "error_en": f"Unexpected error: {str(e)}",
                "instruction_ja": "サーバーログを確認してください",
                "instruction_en": "Check the server logs for details"
            }
    
    async def api_read_zairyu(self, card_number: str) -> Dict[str, Any]:
        """
        API endpoint for reading Zairyu (Residence) Card.
        Based on 在留カード等仕様書 Ver 1.5 (令和6年3月)
        
        Authentication: Card number only (12 characters)
        No retry limit - card number is printed on the card.
        
        Args:
            card_number: 12-character card number (在留カード等番号)
                         e.g., "AB12345678CD"
        
        Returns:
            Dict with success/error and data including:
            - front_image_base64: Front card image (JPEG)
            - photo_base64: Face photo (JPEG) 
            - text data: Name, nationality, status, address, etc.
        """
        # Step 1: Check if pyscard is available
        if not SMARTCARD_AVAILABLE:
            return {
                "success": False,
                "error": "NO_SMARTCARD_LIB",
                "error_ja": "スマートカードライブラリが利用できません",
                "error_en": "Smart card library not available",
                "instruction_ja": "pip install pyscard を実行してください",
                "instruction_en": "Please run: pip install pyscard"
            }
        
        # Step 2: Check if reader is connected
        reader = self.get_reader()
        if not reader:
            return {
                "success": False,
                "error": "NO_READER",
                "error_ja": "カードリーダーが接続されていません",
                "error_en": "No card reader connected",
                "instruction_ja": "NFCカードリーダーをUSBポートに接続してください",
                "instruction_en": "Please connect an NFC card reader to a USB port"
            }
        
        # Step 3: Check if card is present
        if not self.check_card_present():
            return {
                "success": False,
                "error": "NO_CARD",
                "error_ja": "カードが検出されません",
                "error_en": "No card detected on reader",
                "instruction_ja": "在留カードをカードリーダーの上に置いてください",
                "instruction_en": "Please place your Residence Card on the reader",
                "reader": str(reader)
            }
        
        # Step 4: Validate card number format
        if not card_number:
            return {
                "success": False,
                "error": "NO_CARD_NUMBER",
                "error_ja": "在留カード番号が入力されていません",
                "error_en": "Card number is required",
                "instruction_ja": "12桁の在留カード番号を入力してください",
                "instruction_en": "Please enter your 12-character card number"
            }
        
        if len(card_number) != 12:
            return {
                "success": False,
                "error": "INVALID_CARD_NUMBER_FORMAT",
                "error_ja": "在留カード番号は12桁である必要があります",
                "error_en": "Card number must be 12 characters",
                "instruction_ja": "カード表面に記載されている12桁の番号を入力してください",
                "instruction_en": "Enter the 12-character number printed on your card",
                "hint": "Example: AB12345678CD"
            }
        
        # Step 5: Try to read the card
        try:
            conn = reader.createConnection()
            conn.connect()
            
            zairyu_reader = ZairyuCardReader(conn)
            
            logger.info(f"API: Reading Zairyu card with number {card_number[:4]}****{card_number[-2:]}")
            
            # Log ATR for debugging
            try:
                atr = conn.getATR()
                if atr:
                    logger.info(f"Card ATR: {toHexString(atr)}")
            except Exception as e:
                logger.warning(f"Could not get ATR: {e}")
            
            result = zairyu_reader.read_all_data(card_number)
            
            conn.disconnect()
            
            # Check for errors in result
            if "error" in result:
                error_msg = result.get("error", "")
                
                if "Mutual authentication failed" in error_msg:
                    return {
                        "success": False,
                        "error": "AUTH_FAILED",
                        "error_ja": "カードとの相互認証に失敗しました",
                        "error_en": "Failed mutual authentication with card",
                        "instruction_ja": "カードが正しく置かれているか確認してください。在留カードでない可能性もあります。",
                        "instruction_en": "Please ensure the card is properly positioned. This may not be a valid Residence Card.",
                        "hint": result.get("hint", "Check server logs for details")
                    }
                elif "Card number verification failed" in error_msg:
                    return {
                        "success": False,
                        "error": "WRONG_CARD_NUMBER",
                        "error_ja": "在留カード番号が一致しません",
                        "error_en": "Card number does not match",
                        "instruction_ja": "カード表面に記載されている正しい番号を入力してください",
                        "instruction_en": "Please enter the correct number printed on your card"
                    }
                elif "Cannot select MF" in error_msg:
                    return {
                        "success": False,
                        "error": "NOT_ZAIRYU_CARD",
                        "error_ja": "在留カードではありません",
                        "error_en": "This is not a Residence Card",
                        "instruction_ja": "在留カードをカードリーダーに置いてください",
                        "instruction_en": "Please place your Residence Card on the reader"
                    }
                else:
                    return {
                        "success": False,
                        "error": "READ_ERROR",
                        "error_ja": f"読み取りエラー: {error_msg}",
                        "error_en": f"Read error: {error_msg}",
                        "instruction_ja": "カードを置き直して再試行してください",
                        "instruction_en": "Please reposition the card and try again"
                    }
            
            # Success! Return all data
            response = {
                "success": True,
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
                "error_en": "Card was removed during reading",
                "instruction_ja": "カードをリーダーの上に置いたままにしてください",
                "instruction_en": "Keep the card on the reader during the entire process"
            }
        except CardConnectionException as e:
            return {
                "success": False,
                "error": "CONNECTION_ERROR",
                "error_ja": "カードとの通信エラー",
                "error_en": "Communication error with card",
                "instruction_ja": "カードを置き直して再試行してください",
                "instruction_en": "Please reposition the card and try again",
                "detail": str(e)
            }
        except Exception as e:
            logger.error(f"API read_zairyu error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": "UNKNOWN_ERROR",
                "error_ja": f"予期しないエラー: {str(e)}",
                "error_en": f"Unexpected error: {str(e)}",
                "instruction_ja": "サーバーログを確認してください",
                "instruction_en": "Check the server logs for details"
            }
    
    async def api_test_ocr(self, image_base64: str, filename: str = "uploaded") -> Dict[str, Any]:
        """
        API endpoint for testing OCR on an uploaded image.
        No card needed - just upload an image and run OCR.
        
        Args:
            image_base64: Base64 encoded image data
            filename: Original filename (for logging)
        
        Returns:
            Dict with OCR results including extracted fields
        """
        logger.info(f"API: Testing OCR on uploaded image: {filename}")
        
        # Check if EasyOCR is available
        if not EASYOCR_AVAILABLE:
            return {
                "success": False,
                "error": "OCR_NOT_AVAILABLE",
                "error_ja": "EasyOCRがインストールされていません",
                "error_en": "EasyOCR is not installed",
                "instruction_ja": "pip install easyocr を実行してください",
                "instruction_en": "Please run: pip install easyocr"
            }
        
        if not image_base64:
            return {
                "success": False,
                "error": "NO_IMAGE",
                "error_ja": "画像データがありません",
                "error_en": "No image data provided"
            }
        
        try:
            # Decode base64 to bytes
            import base64
            image_data = base64.b64decode(image_base64)
            logger.info(f"Decoded image: {len(image_data)} bytes")
            
            # Create a temporary ZairyuCardReader to use its OCR methods
            # (We don't need a real card connection for OCR testing)
            class OCRTester:
                def __init__(self):
                    pass
                
                def _get_ocr_reader(self):
                    global _ocr_reader
                    if _ocr_reader is None:
                        logger.info("Initializing EasyOCR reader...")
                        _ocr_reader = easyocr.Reader(['ja', 'en'], gpu=False)
                        logger.info("EasyOCR reader initialized")
                    return _ocr_reader
            
            ocr_tester = OCRTester()
            reader = ocr_tester._get_ocr_reader()
            
            if not reader:
                return {
                    "success": False,
                    "error": "OCR_INIT_FAILED",
                    "error_ja": "OCRリーダーの初期化に失敗しました",
                    "error_en": "Failed to initialize OCR reader"
                }
            
            # Convert image to numpy array
            img = Image.open(io.BytesIO(image_data))
            img_array = np.array(img)
            logger.info(f"Image size: {img.size}, mode: {img.mode}")
            
            # Run OCR
            logger.info("Running OCR...")
            ocr_results = reader.readtext(img_array)
            
            # Extract all text
            all_text = []
            for (bbox, text, confidence) in ocr_results:
                all_text.append({
                    "text": text,
                    "confidence": round(confidence, 3)
                })
                logger.info(f"OCR: '{text}' (conf: {confidence:.2f})")
            
            # Parse structured fields
            parsed_fields = self._parse_ocr_for_zairyu(ocr_results)
            
            logger.info(f"OCR extracted {len(all_text)} text regions")
            logger.info(f"Parsed fields: {list(parsed_fields.keys())}")
            
            return {
                "success": True,
                "filename": filename,
                "image_size": len(image_data),
                "ocr_result": {
                    "ocr_success": True,
                    "raw_text": all_text,
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
    
    def _parse_ocr_for_zairyu(self, ocr_results: list) -> Dict[str, str]:
        """
        Parse OCR results by grouping text into visual lines.
        Uses Spatial Analysis - optimized for Zairyu Card layout.
        Same logic as ZairyuCardReader._parse_ocr_results
        """
        parsed = {}

        # ---------------------------------------------------------
        # 1. HELPER: Group blocks into lines based on Y-coordinate
        # ---------------------------------------------------------
        sorted_blocks = sorted(ocr_results, key=lambda x: x[0][0][1])
        
        lines = []
        if sorted_blocks:
            current_line = [sorted_blocks[0]]
            current_y = sorted_blocks[0][0][0][1]
            
            for block in sorted_blocks[1:]:
                y = block[0][0][1]
                if abs(y - current_y) < 20:
                    current_line.append(block)
                else:
                    current_line.sort(key=lambda x: x[0][0][0])
                    lines.append(current_line)
                    current_line = [block]
                    current_y = y
            
            current_line.sort(key=lambda x: x[0][0][0])
            lines.append(current_line)

        text_lines = []
        for line in lines:
            line_text = " ".join([b[1] for b in line])
            text_lines.append(line_text)
            logger.info(f"OCR Line: {line_text}")

        full_text = " ".join(text_lines)

        # ---------------------------------------------------------
        # 2. HELPER: Fix Japanese Date Typos
        # ---------------------------------------------------------
        def fix_date_typo(date_str):
            if not date_str:
                return None
            if re.match(r'.+\d{1,2}月$', date_str) and date_str.count('月') > 1:
                return date_str[:-1] + "日"
            return date_str

        # --- A. Card Number ---
        card_num_match = re.search(r'([A-Z]{2}\d{8}[A-Z]{2})', full_text.replace(" ", ""))
        if card_num_match:
            parsed["card_number"] = card_num_match.group(1)

        # --- B. Name ---
        for line in text_lines:
            clean_line = line.strip()
            check_content = clean_line.replace(" ", "")
            
            if parsed.get("card_number") and check_content.upper() == parsed["card_number"]:
                continue
            if re.search(r'\d', check_content):
                continue
            # Skip Japanese characters
            if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', check_content):
                continue
            
            check_upper = check_content.upper()
            if (check_content.isalpha() and 
                len(check_content) > 3 and 
                "VALIDITY" not in check_upper and 
                "PERIOD" not in check_upper and
                "CARD" not in check_upper and
                "FERICD" not in check_upper and
                "STUDENT" not in check_upper and
                "SRUDENT" not in check_upper):
                parsed["name"] = clean_line.upper()
                break

        # --- C. Date of Birth, Gender, Nationality ---
        dob_pattern = r'(\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?[日月])'
        
        for line in text_lines:
            dob_match = re.search(dob_pattern, line)
            if dob_match:
                raw_dob = dob_match.group(1).replace(" ", "")
                raw_dob = fix_date_typo(raw_dob)
                if raw_dob:
                    parsed["date_of_birth"] = raw_dob.replace("年", "-").replace("月", "-").replace("日", "")
                
                if '女' in line or 'F.' in line:
                    parsed["gender"] = "女"
                elif '男' in line or 'M.' in line:
                    parsed["gender"] = "男"
                
                nationalities = [
                    'ベトナム', 'ヴェトナム', '中国', '韓国', 'フィリピン',
                    'インドネシア', 'ネパール', 'ミャンマー', 'タイ', 'スリランカ',
                ]
                for nationality in nationalities:
                    if nationality in line:
                        parsed["nationality"] = nationality
                        break
                break

        # --- D. Period of Stay & Expiration ---
        # Use STRICT regex to extract actual date inside parens, ignoring garbage
        period_pattern = r'(\d+\s?年(?:\s?\d+\s?月)?)\s*[（\(].*?(\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?[日月]).*?[）\)]'
        
        found_period = False
        for line in text_lines:
            match = re.search(period_pattern, line)
            if match:
                duration = match.group(1).replace(" ", "")
                expiry_raw = match.group(2).replace(" ", "")
                expiry_raw = fix_date_typo(expiry_raw)
                
                parsed["period_of_stay"] = f"{duration} ({expiry_raw}まで)"
                parsed["expiration_date"] = expiry_raw
                found_period = True
                break
        
        # Fallback if strict regex failed (underlined text in parens is often corrupted)
        if not found_period:
            # Just extract duration - don't append corrupted underlined date
            dur_match = re.search(r'(?<!\d)(\d{1,2}年(?:\d{1,2}月)?)(?!\d)', full_text)
            if dur_match:
                parsed["period_of_stay"] = dur_match.group(1)
        
        # Try to get expiration from "まで有効" line at bottom (usually readable)
        if "expiration_date" not in parsed:
            valid_match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)まで有効', full_text)
            if valid_match:
                parsed["expiration_date"] = valid_match.group(1)

        # --- E. Status ---
        known_statuses = [
            '留学', '技能実習', '技術・人文知識・国際業務', '家族滞在',
            '永住者', '定住者', '特定技能',
        ]
        for line in text_lines:
            for status in known_statuses:
                if status in line:
                    parsed["status_of_residence"] = status
                    break
            if "status_of_residence" in parsed:
                break

        # --- F. Address ---
        address_pattern = r'(?:東京都|北海道|京都府|大阪府|.{2,3}県).+?(?:市|区|町|村).+'
        for line in text_lines:
            if re.search(address_pattern, line) and not re.search(r'\d{4}年', line):
                parsed["address"] = line.strip()
                break

        # --- G. Work Restrictions ---
        if '就労不可' in full_text:
            parsed["work_permission"] = "就労不可"
        elif '就労制限なし' in full_text:
            parsed["work_permission"] = "就労制限なし"
        elif '指定書' in full_text:
            parsed["work_permission"] = "指定書により指定"

        # --- H. Valid Until (Fallback) ---
        if "expiration_date" not in parsed:
            valid_pattern = r'(\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?[日月])\s*まで'
            valid_match = re.search(valid_pattern, full_text)
            if valid_match:
                exp = valid_match.group(1).replace(" ", "")
                exp = fix_date_typo(exp)
                parsed["expiration_date"] = exp

        logger.info(f"Final Parsed Data: {parsed}")
        return parsed

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
                
                # Read based on card type
                if card_type == "cccd":
                    result = self.read_cccd_card(
                        params.get('card_number', ''),
                        params.get('birth_date', ''),
                        params.get('expiry_date', '')
                    )
                elif card_type == "zairyu":
                    # Zairyu card only needs card number (12 chars)
                    result = self.read_zairyu_card(
                        params.get('card_number', '')
                    )
                elif card_type == "mynumber":
                    result = self.read_mynumber_card(
                        params.get('pin', '')
                    )
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
                # Cancel existing scan
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
                # Immediately read card without waiting
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
                    # Zairyu card only needs card number (12 chars)
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
                # Dedicated API for reading My Number card with PIN
                # Returns personal info or detailed error messages
                result = await self.api_read_mynumber(data.get("pin", ""))
                await websocket.send(json.dumps({
                    "type": "mynumber_result",
                    **result
                }))
            
            elif msg_type == "read_zairyu":
                # Dedicated API for reading Zairyu (Residence) Card
                # Only needs card number (12 chars) - NO PIN, NO DOB, NO EXPIRY
                # Returns all data: front image, photo, text, signature
                result = await self.api_read_zairyu(data.get("card_number", ""))
                await websocket.send(json.dumps({
                    "type": "zairyu_result",
                    **result
                }))
            
            elif msg_type == "test_ocr":
                # Test OCR on an uploaded image (no card needed)
                result = await self.api_test_ocr(
                    data.get("image_base64", ""),
                    data.get("filename", "uploaded_image")
                )
                await websocket.send(json.dumps({
                    "type": "ocr_result",
                    **result
                }))
            
            elif msg_type == "get_status":
                reader = self.get_reader()
                await websocket.send(json.dumps({
                    "type": "status_response",
                    "state": self.state.value,
                    "reader_available": reader is not None,
                    "reader_name": str(reader) if reader else None,
                    "card_present": self.check_card_present()
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
            "version": "2.1.0",
            "zairyu_auth": "card_number_only"  # Per 在留カード等仕様書 Ver 1.5
        }))
        
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connected_clients.discard(websocket)
            logger.info(f"Client disconnected. Total: {len(self.connected_clients)}")


async def main():
    bridge = NFCBridge()
    
    print("=" * 60)
    print("  NFC Bridge Server v2.1.0")
    print("  Supports: CCCD, Zairyu (在留カード), My Number, Suica")
    print("  Zairyu: Card number only (per 在留カード等仕様書 Ver 1.5)")
    print("=" * 60)
    print(f"  URL    : ws://{HOST}:{PORT}")
    print(f"  Reader : {bridge.get_reader() or 'Not detected'}")
    print(f"  Status : {'Ready' if SMARTCARD_AVAILABLE else 'Simulation mode'}")
    print("=" * 60)
    print()
    
    async with websockets.serve(bridge.handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
