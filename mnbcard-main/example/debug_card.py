#! /usr/bin/env python3
"""Debug script to analyze raw card data"""

import sys
sys.path.append('./../mnbcard')

from reader import get_reader, connect_card
from api import Card

print("Connecting to card reader...")
reader = get_reader()
connection = connect_card(reader)
card = Card(connection)

profile_pin = input("4-digit PIN: ")

# Read raw data
card.select_file_profile_ap()
card.select_file_profile_pin()
card.verify_profile_pin([ord(c) for c in profile_pin])
card.select_file_base_4_info()
raw_data = card.read_binary_256()

print("\n" + "="*70)
print("RAW DATA ANALYSIS")
print("="*70)

# Print first 50 bytes with indices
print("\nByte index and values:")
for i in range(min(50, len(raw_data))):
    val = raw_data[i]
    char = chr(val) if 32 <= val < 127 else '.'
    print(f"  [{i:2d}] = 0x{val:02x} ({val:3d}) '{char}'")

print("\n" + "-"*70)
print("Looking for TLV segments (0xDF markers):")

# Find all 0xDF markers (TLV segment starts)
for i, b in enumerate(raw_data[:100]):
    if b == 0xDF:
        tag1 = raw_data[i+1] if i+1 < len(raw_data) else 0
        length = raw_data[i+2] if i+2 < len(raw_data) else 0
        print(f"  Found 0xDF at position {i}, tag=0x{tag1:02x}, length={length}")
        
        # Try to decode the content
        if i + 3 + length <= len(raw_data):
            content = bytes(raw_data[i+3:i+3+length])
            for enc in ["utf-8", "cp932", "shift-jis"]:
                try:
                    decoded = content.decode(enc)
                    print(f"    Content ({enc}): {decoded}")
                    break
                except:
                    pass

print("\n" + "-"*70)
print("Manifest positions from library:")
print(f"  NAME_SEGMENT_START = 9  -> data[9] = {raw_data[9]}")
print(f"  ADDRESS_SEGMENT_START = 11 -> data[11] = {raw_data[11]}")
print(f"  BIRTHDATE_SEGMENT_START = 13 -> data[13] = {raw_data[13]}")
print(f"  GENDER_SEGMENT_START = 15 -> data[15] = {raw_data[15]}")

print("\n" + "="*70)

