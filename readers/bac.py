"""
BAC (Basic Access Control) Implementation for ICAO 9303 documents.
Used for e-Passport and Vietnamese CCCD authentication.
"""

import hashlib
import logging
from typing import Tuple

from .utils import CRYPTO_AVAILABLE

if CRYPTO_AVAILABLE:
    from Crypto.Cipher import DES3, DES
else:
    DES3 = None
    DES = None

logger = logging.getLogger(__name__)


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
    def derive_keys(doc_number: str, birth_date: str, expiry_date: str) -> Tuple[bytes, bytes]:
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
