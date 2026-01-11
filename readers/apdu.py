"""
APDU Commands for NFC card communication.
"""

from typing import List


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
