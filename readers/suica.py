"""
Suica / FeliCa Card Reader (交通系ICカード)
Supports Suica, Pasmo, ICOCA and other FeliCa-based transit IC cards.
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from .utils import get_hex_string, SMARTCARD_AVAILABLE, NFCPY_AVAILABLE

if SMARTCARD_AVAILABLE:
    from smartcard.util import toHexString

if NFCPY_AVAILABLE:
    import nfc
    from nfc.tag.tt3_sony import FelicaStandard

logger = logging.getLogger(__name__)


class SuicaReader:
    """
    Suica/Pasmo/ICOCA and other FeliCa-based transit IC cards reader.
    Uses PC/SC transparent commands for FeliCa access via Sony PaSoRi.
    """
    
    # FeliCa System Codes
    SYSTEM_CODE_SUICA = [0x00, 0x03]
    SYSTEM_CODE_COMMON = [0x88, 0xB4]
    
    # Service Codes for Suica (little-endian format)
    SERVICE_HISTORY = 0x090F
    
    def __init__(self, connection):
        self.connection = connection
        self.idm = None
        self.pmm = None
    
    def send_apdu(self, apdu: List[int]) -> tuple:
        data, sw1, sw2 = self.connection.transmit(apdu)
        logger.debug(f"APDU: {get_hex_string(apdu)} -> {get_hex_string(data)} SW={sw1:02X}{sw2:02X}")
        return data, sw1, sw2
    
    def felica_command(self, cmd_data: List[int]) -> Optional[List[int]]:
        """Send FeliCa command via PC/SC transparent command."""
        try:
            cmd_with_len = [len(cmd_data) + 1] + cmd_data
            apdu = [0xFF, 0x00, 0x00, 0x00, len(cmd_with_len)] + cmd_with_len
            
            data, sw1, sw2 = self.send_apdu(apdu)
            
            if sw1 == 0x90 and len(data) > 0:
                return list(data)
            
            if sw1 == 0x6A and sw2 == 0x81:
                logger.warning("PC/SC transparent FeliCa commands not supported by this reader")
                return None
            
            apdu2 = [0xFF, 0x00, 0x00, 0x00, len(cmd_data)] + cmd_data
            data, sw1, sw2 = self.send_apdu(apdu2)
            
            if sw1 == 0x90 and len(data) > 0:
                return list(data)
                
        except Exception as e:
            logger.warning(f"FeliCa command failed: {e}")
            
        return None
    
    def felica_polling(self) -> bool:
        """Poll for FeliCa card. Returns True if card found."""
        # Try GET_DATA command first
        data, sw1, sw2 = self.send_apdu([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if sw1 == 0x90 and len(data) >= 8:
            self.idm = bytes(data[:8])
            logger.info(f"FeliCa IDm: {get_hex_string(list(self.idm))}")
            return True
        
        # Try FeliCa Polling command
        for system_code in [[0x00, 0x03], [0x88, 0xB4], [0xFF, 0xFF]]:
            polling_cmd = [0x00] + system_code + [0x01, 0x0F]
            response = self.felica_command(polling_cmd)
            
            if response and len(response) >= 17:
                self.idm = bytes(response[1:9])
                self.pmm = bytes(response[9:17])
                logger.info(f"FeliCa IDm: {get_hex_string(list(self.idm))}")
                return True
        
        return False
    
    def read_blocks(self, service_code: int, block_numbers: List[int]) -> Optional[List[bytes]]:
        """Read blocks from FeliCa card using Read Without Encryption."""
        if not self.idm:
            logger.warning("No IDm available")
            return None
        
        block_numbers = block_numbers[:1]
        num_blocks = len(block_numbers)
        
        block_list = []
        for block_num in block_numbers:
            block_list.extend([0x80, block_num & 0xFF])
        
        cmd = (
            [0x06] +
            list(self.idm) +
            [0x01] +
            [service_code & 0xFF, (service_code >> 8) & 0xFF] +
            [num_blocks] +
            block_list
        )
        
        logger.info(f"Read cmd for service {service_code:04X}: {get_hex_string(cmd)}")
        
        response = self.felica_command(cmd)
        
        if not response:
            logger.warning(f"No response for Read Without Encryption")
            return None
        
        logger.info(f"Read response ({len(response)} bytes): {get_hex_string(response[:min(32, len(response))])}")
        
        first_byte = response[0]
        
        if first_byte == 0x07:
            offset = 0
        elif first_byte == len(response) or first_byte == len(response) - 1:
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
        
        blocks = []
        data_offset = offset + 12
        for i in range(resp_num_blocks):
            if data_offset + 16 <= len(response):
                block_data = bytes(response[data_offset:data_offset + 16])
                blocks.append(block_data)
                logger.info(f"Block {i}: {get_hex_string(list(block_data))}")
                data_offset += 16
        
        return blocks if blocks else None
    
    def parse_suica_balance(self, block_data: bytes) -> int:
        """Parse balance from Suica block data"""
        if len(block_data) < 12:
            return -1
        return block_data[11] << 8 | block_data[10]
    
    def parse_suica_history(self, block_data: bytes) -> Dict[str, Any]:
        """Parse history entry from Suica block data"""
        if len(block_data) < 16:
            return {"error": "Invalid data"}
        
        entry = {}
        
        terminal_type = block_data[0]
        terminal_names = {
            0x03: "精算機", 0x05: "バス", 0x07: "券売機",
            0x08: "精算機", 0x12: "券売機", 0x14: "券売機等",
            0x15: "券売機等", 0x16: "改札機", 0x17: "券売機",
            0x18: "券売機", 0x1A: "改札機", 0x1B: "バス等",
            0x1C: "バス等", 0x1F: "物販", 0x46: "VIEW ALTTE",
            0x48: "VIEW ALTTE", 0xC7: "物販", 0xC8: "物販",
        }
        entry["terminal"] = terminal_names.get(terminal_type, f"Unknown({terminal_type:02X})")
        
        process_type = block_data[1]
        process_names = {
            0x01: "運賃支払", 0x02: "チャージ", 0x03: "物販購入",
            0x04: "精算", 0x05: "精算 (入場)", 0x06: "物販取消",
            0x07: "入金精算", 0x0F: "バス", 0x11: "バス",
            0x13: "バス/路面等", 0x14: "オートチャージ", 0x15: "バス等",
            0x1F: "バスチャージ", 0x46: "物販現金", 0x49: "入金",
        }
        entry["process"] = process_names.get(process_type, f"Unknown({process_type:02X})")
        
        date_raw = (block_data[4] << 8) | block_data[5]
        year = ((date_raw >> 9) & 0x7F) + 2000
        month = (date_raw >> 5) & 0x0F
        day = date_raw & 0x1F
        if 1 <= month <= 12 and 1 <= day <= 31:
            entry["date"] = f"{year}/{month:02d}/{day:02d}"
        else:
            entry["date_raw"] = f"{date_raw:04X}"
        
        balance = (block_data[11] << 8) | block_data[10]
        entry["balance"] = balance
        
        return entry
    
    def read_card(self) -> Dict[str, Any]:
        """Read Suica card data"""
        card_data = {}
        
        if not self.felica_polling():
            return {"error": "FeliCa polling failed"}
        
        if self.idm:
            card_data["idm"] = get_hex_string(list(self.idm)).replace(" ", "")
            manufacturer = (self.idm[0] << 8) | self.idm[1]
            card_data["manufacturer"] = f"0x{manufacturer:04X}"
        
        if self.pmm:
            card_data["pmm"] = get_hex_string(list(self.pmm)).replace(" ", "")
        
        card_data["card_type"] = "Suica/Pasmo/ICOCA (交通系IC)"
        
        history_blocks = self.read_blocks(self.SERVICE_HISTORY, [0])
        
        if history_blocks and len(history_blocks) > 0:
            first_block = history_blocks[0]
            card_data["block0_raw"] = get_hex_string(list(first_block))
            
            if len(first_block) >= 12:
                balance = (first_block[11] << 8) | first_block[10]
                card_data["balance"] = f"¥{balance:,}"
                card_data["balance_raw"] = balance
            
            entry = self.parse_suica_history(first_block)
            card_data["last_transaction"] = entry
        else:
            card_data["balance"] = "🔒 暗号化エリア"
            card_data["limitation"] = "Suicaの残高・履歴は暗号化されており、特殊な認証が必要です"
            card_data["reason"] = "Sony PaSoRiのPC/SCドライバはFeliCa暗号化エリアの読取に非対応"
            card_data["solutions"] = [
                "1. スマホアプリ「Suica」で確認",
                "2. suica-viewerを使用 (nfcpy + リモート認証)",
                "3. 駅の券売機で残高確認"
            ]
        
        return card_data


class NfcpySuicaReader:
    """
    Full Suica reader using nfcpy for direct USB access.
    Uses remote authentication server for encrypted area access.
    """
    
    SYSTEM_CODE = 0x0003
    AUTH_SERVER_URL = "https://felica-auth.nyaa.ws"
    
    AREA_NODE_IDS = (0x0000, 0x0040, 0x0800, 0x0FC0, 0x1000)
    SERVICE_NODE_IDS = (0x0048, 0x0088, 0x0810, 0x08C8, 0x090C, 0x1008, 0x1048, 0x108C, 0x10C8)
    
    CARD_TYPE_LABELS = {
        0: "せたまる/IruCa",
        2: "Suica/PiTaPa/TOICA/PASMO",
        3: "ICOCA",
    }
    
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
        
        while True:
            step = response.get("step")
            
            if step in ("auth1", "auth2"):
                command = response.get("command", {})
                frame = bytes.fromhex(command.get("frame", ""))
                timeout = command.get("timeout", 1.0)
                
                logger.debug(f"Auth step {step}: sending {frame.hex()}")
                card_response = tag.clf.exchange(frame, timeout)
                logger.debug(f"Card response: {card_response.hex()}")
                
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
        
        elements = []
        for block_idx in block_indexes:
            elements.append(0x80 | service_index)
            elements.append(block_idx & 0xFF)
        
        payload = bytes([len(block_indexes)]) + bytes(elements)
        
        response = self._http_post("/encryption-exchange", {
            "session_id": self.session_id,
            "cmd_code": 0x14,
            "payload": payload.hex(),
        })
        self.session_id = response.get("session_id", self.session_id)
        
        command = response.get("command", {})
        frame = bytes.fromhex(command.get("frame", ""))
        timeout = command.get("timeout", 1.0)
        
        card_response = tag.clf.exchange(frame, timeout)
        
        final_response = self._http_post("/encryption-exchange", {
            "session_id": self.session_id,
            "card_response": card_response.hex(),
        })
        
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
            with nfc.ContactlessFrontend("usb") as clf:
                logger.info("nfcpy: Waiting for card...")
                
                tag_holder = [None]
                
                def on_connect(tag):
                    if isinstance(tag, FelicaStandard):
                        tag_holder[0] = tag
                        return True
                    return False
                
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
                
                polling_result = tag.polling(self.SYSTEM_CODE)
                if len(polling_result) >= 2:
                    tag.idm, tag.pmm = polling_result[0], polling_result[1]
                
                card_data["idm"] = tag.idm.hex().upper()
                card_data["pmm"] = tag.pmm.hex().upper()
                card_data["card_type"] = "Suica/Pasmo/ICOCA"
                
                logger.info("nfcpy: Starting mutual authentication...")
                auth_result = self._mutual_authentication(tag)
                
                idi = auth_result.get("issue_id", auth_result.get("idi", ""))
                pmi = auth_result.get("issue_parameter", auth_result.get("pmi", ""))
                
                card_data["idi"] = idi.upper() if idi else None
                card_data["pmi"] = pmi.upper() if pmi else None
                card_data["authenticated"] = True
                
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
                
                logger.info("nfcpy: Reading transaction history...")
                try:
                    history_blocks = self._read_encrypted_blocks(tag, 4, list(range(10)))
                    history = []
                    
                    for i, block in enumerate(history_blocks):
                        if block[0] == 0x00:
                            continue
                        
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
