"""
Vietnamese CCCD (Căn cước công dân) card reader.
"""

import logging
from typing import Optional, List, Dict, Any

from .apdu import APDU
from .utils import get_hex_string, SMARTCARD_AVAILABLE

if SMARTCARD_AVAILABLE:
    from smartcard.util import toHexString

logger = logging.getLogger(__name__)


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
            return get_hex_string(data).replace(" ", "")
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
