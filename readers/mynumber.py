"""
Japanese My Number Card (マイナンバーカード) reader.
Uses JPKI (Japanese Public Key Infrastructure).
"""

import logging
from typing import Optional, List, Dict, Any, Tuple

from .utils import get_hex_string, SMARTCARD_AVAILABLE

if SMARTCARD_AVAILABLE:
    from smartcard.util import toHexString

logger = logging.getLogger(__name__)


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
    
    # Manifest positions for Basic 4 Info parsing
    NAME_SEGMENT_PTR = 7
    ADDRESS_SEGMENT_PTR = 9
    BIRTHDATE_SEGMENT_PTR = 11
    GENDER_SEGMENT_PTR = 13
    
    def __init__(self, connection):
        self.connection = connection
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        data, sw1, sw2 = self.connection.transmit(apdu)
        logger.debug(f"APDU: {get_hex_string(apdu)} -> SW={sw1:02X}{sw2:02X}")
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
    
    def verify_pin(self, pin: str) -> Tuple[bool, int]:
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
    
    def get_remaining_tries(self) -> Tuple[int, str]:
        """Get remaining PIN tries without consuming a try."""
        verify_cmd = [0x00, 0x20, 0x00, 0x80]
        data, sw1, sw2 = self.send_apdu(verify_cmd)
        
        if sw1 == 0x63 and (sw2 & 0xC0) == 0xC0:
            return sw2 & 0x0F, "OK"
        elif sw1 == 0x69 and sw2 == 0x84:
            return 0, "LOCKED"
        elif sw1 == 0x90:
            return -1, "Already authenticated"
        else:
            return -1, f"Unknown status: {sw1:02X}{sw2:02X}"
    
    def read_binary_long(self, max_length: int = 4096) -> Optional[bytes]:
        """Read binary data with extended length support"""
        result = bytearray()
        offset = 0
        
        while offset < max_length:
            read_len = min(256, max_length - offset)
            p1 = (offset >> 8) & 0x7F
            p2 = offset & 0xFF
            read_cmd = [0x00, 0xB0, p1, p2, read_len if read_len < 256 else 0x00]
            data, sw1, sw2 = self.send_apdu(read_cmd)
            
            if sw1 == 0x90:
                result.extend(data)
                if len(data) < read_len:
                    break
                offset += len(data)
            elif sw1 == 0x6C:
                read_cmd = [0x00, 0xB0, p1, p2, sw2]
                data, sw1, sw2 = self.send_apdu(read_cmd)
                if sw1 == 0x90:
                    result.extend(data)
                break
            elif sw1 == 0x6B:
                break
            else:
                break
        
        return bytes(result) if result else None
    
    def parse_certificate_info(self, cert_data: bytes) -> Dict[str, Any]:
        """Parse basic info from X.509 certificate DER data"""
        info = {}
        try:
            hex_data = cert_data.hex()
            cn_oid = "550403"
            cn_pos = hex_data.find(cn_oid)
            if cn_pos > 0:
                pos = cn_pos + 6
                type_byte = int(hex_data[pos:pos+2], 16)
                pos += 2
                length = int(hex_data[pos:pos+2], 16)
                pos += 2
                if length < 128:
                    cn_bytes = bytes.fromhex(hex_data[pos:pos+length*2])
                    info["certificate_cn"] = cn_bytes.decode('utf-8', errors='replace')
            
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
        return data.decode("cp932", errors="replace")
    
    def _parse_attr(self, data: List[int], segment_start: int) -> str:
        """Parse an attribute from the basic 4 info data."""
        try:
            attr_length = data[segment_start + 2]
            attr_start = segment_start + 3
            attr_data = data[attr_start:attr_start + attr_length]
            return self._decode_japanese_text(bytes(attr_data))
        except Exception as e:
            logger.error(f"Error parsing attribute at {segment_start}: {e}")
            return ""
    
    def read_my_number(self, profile_pin: str) -> Dict[str, Any]:
        """Read マイナンバー (個人番号) from the card."""
        result = {}
        
        if not self.select_application(self.AID_PROFILE_AP):
            result["error"] = "Cannot select Profile AP"
            return result
        
        if not self.select_ef(self.EF_PROFILE_PIN):
            result["error"] = "Cannot select Profile PIN file"
            return result
        
        success, remaining = self.verify_pin(profile_pin)
        if not success:
            result["error"] = f"PIN verification failed"
            result["remaining_tries"] = remaining
            if remaining == 0:
                result["warning"] = "⚠️ カードがロックされています"
            return result
        
        if not self.select_ef(self.EF_MY_NUMBER):
            result["error"] = "Cannot select My Number file"
            return result
        
        data = self.read_binary(16)
        if data:
            my_number = ''.join([chr(b) for b in data[3:15]])
            result["my_number"] = my_number
            logger.info(f"Read My Number: {my_number[:4]}****{my_number[-4:]}")
        else:
            result["error"] = "Cannot read My Number data"
        
        return result
    
    def read_basic_4_info(self, profile_pin: str) -> Dict[str, Any]:
        """Read 基本4情報 (name, address, birthdate, gender) from the card."""
        result = {}
        
        if not self.select_application(self.AID_PROFILE_AP):
            result["error"] = "Cannot select Profile AP"
            return result
        
        if not self.select_ef(self.EF_PROFILE_PIN):
            result["error"] = "Cannot select Profile PIN file"
            return result
        
        success, remaining = self.verify_pin(profile_pin)
        if not success:
            result["error"] = f"PIN verification failed"
            result["remaining_tries"] = remaining
            if remaining == 0:
                result["warning"] = "⚠️ カードがロックされています"
            return result
        
        if not self.select_ef(self.EF_BASIC_4_INFO):
            result["error"] = "Cannot select Basic 4 Info file"
            return result
        
        data = self.read_binary(0)
        if not data:
            result["error"] = "Cannot read Basic 4 Info data"
            return result
        
        data_list = list(data)
        
        try:
            name_ptr = data_list[self.NAME_SEGMENT_PTR]
            address_ptr = data_list[self.ADDRESS_SEGMENT_PTR]
            birthdate_ptr = data_list[self.BIRTHDATE_SEGMENT_PTR]
            gender_ptr = data_list[self.GENDER_SEGMENT_PTR]
            
            result["name"] = self._parse_attr(data_list, name_ptr)
            result["address"] = self._parse_attr(data_list, address_ptr)
            result["birthdate"] = self._parse_attr(data_list, birthdate_ptr)
            
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
        """Read both My Number and Basic 4 Info in one call."""
        result = {}
        
        my_number_result = self.read_my_number(profile_pin)
        if "error" in my_number_result:
            return my_number_result
        result.update(my_number_result)
        
        basic_info_result = self.read_basic_4_info(profile_pin)
        if "error" in basic_info_result:
            result["basic_info_error"] = basic_info_result.get("error")
        else:
            result.update(basic_info_result)
        
        return result
    
    def read_basic_info(self) -> Dict[str, Any]:
        """Read card info without PIN"""
        info = {}
        
        if self.select_application(self.AID_CARD_INFO):
            info["card_info_available"] = True
            
            if self.select_ef([0x00, 0x06]):
                data = self.read_binary(20)
                if data:
                    info["card_serial"] = get_hex_string(list(data))
            
            if self.select_ef([0x00, 0x11]):
                data = self.read_binary(8)
                if data:
                    try:
                        expiry_str = data.decode('ascii').strip()
                        info["card_expiry"] = expiry_str
                    except:
                        info["card_expiry_raw"] = get_hex_string(list(data))
        
        if self.select_application(self.AID_JPKI_AP):
            info["jpki_auth_available"] = True
            
            if self.select_ef([0x00, 0x18]):
                remaining, status = self.get_remaining_tries()
                info["auth_pin_remaining_tries"] = remaining
                info["auth_pin_status"] = status
                if remaining == 0:
                    info["auth_pin_warning"] = "⚠️ LOCKED - Visit city hall to reset"
                elif 0 < remaining <= 2:
                    info["auth_pin_warning"] = f"⚠️ Only {remaining} tries left!"
            
            if self.select_ef([0x00, 0x0A]):
                cert_data = self.read_binary_long(2048)
                if cert_data and len(cert_data) > 0:
                    cert_info = self.parse_certificate_info(cert_data)
                    info.update(cert_info)
                    info["auth_cert_preview"] = get_hex_string(list(cert_data[:32]))
            
            if self.select_ef([0x00, 0x0B]):
                ca_data = self.read_binary_long(2048)
                if ca_data and len(ca_data) > 0:
                    info["ca_cert_size"] = len(ca_data)
                    info["ca_cert_available"] = True
        
        if self.select_application(self.AID_JPKI_SIGN):
            info["jpki_sign_available"] = True
            
            if self.select_ef([0x00, 0x1B]):
                remaining, status = self.get_remaining_tries()
                info["sign_pin_remaining_tries"] = remaining
                info["sign_pin_status"] = status
                if remaining == 0:
                    info["sign_pin_warning"] = "⚠️ LOCKED"
        
        return info
