#! /usr/bin/env python3
"""
Simple script to read basic info from マイナンバーカード
Only requires the 4-digit Profile PIN (券面入力補助用パスワード)
"""

import logging
import sys
sys.path.append('./../mnbcard')

from reader import get_reader, connect_card
from api import Card
from helper import save_to_file

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Connect to card reader
print("Connecting to card reader...")
reader = get_reader()
connection = connect_card(reader)
card = Card(connection)

# Only need the 4-digit Profile PIN
profile_pin = input("Please input the 4-digit Profile PIN (券面入力補助用パスワード): ")

print("\n" + "="*50)
print("Reading card information...")
print("="*50 + "\n")

# Get My Number (個人番号)
try:
    my_number = card.get_my_number(profile_pin)
    print(f"マイナンバー (個人番号): {my_number}")
except Exception as e:
    print(f"Error reading My Number: {e}")

# Get basic 4 info (name, address, birthdate, gender)
try:
    name, address, birthdate, gender = card.get_basic_info(profile_pin)
    gender_map = {"1": "男性", "2": "女性", "3": "その他"}
    gender_text = gender_map.get(gender.strip(), gender)
    
    print(f"\n--- 基本4情報 ---")
    print(f"名前: {name}")
    print(f"住所: {address}")
    print(f"生年月日: {birthdate}")
    print(f"性別: {gender_text}")
except Exception as e:
    print(f"Error reading basic info: {e}")
    # Debug: Try to read raw data
    print("Attempting to read raw data for debugging...")
    try:
        card.select_file_profile_ap()
        card.select_file_profile_pin()
        card.verify_profile_pin([ord(c) for c in profile_pin])
        card.select_file_base_4_info()
        raw_data = card.read_binary_256()
        print(f"Raw data (first 100 bytes): {raw_data[:100]}")
        print(f"Raw hex: {' '.join(f'{b:02x}' for b in raw_data[:100])}")
    except Exception as e2:
        print(f"Debug failed: {e2}")

# Also get auth certificate (no PIN required)
try:
    auth_cert = card.get_cert_for_auth()
    save_to_file("Auth_Cert.der", auth_cert)
    print(f"\n認証用証明書を Auth_Cert.der に保存しました")
except Exception as e:
    print(f"Error reading auth certificate: {e}")

print("\n" + "="*50)
print("Complete!")
print("="*50)

