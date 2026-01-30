"""
Japanese Residence Card (在留カード) reader.
Based on 在留カード等仕様書 Ver 1.5 (令和6年3月) - Immigration Services Agency

Authentication: Card number only (12 characters)
Protocol: SELECT MF → GET CHALLENGE → MUTUAL AUTH → VERIFY(card#) → READ
"""

import base64
import hashlib
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from .utils import get_hex_string, CRYPTO_AVAILABLE, PILLOW_AVAILABLE

if CRYPTO_AVAILABLE:
    from Crypto.Cipher import DES3, DES

if PILLOW_AVAILABLE:
    from PIL import Image
    import io

logger = logging.getLogger(__name__)


class ZairyuCardReader:
    """
    Japanese Residence Card (在留カード) reader.
    Based on 在留カード等仕様書 Ver 1.5 (令和6年3月) - Immigration Services Agency
    
    Authentication: Card number only (12 characters)
    No PIN retry limit - uses card number printed on card.
    """
    
    # AIDs from official specification (Section 3.3.2)
    AID_MF = []
    AID_DF1 = [0xD3, 0x92, 0xF0, 0x00, 0x4F, 0x02, 0x00, 0x00, 
               0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    AID_DF2 = [0xD3, 0x92, 0xF0, 0x00, 0x4F, 0x03, 0x00, 0x00,
               0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    AID_DF3 = [0xD3, 0x92, 0xF0, 0x00, 0x4F, 0x04, 0x00, 0x00,
               0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    
    # EF Short IDs
    EF_MF_COMMON = 0x01
    EF_MF_CARD_TYPE = 0x02
    EF_DF1_FRONT_IMAGE = 0x05
    EF_DF1_PHOTO = 0x06
    EF_DF2_ADDRESS = 0x01
    EF_DF2_ENDORSEMENT_1 = 0x02
    EF_DF2_ENDORSEMENT_2 = 0x03
    EF_DF2_ENDORSEMENT_3 = 0x04
    EF_DF3_SIGNATURE = 0x02
    
    # Critical fields that should be present in a valid OCR result
    CRITICAL_FIELDS = ['name', 'nationality', 'date_of_birth']
    
    def __init__(self, connection, ocr_provider=None, fallback_ocr_provider=None):
        """
        Initialize Zairyu card reader.
        
        Args:
            connection: Smart card connection
            ocr_provider: Primary OCR provider for text extraction from images
            fallback_ocr_provider: Fallback OCR provider when primary misses fields
        """
        self.connection = connection
        self.ks_enc = None
        self.authenticated = False
        self.ocr_provider = ocr_provider
        self.fallback_ocr_provider = fallback_ocr_provider
    
    def set_ocr_provider(self, provider):
        """Set OCR provider for text extraction"""
        self.ocr_provider = provider
    
    def set_fallback_ocr_provider(self, provider):
        """Set fallback OCR provider for when primary misses fields"""
        self.fallback_ocr_provider = provider
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        """Send APDU and return response"""
        try:
            data, sw1, sw2 = self.connection.transmit(apdu)
            if apdu[1] in [0xA4, 0x84, 0x82, 0x20]:
                logger.info(f"APDU TX: {get_hex_string(apdu)}")
                logger.info(f"APDU RX: data={get_hex_string(data) if data else 'empty'}, SW={sw1:02X}{sw2:02X}")
            else:
                logger.debug(f"APDU: {get_hex_string(apdu)} -> SW={sw1:02X}{sw2:02X}")
            return data, sw1, sw2
        except Exception as e:
            logger.error(f"APDU transmit error: {e}")
            raise
    
    def get_uid(self) -> Optional[str]:
        """Get card UID"""
        from .apdu import APDU
        data, sw1, sw2 = self.send_apdu(APDU.GET_UID)
        if sw1 == 0x90:
            return get_hex_string(data).replace(" ", "")
        return None
    
    def select_mf(self) -> bool:
        """Select Master File (MF)."""
        cmd = [0x00, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00]
        logger.info(f"SELECT MF (by File ID 3F00): {get_hex_string(cmd)}")
        data, sw1, sw2 = self.send_apdu(cmd)
        logger.info(f"SELECT MF response: SW={sw1:02X}{sw2:02X}")
        if sw1 != 0x90:
            logger.error(f"SELECT MF failed with SW={sw1:02X}{sw2:02X}")
        return sw1 == 0x90
    
    def select_df(self, aid: List[int]) -> bool:
        """Select Dedicated File by AID"""
        cmd = [0x00, 0xA4, 0x04, 0x0C, len(aid)] + aid
        logger.info(f"SELECT DF: AID={get_hex_string(aid[:8])}...")
        data, sw1, sw2 = self.send_apdu(cmd)
        if sw1 == 0x90:
            logger.info("DF selected successfully")
            return True
        else:
            logger.error(f"SELECT DF failed: SW={sw1:02X}{sw2:02X}")
            return False
    
    def get_challenge(self) -> Optional[bytes]:
        """Get 8-byte challenge from card"""
        cmd = [0x00, 0x84, 0x00, 0x00, 0x08]
        logger.info(f"GET CHALLENGE: {get_hex_string(cmd)}")
        data, sw1, sw2 = self.send_apdu(cmd)
        logger.info(f"GET CHALLENGE response: SW={sw1:02X}{sw2:02X}, data_len={len(data)}")
        if data:
            logger.info(f"GET CHALLENGE data: {get_hex_string(data)}")
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
        """Compute Retail MAC (ISO 9797-1 Algorithm 3)."""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome required")
        
        padded = self._pad_data(data)
        ka = key[:8]
        kb = key[8:16]
        
        h = bytes(8)
        cipher_a = DES.new(ka, DES.MODE_ECB)
        for i in range(0, len(padded), 8):
            block = padded[i:i+8]
            xored = bytes(a ^ b for a, b in zip(h, block))
            h = cipher_a.encrypt(xored)
        
        cipher_b = DES.new(kb, DES.MODE_ECB)
        h = cipher_b.decrypt(h)
        h = cipher_a.encrypt(h)
        
        return h
    
    def _tdes_ede_block(self, k1: bytes, k2: bytes, block: bytes, encrypt: bool = True) -> bytes:
        """Single block 3DES-EDE2 operation."""
        cipher_k1 = DES.new(k1, DES.MODE_ECB)
        cipher_k2 = DES.new(k2, DES.MODE_ECB)
        
        if encrypt:
            step1 = cipher_k1.encrypt(block)
            step2 = cipher_k2.decrypt(step1)
            step3 = cipher_k1.encrypt(step2)
            return step3
        else:
            step1 = cipher_k1.decrypt(block)
            step2 = cipher_k2.encrypt(step1)
            step3 = cipher_k1.decrypt(step2)
            return step3
    
    def _tdes_encrypt(self, key: bytes, data: bytes) -> bytes:
        """3DES-EDE2 CBC encrypt with zero IV."""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome required")
        
        k1 = key[:8]
        k2 = key[8:16]
        
        iv = bytes(8)
        result = bytearray()
        prev_block = iv
        
        for i in range(0, len(data), 8):
            block = data[i:i+8]
            xored = bytes(a ^ b for a, b in zip(block, prev_block))
            encrypted = self._tdes_ede_block(k1, k2, xored, encrypt=True)
            result.extend(encrypted)
            prev_block = encrypted
        
        return bytes(result)
    
    def _tdes_decrypt(self, key: bytes, data: bytes) -> bytes:
        """3DES-EDE2 CBC decrypt with zero IV."""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome required")
        
        k1 = key[:8]
        k2 = key[8:16]
        
        iv = bytes(8)
        result = bytearray()
        prev_block = iv
        
        for i in range(0, len(data), 8):
            block = data[i:i+8]
            decrypted = self._tdes_ede_block(k1, k2, block, encrypt=False)
            xored = bytes(a ^ b for a, b in zip(decrypted, prev_block))
            result.extend(xored)
            prev_block = block
        
        return bytes(result)
    
    def _compute_session_key(self, key_material: bytes) -> bytes:
        """Compute session key from key material."""
        d = key_material + bytes([0x00, 0x00, 0x00, 0x01])
        h = hashlib.sha1(d).digest()
        
        key = bytearray(h[:16])
        for i in range(16):
            b = key[i]
            parity = bin(b).count('1') % 2
            if parity == 0:
                key[i] ^= 1
        
        return bytes(key)
    
    def _derive_auth_keys(self, card_number: str) -> tuple:
        """Derive Kenc and Kmac from card number for Mutual Authentication."""
        if len(card_number) != 12:
            raise ValueError("Card number must be 12 characters")
        
        h = hashlib.sha1(card_number.encode('ascii')).digest()
        key = h[:16]
        
        logger.info(f"Derived key from card number: {get_hex_string(list(key))}")
        
        return key, key
    
    def mutual_authenticate(self, card_number: str) -> bool:
        """Perform Mutual Authentication to establish session key."""
        if not CRYPTO_AVAILABLE:
            logger.error("pycryptodome required for mutual authentication")
            return False
        
        k_enc, k_mac = self._derive_auth_keys(card_number)
        
        logger.info(f"K_ENC for auth: {get_hex_string(list(k_enc))}")
        logger.info(f"K_MAC for auth: {get_hex_string(list(k_mac))}")
        
        logger.info("Mutual Auth Step 1: Getting challenge from card...")
        rnd_icc = self.get_challenge()
        if not rnd_icc:
            logger.error("Failed to get challenge from card")
            return False
        
        logger.info(f"RND.ICC (8 bytes): {get_hex_string(list(rnd_icc))}")
        
        rnd_ifd = os.urandom(8)
        k_ifd = os.urandom(16)
        
        logger.info(f"RND.IFD: {get_hex_string(list(rnd_ifd))}")
        logger.info(f"K.IFD: {get_hex_string(list(k_ifd))}")
        
        s = rnd_ifd + rnd_icc + k_ifd
        
        e_ifd = self._tdes_encrypt(k_enc, s)
        m_ifd = self._compute_retail_mac(k_mac, e_ifd)
        
        logger.info(f"E_IFD: {get_hex_string(list(e_ifd))}")
        logger.info(f"M_IFD: {get_hex_string(list(m_ifd))}")
        
        cmd_data = list(e_ifd) + list(m_ifd)
        cmd = [0x00, 0x82, 0x00, 0x00, len(cmd_data)] + cmd_data + [0x00]
        
        logger.info(f"MUTUAL AUTH cmd length: {len(cmd_data)}")
        
        data, sw1, sw2 = self.send_apdu(cmd)
        
        if sw1 != 0x90:
            logger.error(f"MUTUAL AUTHENTICATE failed: SW={sw1:02X}{sw2:02X}")
            return False
        
        if len(data) != 40:
            logger.error(f"Invalid response length: {len(data)} (expected 40)")
            return False
        
        e_icc = bytes(data[:32])
        m_icc = bytes(data[32:40])
        
        logger.info(f"E_ICC: {get_hex_string(list(e_icc))}")
        logger.info(f"M_ICC: {get_hex_string(list(m_icc))}")
        
        computed_mac = self._compute_retail_mac(k_mac, e_icc)
        if computed_mac != m_icc:
            logger.error("MAC verification failed")
            return False
        
        decrypted = self._tdes_decrypt(k_enc, e_icc)
        
        logger.info(f"Decrypted ({len(decrypted)} bytes): {get_hex_string(list(decrypted))}")
        
        if len(decrypted) != 32:
            logger.error(f"Invalid decrypted length: {len(decrypted)} (expected 32)")
            return False
        
        rnd_icc_resp = decrypted[:8]
        rnd_ifd_resp = decrypted[8:16]
        k_icc = decrypted[16:32]
        
        if rnd_icc_resp != rnd_icc:
            logger.error(f"RND.ICC mismatch!")
            return False
        
        if rnd_ifd_resp != rnd_ifd:
            logger.error(f"RND.IFD mismatch!")
            return False
        
        logger.info("RND values verified successfully")
        
        key_material = bytes(a ^ b for a, b in zip(k_ifd, k_icc))
        logger.info(f"Key material (K.IFD XOR K.ICC): {get_hex_string(list(key_material))}")
        
        self.ks_enc = self._compute_session_key(key_material)
        
        logger.info(f"Session key KSenc established: {get_hex_string(list(self.ks_enc))}")
        
        return True
    
    def verify_card_number(self, card_number: str) -> bool:
        """Verify card number (在留カード等番号による認証)."""
        if not self.ks_enc:
            logger.error("Session key not established")
            return False
        
        if len(card_number) != 12:
            logger.error(f"Invalid card number length: {len(card_number)} (expected 12)")
            return False
        
        card_bytes = card_number.encode('ascii')
        card_padded = self._pad_data(card_bytes)
        
        logger.info(f"Card number padded: {get_hex_string(list(card_padded))}")
        
        encrypted_card = self._tdes_encrypt(self.ks_enc, card_padded)
        
        logger.info(f"Encrypted card#: {get_hex_string(list(encrypted_card))}")
        
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
        """Read binary data with Secure Messaging."""
        if not self.ks_enc or not self.authenticated:
            logger.error("Not authenticated")
            return None
        
        all_data = bytearray()
        offset = 0
        
        logger.info(f"Reading EF {ef_id:02X} with SM...")
        
        while offset < max_length:
            if offset == 0:
                p1 = 0x80 | ef_id
                p2 = 0x00
            else:
                p1 = (offset >> 8) & 0x7F
                p2 = offset & 0xFF
            
            chunk_size = min(256, max_length - offset)
            sm_data = [0x96, 0x02, (chunk_size >> 8) & 0xFF, chunk_size & 0xFF]
            
            cmd = [0x08, 0xB0, p1, p2, 0x00, 0x00, len(sm_data)] + sm_data + [0x00, 0x00]
            
            data, sw1, sw2 = self.send_apdu(cmd)
            
            if sw1 != 0x90:
                if offset == 0:
                    logger.error(f"READ BINARY EF{ef_id:02X} failed: SW={sw1:02X}{sw2:02X}")
                    return None
                else:
                    logger.info(f"READ BINARY EF{ef_id:02X} ended at offset {offset}")
                    break
            
            if len(data) < 4:
                logger.warning(f"Response too short: {len(data)} bytes")
                break
            
            if data[0] != 0x86:
                logger.warning(f"Unexpected tag: {data[0]:02X} (expected 86)")
                break
            
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
            
            enc_content = bytes(data[idx:idx+data_len])
            
            if len(enc_content) > 0 and enc_content[0] == 0x01:
                enc_data = enc_content[1:]
            else:
                enc_data = enc_content
            
            if len(enc_data) % 8 != 0:
                padding_needed = 8 - (len(enc_data) % 8)
                enc_data = enc_data + bytes(padding_needed)
            
            decrypted = self._tdes_decrypt(self.ks_enc, enc_data)
            decrypted = self._unpad_data(decrypted)
            
            all_data.extend(decrypted)
            offset += len(decrypted)
            
            if len(decrypted) < chunk_size:
                logger.info(f"EF{ef_id:02X} read complete: {len(all_data)} bytes total")
                break
        
        return bytes(all_data) if all_data else None
    
    def read_binary_plain(self, ef_id: int, max_length: int = 256) -> Optional[bytes]:
        """Read binary without SM (for free access files)"""
        all_data = bytearray()
        offset = 0
        
        while offset < max_length:
            p1 = 0x80 | ef_id if offset == 0 else (offset >> 8) & 0x7F
            p2 = 0x00 if offset == 0 else offset & 0xFF
            
            cmd = [0x00, 0xB0, p1, p2, 0x00]
            data, sw1, sw2 = self.send_apdu(cmd)
            
            if sw1 == 0x6C:
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
        """Read common data (共通データ要素) - no authentication required."""
        result = {}
        
        if not self.select_mf():
            result["error"] = "Cannot select MF"
            return result
        
        data = self.read_binary_plain(self.EF_MF_COMMON)
        if data:
            result["common_data_raw"] = get_hex_string(list(data))
            result["common_data_available"] = True
        
        return result
    
    def read_card_type(self) -> Dict[str, Any]:
        """Read card type (カード種別) - no authentication required."""
        result = {}
        
        if not self.select_mf():
            result["error"] = "Cannot select MF"
            return result
        
        data = self.read_binary_plain(self.EF_MF_CARD_TYPE)
        if data:
            result["card_type_raw"] = get_hex_string(list(data))
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
        """Read front card image (券面(表)イメージ) - requires authentication."""
        logger.info("Reading 券面(表)イメージ from DF1/EF05...")
        
        if not self.select_df(self.AID_DF1):
            logger.error("Cannot select DF1 for front image")
            return None
        
        logger.info("DF1 selected for front image")
        data = self.read_binary_sm(self.EF_DF1_FRONT_IMAGE, 8000)
        
        if data:
            logger.info(f"Front image raw data: {len(data)} bytes")
            jpeg = self._parse_tlv_data(data, 0xD0)
            if jpeg:
                logger.info(f"Front image JPEG extracted: {len(jpeg)} bytes")
                if len(jpeg) >= 2 and jpeg[0] == 0xFF and jpeg[1] == 0xD8:
                    logger.info("Front image is standard JPEG format")
                else:
                    # TIFF format is normal for Zairyu cards - will be converted later
                    logger.info("Front image is TIFF format (will be auto-converted to JPEG)")
                return jpeg
            else:
                logger.warning("Could not extract JPEG from TLV (tag D0)")
                return data
        else:
            logger.warning("Could not read front image data")
        
        return None
    
    def read_photo(self) -> Optional[bytes]:
        """Read face photo (顔写真) - requires authentication."""
        logger.info("Reading 顔写真 from DF1/EF06...")
        
        if not self.select_df(self.AID_DF1):
            logger.error("Cannot select DF1 for photo")
            return None
        
        logger.info("DF1 selected for photo")
        data = self.read_binary_sm(self.EF_DF1_PHOTO, 4000)
        
        if data:
            logger.info(f"Photo raw data: {len(data)} bytes")
            jpeg = self._parse_tlv_data(data, 0xD1)
            if jpeg:
                logger.info(f"Photo JPEG extracted: {len(jpeg)} bytes")
                if len(jpeg) >= 2 and jpeg[0] == 0xFF and jpeg[1] == 0xD8:
                    logger.info("Photo is standard JPEG format")
                else:
                    # JPEG 2000 format is normal for Zairyu cards - will be converted later
                    logger.info("Photo is JP2 format (will be auto-converted to JPEG)")
                return jpeg
            else:
                logger.warning("Could not extract JPEG from TLV (tag D1)")
                return data
        else:
            logger.warning("Could not read photo data")
        
        return None
    
    def _decode_text(self, data: bytes) -> str:
        """Decode text data trying multiple Japanese encodings."""
        for encoding in ['cp932', 'shift-jis', 'utf-8', 'euc-jp', 'iso-2022-jp']:
            try:
                decoded = data.decode(encoding)
                if '\ufffd' not in decoded:
                    return decoded
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode('cp932', errors='replace')
    
    def _convert_image_to_jpeg(self, data: bytes) -> bytes:
        """Convert various image formats to standard JPEG."""
        if not PILLOW_AVAILABLE:
            logger.warning("Pillow not available - cannot convert images")
            return data
        
        if len(data) < 4:
            return data
        
        if data[0:2] == b'\xff\xd8':
            logger.info("Image is already JPEG format")
            return data
        
        jp2_signature = b'\x00\x00\x00\x0cjP  '
        is_jp2 = data.startswith(jp2_signature)
        is_tiff_le = data[0:4] == b'II*\x00'
        is_tiff_be = data[0:4] == b'MM\x00*'
        is_tiff = is_tiff_le or is_tiff_be
        
        if is_jp2:
            format_name = "JP2 (JPEG 2000)"
        elif is_tiff:
            format_name = "TIFF"
        else:
            format_name = f"Unknown (header: {data[:4].hex()})"
        
        try:
            logger.info(f"Converting {format_name} image ({len(data)} bytes) to JPEG...")
            
            img = Image.open(io.BytesIO(data))
            logger.info(f"Pillow detected format: {img.format}, mode: {img.mode}, size: {img.size}")
            
            if img.mode in ('RGBA', 'LA', 'P'):
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode == 'L':
                img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=90)
            jpeg_data = output_buffer.getvalue()
            
            logger.info(f"Successfully converted to JPEG ({len(jpeg_data)} bytes)")
            return jpeg_data
            
        except Exception as e:
            logger.error(f"Failed to convert image to JPEG: {e}")
            return data
    
    def read_basic_info(self) -> Dict[str, Any]:
        """Read basic card information without authentication"""
        info = {}
        
        logger.info("Reading basic info: Getting UID...")
        uid = self.get_uid()
        if uid:
            info['uid'] = uid
            logger.info(f"UID: {uid}")
        
        try:
            atr = self.connection.getATR()
            if atr:
                info['atr'] = get_hex_string(atr)
                logger.info(f"ATR: {get_hex_string(atr)}")
        except Exception as e:
            logger.warning(f"Could not get ATR: {e}")
        
        logger.info("Selecting MF for basic info read...")
        if self.select_mf():
            info['mf_selected'] = True
            
            card_type_info = self.read_card_type()
            info.update(card_type_info)
            
            common_info = self.read_common_data()
            info.update(common_info)
            
            info['auth_hint'] = 'Card number only (12 characters)'
            info['auth_method'] = 'MUTUAL_AUTH + VERIFY'
        else:
            info['mf_selected'] = False
            info['error'] = 'Cannot select MF - may not be a Zairyu card'
        
        return info
    
    def extract_text_from_image(self, image_data: bytes) -> Dict[str, Any]:
        """
        Extract text from card image using OCR provider.
        
        Uses fallback OCR when critical fields are missing from primary OCR.
        """
        if not self.ocr_provider:
            return {
                "ocr_available": False,
                "error": "No OCR provider configured"
            }
        
        # Import parser here to avoid circular imports
        from ocr.parser import ZairyuCardParser
        parser = ZairyuCardParser()
        
        # Try primary OCR
        primary_result = self.ocr_provider.process_image(image_data)
        
        if not primary_result.success:
            return {
                "ocr_available": True,
                "ocr_success": False,
                "error": primary_result.error
            }
        
        parsed_fields = parser.parse(primary_result)
        primary_provider = getattr(self.ocr_provider, 'name', 'primary')
        
        # Check for missing critical fields
        missing_fields = [f for f in self.CRITICAL_FIELDS if f not in parsed_fields]
        
        if missing_fields and self.fallback_ocr_provider:
            logger.warning(f"Primary OCR ({primary_provider}) missing fields: {missing_fields}")
            logger.info("Trying fallback OCR to fill missing fields...")
            
            try:
                # Run fallback OCR
                fallback_result = self.fallback_ocr_provider.process_image(image_data)
                fallback_provider = getattr(self.fallback_ocr_provider, 'name', 'fallback')
                
                if fallback_result.success:
                    fallback_parsed = parser.parse(fallback_result)
                    
                    # Merge: fill in missing fields from fallback
                    fields_filled = []
                    for field in missing_fields:
                        if field in fallback_parsed:
                            parsed_fields[field] = fallback_parsed[field]
                            fields_filled.append(field)
                    
                    if fields_filled:
                        logger.info(f"Fallback OCR ({fallback_provider}) filled fields: {fields_filled}")
                        parsed_fields["_fallback_fields"] = fields_filled
                        parsed_fields["_fallback_provider"] = fallback_provider
                    else:
                        logger.warning(f"Fallback OCR ({fallback_provider}) also missing: {missing_fields}")
                else:
                    logger.warning(f"Fallback OCR failed: {fallback_result.error}")
                    
            except Exception as e:
                logger.error(f"Fallback OCR error: {e}")
        elif missing_fields:
            logger.warning(f"Missing fields {missing_fields} but no fallback OCR configured")
        
        return {
            "ocr_available": True,
            "ocr_success": True,
            "raw_text": primary_result.raw_text,
            "parsed_fields": parsed_fields,
            "primary_provider": primary_provider
        }
    
    def read_all_data(self, card_number: str) -> Dict[str, Any]:
        """Read all data from Zairyu card with authentication."""
        result = {
            "timestamp": datetime.now().isoformat(),
            "card_number_input": card_number
        }
        
        basic = self.read_basic_info()
        result.update(basic)
        
        logger.info("Step 2: Selecting MF for authentication...")
        if not self.select_mf():
            result["error"] = "Cannot select MF"
            result["hint"] = "Card may not be a Zairyu card or is not positioned correctly"
            return result
        
        logger.info("MF selected successfully")
        
        logger.info("Step 3: Starting mutual authentication...")
        if not self.mutual_authenticate(card_number):
            result["error"] = "Mutual authentication failed"
            result["hint"] = "Card may not support this protocol. Check server logs for details."
            result["mutual_auth"] = False
            return result
        
        result["mutual_auth"] = True
        logger.info("Mutual authentication successful!")
        
        logger.info(f"Verifying card number: {card_number[:4]}****{card_number[-2:]}")
        if not self.verify_card_number(card_number):
            result["error"] = "Card number verification failed"
            result["hint"] = "Check that the card number is correct (12 characters)"
            result["authenticated"] = False
            return result
        
        result["authenticated"] = True
        
        # === PHOTO SAVING (enabled for debugging) ===
        # Prepare photo save directory
        photo_save_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "photo", "zairyuu")
        try:
            os.makedirs(photo_save_dir, exist_ok=True)
            logger.info(f"Photo save directory: {photo_save_dir}")
        except Exception as e:
            logger.warning(f"Could not create photo directory: {e}")
            photo_save_dir = None
        
        # Generate timestamp for unique filenames
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Use masked card number for filename (privacy)
        card_id = f"{card_number[:4]}XXXX{card_number[-2:]}"
        # === END PHOTO SAVING SETUP ===
        
        # Read front image
        front_image = self.read_front_image()
        if front_image:
            result["front_image_size_original"] = len(front_image)
            front_image_jpeg = self._convert_image_to_jpeg(front_image)
            result["front_image_size"] = len(front_image_jpeg)
            result["front_image_base64"] = base64.b64encode(front_image_jpeg).decode('ascii')
            result["front_image_type"] = "image/jpeg"
            
            # === PHOTO SAVING (enabled for debugging) ===
            # Save front image to disk
            if photo_save_dir:
                try:
                    front_filename = f"{card_id}_{timestamp_str}_front.jpg"
                    front_path = os.path.join(photo_save_dir, front_filename)
                    with open(front_path, 'wb') as f:
                        f.write(front_image_jpeg)
                    result["front_image_saved"] = front_path
                    logger.info(f"Saved front image: {front_path}")
                except Exception as e:
                    logger.warning(f"Could not save front image: {e}")
            # === END PHOTO SAVING ===
        
        # Read photo
        photo = self.read_photo()
        if photo:
            result["photo_size_original"] = len(photo)
            photo_jpeg = self._convert_image_to_jpeg(photo)
            result["photo_size"] = len(photo_jpeg)
            result["photo_base64"] = base64.b64encode(photo_jpeg).decode('ascii')
            result["photo_type"] = "image/jpeg"
            
            # === PHOTO SAVING (enabled for debugging) ===
            # Save face photo to disk
            if photo_save_dir:
                try:
                    photo_filename = f"{card_id}_{timestamp_str}_photo.jpg"
                    photo_path = os.path.join(photo_save_dir, photo_filename)
                    with open(photo_path, 'wb') as f:
                        f.write(photo_jpeg)
                    result["photo_saved"] = photo_path
                    logger.info(f"Saved face photo: {photo_path}")
                except Exception as e:
                    logger.warning(f"Could not save face photo: {e}")
            # === END PHOTO SAVING ===
        
        # OCR: Extract personal info from front card image
        if front_image and self.ocr_provider:
            logger.info("Running OCR on front card image to extract personal info...")
            try:
                jpeg_for_ocr = self._convert_image_to_jpeg(front_image)
                ocr_result = self.extract_text_from_image(jpeg_for_ocr)
                
                result["ocr_result"] = ocr_result
                
                if ocr_result.get("parsed_fields"):
                    for key, value in ocr_result["parsed_fields"].items():
                        result[f"ocr_{key}"] = value
                    
                    logger.info(f"OCR extracted fields: {list(ocr_result['parsed_fields'].keys())}")
            except Exception as e:
                logger.error(f"OCR extraction failed: {e}")
                result["ocr_error"] = str(e)
        elif not self.ocr_provider:
            result["ocr_note"] = "No OCR provider configured"
        
        result["read_complete"] = True
        
        return result
