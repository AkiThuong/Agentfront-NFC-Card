"""
Zairyu Card OCR Result Parser.
Extracts structured fields from OCR text blocks.

Optimized for PaddleOCR output format.
This module is separate from OCR providers so the same parsing logic
can be used with any OCR backend.
"""

import re
import logging
from typing import Dict, List, Tuple, Any, Optional
from .base import OCRResult, OCRTextBlock

logger = logging.getLogger(__name__)


class ZairyuCardParser:
    """
    Parser for Zairyu Card (在留カード) OCR results.
    Optimized for Japanese government ID card format.
    
    Extracts:
    - Card number (在留カード番号) - e.g., "UH17622299ER"
    - Name (氏名) - e.g., "BUI NGOC YEN"
    - Date of birth (生年月日) - e.g., "2005年06月01日"
    - Gender (性別) - e.g., "女 F." or "男 M."
    - Nationality (国籍・地域) - e.g., "ベトナム"
    - Address (住居地) - e.g., "埼玉県川越市..."
    - Status of residence (在留資格) - e.g., "留学"
    - Period of stay (在留期間) - e.g., "3年11月"
    - Expiration date (在留期間の満了日) - e.g., "2029年05月17日"
    - Work permission (就労制限) - e.g., "就労不可" or "就労制限なし"
    """
    
    # Known nationality values (expanded list)
    NATIONALITIES = [
        # Southeast Asia
        'ベトナム', 'ヴェトナム', 'フィリピン', 'インドネシア', 'タイ',
        'ミャンマー', 'マレーシア', 'シンガポール', 'カンボジア', 'ラオス',
        # East Asia
        '中国', '韓国', '台湾', '香港', 'モンゴル',
        # South Asia
        'ネパール', 'インド', 'スリランカ', 'バングラデシュ', 'パキスタン',
        # Americas
        'ブラジル', 'ペルー', '米国', 'アメリカ', 'カナダ', 'メキシコ',
        # Europe
        '英国', 'イギリス', 'フランス', 'ドイツ', 'イタリア', 'スペイン',
        'ロシア', 'ウクライナ', 'ポーランド',
        # Oceania
        'オーストラリア', 'オーストラリヤ', 'ニュージーランド',
        'ニューシーランド', 'ニュ一ジ一ランド', 'ニユージーランド',  # OCR variations
        'ニュージランド', 'ニューシランド',  # Missing vowel mark variations
        # Africa
        'ナイジェリア', 'ガーナ', 'エジプト',
    ]
    
    # Known residence status values (comprehensive list)
    RESIDENCE_STATUSES = [
        # Work statuses
        '技術・人文知識・国際業務', '技術', '人文知識', '国際業務',
        '技能実習', '技能実習1号', '技能実習2号', '技能実習3号',
        '特定技能', '特定技能1号', '特定技能2号',
        '技能', '高度専門職', '高度専門職1号', '高度専門職2号',
        '経営・管理', '経営', '管理',
        '企業内転勤', '介護', '興行', '研究', '教育', '教授',
        '芸術', '宗教', '報道', '法律・会計業務',
        # Study/Training
        '留学', '研修', '文化活動',
        # Family/Spouse
        '家族滞在', '日本人の配偶者等', '永住者の配偶者等',
        '定住者', '永住者',
        # Special
        '特定活動', '短期滞在',
        # Student - common OCR variations
        'Student', 'student',
    ]
    
    # Words to skip when detecting names (EXACT MATCH only)
    # These are matched exactly against individual words in the text
    SKIP_WORDS = [
        # Card labels and headers
        'VALIDITY', 'PERIOD', 'CARD', 'FERICD', 'STUDENT', 'SRUDENT',
        'RESIDENCE', 'STATUS', 'PERMIT', 'JAPAN', 'IMMIGRATION',
        'MINISTRY', 'JUSTICE', 'SERVICES', 'AGENCY',
        'DATE', 'BIRTH', 'SEX', 'NATIONALITY', 'ADDRESS',
        'STAY', 'EXPIRATION', 'WORK', 'PERMISSION',
        'THIS', 'THE', 'OF', 'FOR', 'AND', 'IS', 'TO',
        # Residence status labels
        'DESIGNATED', 'ACTIVITIES', 'ACTIVITY',
        # Card text labels
        'NAME', 'NUMBER', 'ISSUE', 'ISSUED', 'EXPIRED',
        'HOLDER', 'BEARER', 'PHOTO', 'SIGNATURE',
    ]
    
    # Full phrases to skip (checked as substrings)
    SKIP_PHRASES = [
        'PERIOD OF VALIDITY',
        'VALIDITY OF THIS CARD',
        'DATE OF BIRTH',
        'STATUS OF RESIDENCE',
    ]
    
    def __init__(self, line_threshold: int = 25):
        """
        Initialize parser.
        
        Args:
            line_threshold: Pixel threshold for grouping text into lines
        """
        self.line_grouping_threshold = line_threshold
    
    def parse(self, ocr_result: OCRResult) -> Dict[str, str]:
        """
        Parse OCR result into structured fields.
        
        Args:
            ocr_result: OCRResult from any OCR provider
            
        Returns:
            Dict with extracted fields
        """
        if not ocr_result.success or not ocr_result.text_blocks:
            return {}
        
        # Convert to format expected by internal parsing
        raw_results = [
            (block.bbox, block.text, block.confidence)
            for block in ocr_result.text_blocks
        ]
        
        return self._parse_raw_results(raw_results)
    
    def parse_raw(self, ocr_results: List[Tuple[List, str, float]]) -> Dict[str, str]:
        """
        Parse raw OCR results (bbox, text, confidence tuples).
        
        Args:
            ocr_results: List of (bbox, text, confidence) tuples
            
        Returns:
            Dict with extracted fields
        """
        return self._parse_raw_results(ocr_results)
    
    def _parse_raw_results(self, ocr_results: List[Tuple]) -> Dict[str, str]:
        """Internal parsing implementation"""
        parsed = {}
        
        if not ocr_results:
            return parsed
        
        # Debug: Log raw OCR results structure
        logger.warning(f"=== PARSING {len(ocr_results)} OCR RESULTS ===")
        for i, r in enumerate(ocr_results[:5]):  # Log first 5
            bbox = r[0] if len(r) > 0 else None
            text = r[1] if len(r) > 1 else None
            conf = r[2] if len(r) > 2 else None
            bbox_info = f"bbox={bbox}" if bbox else "NO BBOX"
            logger.warning(f"  [{i}] text='{text}', {bbox_info}")
        if len(ocr_results) > 5:
            logger.warning(f"  ... and {len(ocr_results) - 5} more")
        
        # Get all text blocks
        all_texts = [r[1] for r in ocr_results if r[1]]
        full_text = " ".join(all_texts)
        
        # Group text blocks into visual lines
        text_lines = self._group_into_lines(ocr_results)
        
        # Log lines for debugging
        logger.info(f"Parsed {len(text_lines)} visual lines:")
        for i, line in enumerate(text_lines):
            logger.info(f"  Line {i}: {line}")
        
        # Extract card number first (needed for name extraction)
        parsed.update(self._extract_card_number(full_text, all_texts))
        logger.warning(f"Card number extracted: {parsed.get('card_number', 'NOT FOUND')}")
        
        # Extract name using position-based detection (preferred for Zairyu cards)
        # Falls back to text-based detection if position-based fails
        logger.warning("=== ATTEMPTING POSITION-BASED NAME DETECTION ===")
        name_result = self._extract_name_by_position(ocr_results, parsed.get('card_number'))
        if name_result:
            logger.info(f"Position-based name: {name_result.get('name')}")
            parsed.update(name_result)
        else:
            # Fallback to old method
            logger.info("Position-based failed, trying text-based fallback...")
            name_result = self._extract_name(text_lines, all_texts, parsed.get('card_number'))
            if name_result:
                logger.info(f"Text-based name: {name_result.get('name')}")
                parsed.update(name_result)
            else:
                logger.warning("NAME NOT FOUND by any method!")
        
        # Extract other fields
        parsed.update(self._extract_dob_gender_nationality(text_lines, full_text))
        
        # If nationality not found by text-based method, try position-based
        if "nationality" not in parsed:
            logger.warning("=== ATTEMPTING POSITION-BASED NATIONALITY DETECTION ===")
            nationality_result = self._extract_nationality_by_position(ocr_results)
            if nationality_result:
                parsed.update(nationality_result)
        
        parsed.update(self._extract_period_and_expiry(text_lines, full_text))
        parsed.update(self._extract_status(text_lines, full_text))
        parsed.update(self._extract_address(text_lines, full_text))
        parsed.update(self._extract_work_permission(full_text))
        
        logger.info(f"Parsed fields: {parsed}")
        return parsed
    
    def _group_into_lines(self, ocr_results: List[Tuple]) -> List[str]:
        """Group OCR blocks into visual lines based on Y-coordinate"""
        if not ocr_results:
            return []
        
        # Filter out results without valid bbox
        valid_results = []
        for r in ocr_results:
            if r[0] and len(r[0]) >= 1 and r[1]:
                try:
                    # Get Y coordinate from first point of bbox
                    if isinstance(r[0][0], (list, tuple)):
                        y = float(r[0][0][1])
                    else:
                        y = float(r[0][1])
                    valid_results.append((r, y))
                except (IndexError, TypeError, ValueError):
                    continue
        
        if not valid_results:
            # Fallback: just return all texts
            return [r[1] for r in ocr_results if r[1]]
        
        # Sort by Y-coordinate
        sorted_blocks = sorted(valid_results, key=lambda x: x[1])
        
        lines = []
        current_line = [sorted_blocks[0]]
        current_y = sorted_blocks[0][1]
        
        for block, y in sorted_blocks[1:]:
            # If Y difference is small, same line
            if abs(y - current_y) < self.line_grouping_threshold:
                current_line.append((block, y))
            else:
                # Sort completed line by X position (left to right)
                current_line.sort(key=lambda x: self._get_x_coord(x[0][0]))
                lines.append(" ".join(b[0][1] for b in current_line))
                current_line = [(block, y)]
                current_y = y
        
        # Append last line
        if current_line:
            current_line.sort(key=lambda x: self._get_x_coord(x[0][0]))
            lines.append(" ".join(b[0][1] for b in current_line))
        
        return lines
    
    def _get_x_coord(self, bbox) -> float:
        """Get X coordinate from bbox"""
        try:
            if isinstance(bbox[0], (list, tuple)):
                return float(bbox[0][0])
            else:
                return float(bbox[0])
        except:
            return 0.0
    
    def _normalize_date(self, date_str: str) -> str:
        """Normalize date format, fix OCR errors"""
        if not date_str:
            return date_str
        
        # Remove spaces
        date_str = date_str.replace(" ", "")
        
        # Fix common OCR error where '日' is read as '月' at end of date
        if re.match(r'.+\d{1,2}月$', date_str) and date_str.count('月') > 1:
            date_str = date_str[:-1] + "日"
        
        # Fix OCR errors in numbers
        date_str = date_str.replace('O', '0').replace('o', '0')
        date_str = date_str.replace('l', '1').replace('I', '1')
        
        return date_str
    
    def _extract_card_number(self, full_text: str, all_texts: List[str]) -> Dict[str, str]:
        """Extract card number (e.g., UH17622299ER)"""
        # Pattern: 2 letters + 8 digits + 2 letters
        pattern = r'([A-Z]{2}\d{8}[A-Z]{2})'
        
        # First try in full text (no spaces)
        clean_text = full_text.replace(" ", "").upper()
        match = re.search(pattern, clean_text)
        if match:
            return {"card_number": match.group(1)}
        
        # Try in individual text blocks
        for text in all_texts:
            clean = text.replace(" ", "").upper()
            match = re.search(pattern, clean)
            if match:
                return {"card_number": match.group(1)}
        
        return {}
    
    def _extract_name(self, text_lines: List[str], all_texts: List[str], 
                      card_number: Optional[str] = None) -> Dict[str, str]:
        """Extract name (Latin characters, typically near top)"""
        
        # This is a fallback - prefer _extract_name_by_position when bbox data is available
        logger.info("=== TEXT-BASED NAME DETECTION (FALLBACK) ===")
        candidates = []
        
        # Check each line and individual text block
        for source in [text_lines, all_texts]:
            for text in source:
                clean_text = text.strip()
                check_content = clean_text.replace(" ", "")
                
                # Skip if it's the card number
                if card_number and check_content.upper() == card_number:
                    continue
                
                # Skip if contains numbers (except for spacing issues)
                if re.search(r'\d', check_content):
                    continue
                
                # Skip if contains Japanese characters
                if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', check_content):
                    continue
                
                # Skip known non-name words
                # Single words: exact match; Multi-word: only skip phrases
                text_upper = clean_text.upper().strip()
                text_word_list = text_upper.split()
                
                if len(text_word_list) == 1:
                    if text_upper in self.SKIP_WORDS:
                        continue
                else:
                    if any(phrase in text_upper for phrase in self.SKIP_PHRASES):
                        continue
                
                # Check if looks like a name (mostly letters)
                letter_count = sum(1 for c in check_content if c.isalpha())
                if letter_count >= 3 and letter_count / max(len(check_content), 1) > 0.8:
                    # Score by length (longer names are more likely correct)
                    score = len(clean_text)
                    candidates.append((clean_text.upper(), score))
                    logger.info(f"  ✓ TEXT CANDIDATE: '{clean_text}' (score={score})")
        
        if candidates:
            # Return the best candidate (longest)
            candidates.sort(key=lambda x: x[1], reverse=True)
            logger.info(f"  Selected: '{candidates[0][0]}' from {len(candidates)} candidates")
            return {"name": candidates[0][0]}
        
        logger.warning("  No text-based name candidates found!")
        return {}
    
    def _extract_name_by_position(self, ocr_results: List[Tuple], 
                                   card_number: Optional[str] = None) -> Dict[str, str]:
        """
        Extract name using position-based detection for Zairyu cards.
        
        The name on a Zairyu card is:
        - In the top-left area (within first 30% vertically)
        - The first English-only text line (reading top to bottom)
        - Left-aligned (card number is on the right)
        - Above the DOB line
        
        Args:
            ocr_results: List of (bbox, text, confidence) tuples
            card_number: Card number to exclude from detection
            
        Returns:
            Dict with 'name' key if found
        """
        if not ocr_results:
            return {}
        
        # Step 1: Extract blocks with valid bboxes and calculate card boundaries
        blocks_with_position = []
        all_y_coords = []
        all_x_coords = []
        
        for result in ocr_results:
            bbox, text, confidence = result[0], result[1], result[2] if len(result) > 2 else 0.0
            if not bbox or not text:
                continue
            
            # Get Y and X coordinates from bbox
            try:
                if isinstance(bbox[0], (list, tuple)):
                    # Format: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    y_coord = float(bbox[0][1])  # Top-left Y
                    x_coord = float(bbox[0][0])  # Top-left X
                    # Also get right edge for width calculation
                    x_right = float(bbox[1][0]) if len(bbox) > 1 else x_coord
                else:
                    # Format: [x1, y1, x2, y2, ...]
                    y_coord = float(bbox[1])
                    x_coord = float(bbox[0])
                    x_right = float(bbox[2]) if len(bbox) > 2 else x_coord
                
                all_y_coords.append(y_coord)
                all_x_coords.append(x_coord)
                all_x_coords.append(x_right)
                
                blocks_with_position.append({
                    'text': text.strip(),
                    'y': y_coord,
                    'x': x_coord,
                    'x_right': x_right,
                    'confidence': confidence
                })
            except (IndexError, TypeError, ValueError) as e:
                logger.debug(f"Failed to parse bbox for text '{text}': {e}")
                continue
        
        if not blocks_with_position or not all_y_coords:
            logger.warning(f"No valid position data! blocks={len(blocks_with_position)}, y_coords={len(all_y_coords)}")
            return {}
        
        # Step 2: Calculate card boundaries
        card_top = min(all_y_coords)
        card_bottom = max(all_y_coords)
        card_left = min(all_x_coords)
        card_right = max(all_x_coords)
        card_height = card_bottom - card_top
        card_width = card_right - card_left
        
        if card_height <= 0 or card_width <= 0:
            logger.debug("Invalid card dimensions")
            return {}
        
        # Step 3: Define name zone (top 30% of card, left 70% to exclude card number area)
        name_zone_bottom = card_top + card_height * 0.30
        name_zone_right = card_left + card_width * 0.70  # Exclude right side where card# is
        
        logger.debug(f"Card bounds: top={card_top:.0f}, bottom={card_bottom:.0f}, "
                    f"left={card_left:.0f}, right={card_right:.0f}")
        logger.debug(f"Name zone: y < {name_zone_bottom:.0f}, x < {name_zone_right:.0f}")
        
        # Step 4: Filter blocks in name zone and find English-only candidates
        name_candidates = []
        
        # Log all blocks for debugging
        logger.warning(f"Position-based: analyzing {len(blocks_with_position)} blocks")
        logger.warning(f"  Name zone: y < {name_zone_bottom:.0f}, x < {name_zone_right:.0f}")
        for block in blocks_with_position:
            text = block['text']
            y = block['y']
            x = block['x']
            in_y_zone = y <= name_zone_bottom
            in_x_zone = x <= name_zone_right
            logger.warning(f"  '{text[:30]}' y={y:.0f}, x={x:.0f} | y_ok={in_y_zone}, x_ok={in_x_zone}")
        
        for block in blocks_with_position:
            text = block['text']
            y = block['y']
            x = block['x']
            
            # Must be in top 30% of card
            if y > name_zone_bottom:
                continue
            
            # Must be on left side (not in card number area)
            if x > name_zone_right:
                continue
            
            # Skip if it's the card number
            check_content = text.replace(" ", "").upper()
            if card_number and check_content == card_number:
                continue
            
            # Skip if contains numbers
            if re.search(r'\d', check_content):
                continue
            
            # Skip if contains Japanese characters
            if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', check_content):
                continue
            
            # Skip known non-name words
            # For single words: exact match against skip words
            # For multi-word texts: only skip if it matches a skip phrase
            # This allows names like "MONICA STAY" to pass while blocking "STAY" alone
            text_upper = text.upper().strip()
            text_words = text_upper.split()
            
            if len(text_words) == 1:
                # Single word - exact match
                if text_upper in self.SKIP_WORDS:
                    logger.warning(f"    SKIP '{text}': exact skip word")
                    continue
            else:
                # Multi-word - only skip if matches a known phrase
                if any(phrase in text_upper for phrase in self.SKIP_PHRASES):
                    logger.warning(f"    SKIP '{text}': matches skip phrase")
                    continue
            
            # Must be mostly letters (name-like)
            letter_count = sum(1 for c in check_content if c.isalpha())
            if letter_count < 3:
                logger.warning(f"    SKIP '{text}': too short")
                continue
            letter_ratio = letter_count / max(len(check_content), 1)
            if letter_ratio < 0.8:
                logger.warning(f"    SKIP '{text}': low letter ratio")
                continue
            
            # Valid candidate - store with Y and X position for sorting and merging
            name_candidates.append({
                'text': text.upper(),
                'y': y,
                'x': x,
                'length': len(text)
            })
            logger.warning(f"  >>> CANDIDATE: '{text}' at y={y:.0f}, x={x:.0f}")
        
        if not name_candidates:
            logger.warning("No name candidates found in position-based search!")
            logger.info(f"  Total blocks analyzed: {len(blocks_with_position)}")
            return {}
        
        # Step 5: Group candidates by similar Y position (same line) and merge them
        # This handles cases where first name and last name are detected as separate blocks
        name_candidates.sort(key=lambda c: (c['y'], c['x']))
        
        # Group candidates by Y position (within line threshold)
        line_groups = []
        current_group = [name_candidates[0]]
        current_y = name_candidates[0]['y']
        
        for candidate in name_candidates[1:]:
            # If Y difference is within threshold, same line
            if abs(candidate['y'] - current_y) <= self.line_grouping_threshold:
                current_group.append(candidate)
            else:
                # Start new line group
                line_groups.append(current_group)
                current_group = [candidate]
                current_y = candidate['y']
        
        # Don't forget the last group
        if current_group:
            line_groups.append(current_group)
        
        # Log grouped candidates for debugging
        logger.warning(f"  Name groups: {len(line_groups)} line(s)")
        for i, group in enumerate(line_groups):
            texts = [c['text'] for c in group]
            logger.warning(f"    Line {i}: {texts}")
        
        # Take the first line group (topmost) and merge all text blocks
        # Sort by X position to get correct left-to-right order
        first_line = line_groups[0]
        first_line.sort(key=lambda c: c['x'])
        
        # Merge all text blocks on this line into the full name
        best_name = " ".join(c['text'] for c in first_line)
        
        # Clean up multiple spaces
        best_name = " ".join(best_name.split())
        
        logger.info(f"Position-based name detection: '{best_name}' (merged from {len(first_line)} blocks)")
        
        return {"name": best_name}
    
    def _extract_nationality_by_position(self, ocr_results: List[Tuple]) -> Dict[str, str]:
        """
        Extract nationality using position-based detection for Zairyu cards.
        
        The nationality on a Zairyu card is:
        - In the middle area (20-50% vertically from top)
        - Usually on the left side
        - Near the DOB/gender line
        - Contains katakana (Japanese) country names
        
        Args:
            ocr_results: List of (bbox, text, confidence) tuples
            
        Returns:
            Dict with 'nationality' key if found
        """
        if not ocr_results:
            return {}
        
        # Step 1: Extract blocks with valid bboxes and calculate card boundaries
        blocks_with_position = []
        all_y_coords = []
        all_x_coords = []
        
        for result in ocr_results:
            bbox, text, confidence = result[0], result[1], result[2] if len(result) > 2 else 0.0
            if not bbox or not text:
                continue
            
            # Get Y and X coordinates from bbox
            try:
                if isinstance(bbox[0], (list, tuple)):
                    y_coord = float(bbox[0][1])
                    x_coord = float(bbox[0][0])
                    x_right = float(bbox[1][0]) if len(bbox) > 1 else x_coord
                else:
                    y_coord = float(bbox[1])
                    x_coord = float(bbox[0])
                    x_right = float(bbox[2]) if len(bbox) > 2 else x_coord
                
                all_y_coords.append(y_coord)
                all_x_coords.append(x_coord)
                all_x_coords.append(x_right)
                
                blocks_with_position.append({
                    'text': text.strip(),
                    'y': y_coord,
                    'x': x_coord,
                    'x_right': x_right,
                    'confidence': confidence
                })
            except (IndexError, TypeError, ValueError):
                continue
        
        if not blocks_with_position or not all_y_coords:
            return {}
        
        # Step 2: Calculate card boundaries
        card_top = min(all_y_coords)
        card_bottom = max(all_y_coords)
        card_left = min(all_x_coords)
        card_right = max(all_x_coords)
        card_height = card_bottom - card_top
        card_width = card_right - card_left
        
        if card_height <= 0 or card_width <= 0:
            return {}
        
        # Step 3: Define nationality zone (15-55% vertically, left 80% of card)
        # Nationality is typically below the name but in the upper-middle area
        nationality_zone_top = card_top + card_height * 0.15
        nationality_zone_bottom = card_top + card_height * 0.55
        nationality_zone_right = card_left + card_width * 0.80
        
        logger.warning(f"  Nationality zone: y {nationality_zone_top:.0f}-{nationality_zone_bottom:.0f}, x < {nationality_zone_right:.0f}")
        
        # Step 4: Search for nationality in the zone
        for block in blocks_with_position:
            text = block['text']
            y = block['y']
            x = block['x']
            
            # Check if in nationality zone
            if y < nationality_zone_top or y > nationality_zone_bottom:
                continue
            if x > nationality_zone_right:
                continue
            
            # Check against known nationalities
            for nationality in self.NATIONALITIES:
                if nationality in text:
                    logger.warning(f"  Position-based nationality found: '{nationality}' in '{text}' at y={y:.0f}, x={x:.0f}")
                    return {"nationality": nationality}
            
            # Also log what we're checking for debugging
            logger.warning(f"  Checking block in zone: '{text}' at y={y:.0f}, x={x:.0f}")
        
        logger.warning("  Position-based nationality: NOT FOUND")
        return {}
    
    def _extract_dob_gender_nationality(self, text_lines: List[str], 
                                         full_text: str) -> Dict[str, str]:
        """Extract date of birth, gender, and nationality"""
        result = {}
        
        # Date pattern: YYYY年MM月DD日
        dob_pattern = r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日月]'
        
        logger.warning("=== EXTRACTING DOB/GENDER/NATIONALITY ===")
        logger.warning(f"  Searching in {len(text_lines)} lines")
        
        # First, find DOB line
        for i, line in enumerate(text_lines):
            dob_match = re.search(dob_pattern, line)
            if dob_match:
                year = dob_match.group(1)
                month = dob_match.group(2).zfill(2)
                day = dob_match.group(3).zfill(2)
                result["date_of_birth"] = f"{year}-{month}-{day}"
                logger.warning(f"  DOB found in line {i}: {result['date_of_birth']}")
                
                # Extract gender from same line or nearby
                if '女' in line or 'F.' in line or 'F .' in line:
                    result["gender"] = "女"
                    result["gender_en"] = "Female"
                    logger.warning(f"  Gender found in DOB line: Female")
                elif '男' in line or 'M.' in line or 'M .' in line:
                    result["gender"] = "男"
                    result["gender_en"] = "Male"
                    logger.warning(f"  Gender found in DOB line: Male")
                
                # Extract nationality from same line
                for nationality in self.NATIONALITIES:
                    if nationality in line:
                        result["nationality"] = nationality
                        logger.warning(f"  Nationality found in DOB line: {nationality}")
                        break
                
                # If nationality not in DOB line, check adjacent lines (DOB line ± 1)
                if "nationality" not in result:
                    logger.warning(f"  Nationality NOT in DOB line, checking adjacent lines...")
                    # Check line before DOB (if exists)
                    if i > 0:
                        prev_line = text_lines[i - 1]
                        for nationality in self.NATIONALITIES:
                            if nationality in prev_line:
                                result["nationality"] = nationality
                                logger.warning(f"  Nationality found in line {i-1} (before DOB): {nationality}")
                                break
                    
                    # Check line after DOB (if exists)
                    if "nationality" not in result and i + 1 < len(text_lines):
                        next_line = text_lines[i + 1]
                        for nationality in self.NATIONALITIES:
                            if nationality in next_line:
                                result["nationality"] = nationality
                                logger.warning(f"  Nationality found in line {i+1} (after DOB): {nationality}")
                                break
                
                break
        
        # If nationality not found in DOB line or adjacent, search all text
        if "nationality" not in result:
            logger.warning(f"  Nationality NOT found near DOB, searching full text...")
            logger.warning(f"  Full text preview: {full_text[:200]}...")
            for nationality in self.NATIONALITIES:
                if nationality in full_text:
                    result["nationality"] = nationality
                    logger.warning(f"  Nationality found in full text: {nationality}")
                    break
            if "nationality" not in result:
                logger.warning(f"  Nationality NOT FOUND anywhere!")
        
        # If gender not found, search all text
        if "gender" not in result:
            if '女' in full_text:
                result["gender"] = "女"
                result["gender_en"] = "Female"
                logger.warning(f"  Gender found in full text: Female")
            elif '男' in full_text:
                result["gender"] = "男"
                result["gender_en"] = "Male"
                logger.warning(f"  Gender found in full text: Male")
        
        logger.warning(f"  Final DOB/Gender/Nationality result: {result}")
        return result
    
    def _extract_period_and_expiry(self, text_lines: List[str], 
                                    full_text: str) -> Dict[str, str]:
        """Extract period of stay and expiration date"""
        result = {}
        
        # Pattern for period: X年Y月 or X年
        period_pattern = r'(\d{1,2})\s*年\s*(?:(\d{1,2})\s*月)?'
        
        # Pattern for expiry in parentheses: (YYYY年MM月DD日)
        expiry_paren_pattern = r'[（\(]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日月]\s*[）\)]'
        
        # Look for period with expiry in parentheses
        for line in text_lines:
            # Check for expiry in parentheses
            expiry_match = re.search(expiry_paren_pattern, line)
            if expiry_match:
                year = expiry_match.group(1)
                month = expiry_match.group(2).zfill(2)
                day = expiry_match.group(3).zfill(2)
                result["expiration_date"] = f"{year}年{month}月{day}日"
                
                # Also extract period before the parentheses
                before_paren = line[:expiry_match.start()]
                period_match = re.search(period_pattern, before_paren)
                if period_match:
                    years = period_match.group(1)
                    months = period_match.group(2)
                    if months:
                        result["period_of_stay"] = f"{years}年{months}月"
                    else:
                        result["period_of_stay"] = f"{years}年"
                
                break
        
        # Fallback: look for "まで有効" pattern
        if "expiration_date" not in result:
            valid_pattern = r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*まで\s*有効'
            match = re.search(valid_pattern, full_text)
            if match:
                year = match.group(1)
                month = match.group(2).zfill(2)
                day = match.group(3).zfill(2)
                result["expiration_date"] = f"{year}年{month}月{day}日"
        
        # Additional fallback for expiry date
        if "expiration_date" not in result:
            # Look for any 4-digit year date that's not DOB
            date_pattern = r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日'
            matches = re.findall(date_pattern, full_text)
            if len(matches) >= 2:
                # Take the later date as expiry
                dates = []
                for m in matches:
                    try:
                        year = int(m[0])
                        month = int(m[1])
                        day = int(m[2])
                        dates.append((year, month, day, f"{m[0]}年{m[1].zfill(2)}月{m[2].zfill(2)}日"))
                    except:
                        continue
                
                if dates:
                    dates.sort(reverse=True)
                    result["expiration_date"] = dates[0][3]
        
        # Extract period if not found
        if "period_of_stay" not in result:
            # Look for standalone period (not part of date)
            for line in text_lines:
                # Skip lines with full dates
                if re.search(r'\d{4}\s*年', line):
                    # But check for period pattern before or after
                    period_match = re.search(r'(?<!\d)(\d{1,2})\s*年\s*(\d{1,2})\s*月(?!\d)', line)
                    if period_match:
                        result["period_of_stay"] = f"{period_match.group(1)}年{period_match.group(2)}月"
                        break
        
        return result
    
    def _extract_status(self, text_lines: List[str], full_text: str) -> Dict[str, str]:
        """Extract status of residence"""
        
        # First look for exact matches
        for status in self.RESIDENCE_STATUSES:
            if status in full_text:
                result = {"status_of_residence": status}
                
                # Map to English
                status_en_map = {
                    '留学': 'Student',
                    '技能実習': 'Technical Intern Training',
                    '技術・人文知識・国際業務': 'Engineer/Specialist in Humanities/Int\'l Services',
                    '家族滞在': 'Dependent',
                    '永住者': 'Permanent Resident',
                    '定住者': 'Long-term Resident',
                    '特定技能': 'Specified Skilled Worker',
                    '経営・管理': 'Business Manager',
                    '高度専門職': 'Highly Skilled Professional',
                }
                if status in status_en_map:
                    result["status_of_residence_en"] = status_en_map[status]
                
                return result
        
        # Check for "Student" in English
        if re.search(r'\bStudent\b', full_text, re.IGNORECASE):
            return {"status_of_residence": "留学", "status_of_residence_en": "Student"}
        
        return {}
    
    def _extract_address(self, text_lines: List[str], full_text: str) -> Dict[str, str]:
        """Extract address (Japanese prefecture/city pattern)"""
        
        # Prefecture patterns
        prefecture_pattern = r'(東京都|北海道|(?:京都|大阪)府|.{2,3}県)'
        city_pattern = r'(.+?[市区町村])'
        
        for line in text_lines:
            # Skip lines with dates
            if re.search(r'\d{4}\s*年', line):
                continue
            
            # Check for prefecture
            pref_match = re.search(prefecture_pattern, line)
            if pref_match:
                # Try to get the full address from this line
                address = line.strip()
                
                # Clean up unwanted parts
                address = re.sub(r'住居地\s*[:：]?\s*', '', address)
                address = re.sub(r'^\s*[A-Za-z\s]+\s*', '', address)  # Remove English prefix
                
                if address:
                    return {"address": address}
        
        return {}
    
    def _extract_work_permission(self, full_text: str) -> Dict[str, str]:
        """Extract work permission status"""
        
        if '就労不可' in full_text:
            return {
                "work_permission": "就労不可",
                "work_permission_en": "No work permitted"
            }
        elif '就労制限なし' in full_text:
            return {
                "work_permission": "就労制限なし",
                "work_permission_en": "No work restriction"
            }
        elif '指定書' in full_text:
            return {
                "work_permission": "指定書により指定",
                "work_permission_en": "As designated"
            }
        elif '就労可' in full_text:
            return {
                "work_permission": "就労可",
                "work_permission_en": "Work permitted"
            }
        
        return {}


# Convenience function
def parse_zairyu_ocr(ocr_result: OCRResult) -> Dict[str, str]:
    """Parse Zairyu card OCR result into structured fields"""
    parser = ZairyuCardParser()
    return parser.parse(ocr_result)
