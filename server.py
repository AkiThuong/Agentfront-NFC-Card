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
# Zairyu Card Reader (在留カード)
# =============================================================================

class ZairyuCardReader:
    """
    Japanese Residence Card (在留カード) reader.
    Uses ICAO 9303 standard similar to e-Passport.
    MRZ-based BAC authentication.
    """
    
    def __init__(self, connection):
        self.connection = connection
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        data, sw1, sw2 = self.connection.transmit(apdu)
        return data, sw1, sw2
    
    def select_mrtd_application(self) -> bool:
        """Select the MRTD application (same as e-Passport/CCCD)"""
        data, sw1, sw2 = self.send_apdu(APDU.SELECT_MRTD_APP)
        return sw1 == 0x90 and sw2 == 0x00
    
    def get_uid(self) -> Optional[str]:
        """Get card UID"""
        data, sw1, sw2 = self.send_apdu(APDU.GET_UID)
        if sw1 == 0x90:
            return toHexString(data).replace(" ", "")
        return None
    
    def read_basic_info(self) -> Dict[str, Any]:
        """Read basic card information without authentication"""
        info = {}
        
        # Get UID
        uid = self.get_uid()
        if uid:
            info['uid'] = uid
        
        # Get ATR
        try:
            atr = self.connection.getATR()
            if atr:
                info['atr'] = toHexString(atr)
        except:
            pass
        
        # Try MRTD application
        if self.select_mrtd_application():
            info['mrtd_supported'] = True
            info['card_type'] = '在留カード (Zairyu Card)'
            info['note'] = 'BAC authentication required for personal data'
            info['auth_hint'] = 'Card number + Birth date (YYMMDD) + Expiry date (YYMMDD)'
        else:
            info['mrtd_supported'] = False
            info['card_type'] = 'Unknown'
        
        return info
    
    def read_with_auth(self, card_number: str, birth_date: str, expiry_date: str) -> Dict[str, Any]:
        """
        Read Zairyu card with BAC authentication.
        Uses same method as CCCD since both use ICAO 9303.
        
        Args:
            card_number: Card number (様式'在留'の番号 - usually on the card)
            birth_date: YYMMDD format
            expiry_date: YYMMDD format (有効期限)
        """
        # Zairyu card uses ICAO 9303 same as CCCD
        # Reuse CCCD authentication logic
        info = self.read_basic_info()
        
        if not info.get('mrtd_supported'):
            info['error'] = 'Not an ICAO 9303 card'
            return info
        
        # Get challenge
        data, sw1, sw2 = self.send_apdu(APDU.GET_CHALLENGE)
        if sw1 != 0x90:
            info['error'] = f'Cannot get challenge: SW={sw1:02X}{sw2:02X}'
            return info
        
        info['challenge_received'] = True
        rnd_ic = bytes(data)
        
        if not CRYPTO_AVAILABLE:
            info['error'] = 'pycryptodome required for BAC authentication'
            return info
        
        # Perform BAC (same as CCCD)
        rnd_ifd = os.urandom(8)
        k_ifd = os.urandom(16)
        
        k_enc, k_mac = BACAuthentication.derive_keys(card_number, birth_date, expiry_date)
        
        s = rnd_ifd + rnd_ic + k_ifd
        e_ifd = BACAuthentication.encrypt_data(k_enc, s)
        m_ifd = BACAuthentication.compute_mac(k_mac, e_ifd)
        
        cmd_data = e_ifd + m_ifd
        ext_auth = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data)
        
        data, sw1, sw2 = self.send_apdu(ext_auth)
        
        if sw1 == 0x67:
            ext_auth_with_le = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data) + [0x28]
            data, sw1, sw2 = self.send_apdu(ext_auth_with_le)
        
        if sw1 == 0x6C:
            ext_auth_correct = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + list(cmd_data) + [sw2]
            data, sw1, sw2 = self.send_apdu(ext_auth_correct)
        
        if sw1 != 0x90:
            info['authenticated'] = False
            info['auth_error'] = f'SW={sw1:02X}{sw2:02X}'
            info['hint'] = 'Check card number, birth date, and expiry date format'
            return info
        
        info['authenticated'] = True
        
        # Try to read DG1 (MRZ data)
        select_dg1 = [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x01]
        data, sw1, sw2 = self.send_apdu(select_dg1)
        if sw1 == 0x90 or sw1 == 0x61:
            info['dg1_available'] = True
            
            # Read DG1
            read_cmd = [0x00, 0xB0, 0x00, 0x00, 0x00]
            data, sw1, sw2 = self.send_apdu(read_cmd)
            
            if sw1 == 0x90:
                info['dg1_raw'] = toHexString(data)
                try:
                    # Try to extract MRZ
                    raw_bytes = bytes(data)
                    mrz_start = raw_bytes.find(b'\x5F\x1F')
                    if mrz_start >= 0:
                        length = raw_bytes[mrz_start + 2]
                        mrz_data = raw_bytes[mrz_start + 3:mrz_start + 3 + length]
                        info['mrz'] = mrz_data.decode('utf-8', errors='replace')
                except:
                    pass
            elif sw1 == 0x6C:
                read_cmd = [0x00, 0xB0, 0x00, 0x00, sw2]
                data, sw1, sw2 = self.send_apdu(read_cmd)
                if sw1 == 0x90:
                    info['dg1_raw'] = toHexString(data)
            elif sw1 == 0x69 and sw2 == 0x88:
                info['dg1_note'] = 'Secure messaging required'
        
        return info


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
    
    def read_zairyu_card(self, card_number: str = "", birth_date: str = "", expiry_date: str = "") -> Dict[str, Any]:
        """
        Read Japanese Zairyu (Residence) Card.
        Uses ICAO 9303 BAC authentication if credentials provided.
        
        Args:
            card_number: Card number (在留カード番号)
            birth_date: YYMMDD format
            expiry_date: YYMMDD format
        """
        if not SMARTCARD_AVAILABLE:
            return {
                "success": True,
                "data": {
                    "uid": "SIMULATED_ZAIRYU",
                    "card_type": "在留カード (Simulated)",
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
            
            # Get ATR
            atr = conn.getATR()
            if atr:
                card_data["atr"] = toHexString(atr)
            
            # Get UID
            data, sw1, sw2 = conn.transmit(APDU.GET_UID)
            if sw1 == 0x90:
                card_data["uid"] = toHexString(data).replace(" ", "")
            
            zairyu_reader = ZairyuCardReader(conn)
            
            # If credentials provided, try full authentication
            if card_number and birth_date and expiry_date:
                result = zairyu_reader.read_with_auth(card_number, birth_date, expiry_date)
            else:
                result = zairyu_reader.read_basic_info()
            
            card_data.update(result)
            
            conn.disconnect()
            return {"success": True, "data": card_data}
            
        except NoCardException:
            return {"success": False, "error": "No card on reader"}
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
                    result = self.read_zairyu_card(
                        params.get('card_number', ''),
                        params.get('birth_date', ''),
                        params.get('expiry_date', '')
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
                    result = self.read_zairyu_card(
                        params['card_number'],
                        params['birth_date'],
                        params['expiry_date']
                    )
                elif card_type == "mynumber":
                    result = self.read_mynumber_card(params['pin'])
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
            "version": "2.0.0"
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
    print("  NFC Bridge Server v2.1")
    print("  Supports: CCCD (Vietnam), My Number (Japan), Generic")
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
