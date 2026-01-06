#! /usr/bin/env python3
"""Check what card is connected and its ATR"""

import sys
sys.path.append('./../mnbcard')

from smartcard.System import readers
from smartcard.util import toHexString

print("="*60)
print("Card Reader Check")
print("="*60)

# List all readers
reader_list = readers()
print(f"\nFound {len(reader_list)} reader(s):")
for i, r in enumerate(reader_list):
    print(f"  [{i}] {r}")

if not reader_list:
    print("\nNo card reader found!")
    sys.exit(1)

# Try to connect to card
reader = reader_list[0]
print(f"\nUsing reader: {reader}")

try:
    connection = reader.createConnection()
    connection.connect()
    
    # Get ATR (Answer To Reset) - identifies the card type
    atr = connection.getATR()
    atr_hex = toHexString(atr)
    
    print(f"\n✓ Card detected!")
    print(f"ATR: {atr_hex}")
    
    # Known ATR patterns
    if "D276000085010100" in atr_hex.replace(" ", ""):
        print("→ This appears to be a マイナンバーカード (My Number Card)")
    elif "D276000085" in atr_hex.replace(" ", ""):
        print("→ This appears to be a Japanese IC card")
    elif "3B8F8001804F0CA0" in atr_hex.replace(" ", ""):
        print("→ This appears to be a FeliCa card (Suica/PASMO/etc)")
    else:
        print("→ Unknown card type")
    
    # Try to select PKI applet (マイナンバーカード)
    print("\nTrying to select PKI applet (公的個人認証AP)...")
    SELECT_PKI = [0x00, 0xA4, 0x04, 0x0C, 0x0A, 
                  0xD3, 0x92, 0xF0, 0x00, 0x26, 0x01, 0x00, 0x00, 0x00, 0x01]
    
    data, sw1, sw2 = connection.transmit(SELECT_PKI)
    print(f"Response: SW1={hex(sw1)} SW2={hex(sw2)}")
    
    if sw1 == 0x90 and sw2 == 0x00:
        print("✓ PKI applet found - This IS a マイナンバーカード!")
    else:
        print("✗ PKI applet NOT found - This might not be a マイナンバーカード")
        
    # Try Profile applet
    print("\nTrying to select Profile applet (券面入力補助AP)...")
    SELECT_PROFILE = [0x00, 0xA4, 0x04, 0x0C, 0x0A,
                      0xD3, 0x92, 0x10, 0x00, 0x31, 0x00, 0x01, 0x01, 0x04, 0x08]
    
    data, sw1, sw2 = connection.transmit(SELECT_PROFILE)
    print(f"Response: SW1={hex(sw1)} SW2={hex(sw2)}")
    
    if sw1 == 0x90 and sw2 == 0x00:
        print("✓ Profile applet found!")
    else:
        print("✗ Profile applet NOT found")

except Exception as e:
    print(f"\n✗ Error: {e}")
    print("\nMake sure:")
    print("  1. Card is placed on the reader")
    print("  2. Card is a マイナンバーカード (not Suica/PASMO)")
    print("  3. Card reader driver is correct (PC/SC driver, not libusb)")

print("\n" + "="*60)

