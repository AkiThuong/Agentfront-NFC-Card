#!/usr/bin/env python3
"""
Suica Reader Subprocess - Outputs JSON for parent process
Uses nfcpy with remote authentication server
Run this script separately when Suica reading is needed
"""

import json
import sys
import os

# Add suica-reader to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'suica-reader'))

def read_suica():
    """Read Suica card and return JSON result"""
    result = {
        "success": False,
        "error": None,
        "data": {}
    }
    
    try:
        import nfc
        from nfc.tag.tt3_sony import FelicaStandard
    except ImportError as e:
        result["error"] = f"nfcpy not installed: {e}"
        return result
    
    # Import from suica-viewer
    try:
        from suica_viewer.auth_client import FelicaRemoteClient, FelicaRemoteClientError
        from suica_viewer.utils import SYSTEM_CODE, CARD_TYPE_LABELS
        from suica_viewer.cli import (
            RemoteCardReader, resolve_server_url, resolve_auth_token,
            AREA_NODE_IDS, SERVICE_NODE_IDS
        )
    except ImportError as e:
        result["error"] = f"suica_viewer not found: {e}. Make sure suica-reader folder exists."
        return result
    
    # Equipment and transaction type mappings
    EQUIPMENT_TYPES = {
        0x00: "未定義", 0x03: "のりこし精算機", 0x05: "バス車載機",
        0x07: "カード発売機", 0x08: "自動券売機", 0x16: "自動改札機",
        0x17: "簡易改札機", 0x1A: "有人改札", 0x46: "VIEW ALTTE",
        0xC7: "物販端末", 0xC8: "物販端末",
    }
    
    TRANSACTION_TYPES = {
        0x01: "改札出場", 0x02: "チャージ", 0x03: "きっぷ購入",
        0x04: "磁気券精算", 0x05: "乗越精算", 0x07: "新規",
        0x0F: "バス", 0x14: "オートチャージ", 0x46: "物販",
    }
    
    def format_date(value):
        year = (value >> 9) & 0x7F
        month = (value >> 5) & 0x0F
        day = value & 0x1F
        return f"{year:02d}-{month:02d}-{day:02d}"
    
    def format_station(line_code, station_order):
        return f"線区:{line_code:02X} 駅順:{station_order:02X}"
    
    # Fix IC code map for newer cards
    FelicaStandard.IC_CODE_MAP[0x31] = ("RC-S???", 1, 1)
    
    tag_holder = [None]
    card_data = {}
    
    def on_connect(tag):
        if not isinstance(tag, FelicaStandard):
            return False
        
        try:
            # Get card ID
            polling_result = tag.polling(SYSTEM_CODE)
            if len(polling_result) >= 2:
                tag.idm, tag.pmm = polling_result
            
            card_data["idm"] = tag.idm.hex().upper()
            card_data["pmm"] = tag.pmm.hex().upper()
            card_data["card_type"] = "Suica/Pasmo/ICOCA"
            
            # Setup remote client
            client = FelicaRemoteClient(
                resolve_server_url(),
                tag,
                bearer_token=resolve_auth_token(),
            )
            
            # Perform mutual authentication
            auth_result = client.mutual_authentication(
                SYSTEM_CODE,
                list(AREA_NODE_IDS),
                list(SERVICE_NODE_IDS),
            )
            
            idi = auth_result.get("issue_id", auth_result.get("idi", ""))
            pmi = auth_result.get("issue_parameter", auth_result.get("pmi", ""))
            
            card_data["idi"] = idi.upper() if idi else None
            card_data["pmi"] = pmi.upper() if pmi else None
            card_data["authenticated"] = True
            
            # Create reader
            reader = RemoteCardReader(client)
            
            # Read attribute info (balance) - service index 1
            try:
                attr_blocks = reader.read_blocks(1, [0])
                if attr_blocks and len(attr_blocks) > 0:
                    block = attr_blocks[0]
                    card_type_code = block[8] >> 4
                    card_data["card_type_detail"] = CARD_TYPE_LABELS.get(card_type_code, "不明")
                    
                    balance = int.from_bytes(block[11:13], byteorder="little")
                    card_data["balance"] = f"¥{balance:,}"
                    card_data["balance_raw"] = balance
                    
                    transaction_number = int.from_bytes(block[14:16], byteorder="big")
                    card_data["transaction_count"] = transaction_number
            except Exception as e:
                card_data["balance_error"] = str(e)
            
            # Read transaction history - service index 4
            try:
                history_blocks = reader.read_blocks(4, list(range(10)))
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
                        "date": format_date(recorded_at),
                        "type": TRANSACTION_TYPES.get(transaction_type, f"不明({transaction_type:02X})"),
                        "device": EQUIPMENT_TYPES.get(recorded_by, f"不明({recorded_by:02X})"),
                        "entry": format_station(entry_line, entry_station),
                        "exit": format_station(exit_line, exit_station),
                        "balance_after": amount,
                    })
                
                if history:
                    card_data["history_count"] = len(history)
                    card_data["recent_history"] = history[:5]
            except Exception as e:
                card_data["history_error"] = str(e)
            
            tag_holder[0] = tag
            return True
            
        except FelicaRemoteClientError as e:
            card_data["auth_error"] = str(e)
            tag_holder[0] = tag
            return True
        except Exception as e:
            card_data["error"] = str(e)
            tag_holder[0] = tag
            return True
    
    try:
        print("Waiting for Suica card...", file=sys.stderr)
        with nfc.ContactlessFrontend("usb") as clf:
            clf.connect(
                rdwr={
                    "targets": ["212F", "424F"],  # FeliCa only
                    "on-connect": on_connect,
                },
                terminate=lambda: tag_holder[0] is not None,
            )
        
        if card_data:
            result["success"] = True
            result["data"] = card_data
        else:
            result["error"] = "No card data received"
            
    except IOError as e:
        result["error"] = f"Cannot access NFC reader: {e}. Is another program using it?"
    except Exception as e:
        result["error"] = str(e)
    
    return result


if __name__ == "__main__":
    result = read_suica()
    print(json.dumps(result, ensure_ascii=False, indent=2))





