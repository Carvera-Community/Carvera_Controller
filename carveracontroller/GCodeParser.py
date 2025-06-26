"""
GCode Parser Class for Carvera Controller

This module provides a GCode parser class that can analyze GCode files
and perform various operations like detecting incremental movements
and finding specific M-code commands.
"""

import re
from typing import List, Optional, Tuple


class GCodeParser:
    """
    A GCode parser class for analyzing and processing GCode files.
    
    This class provides methods to:
    - Load GCode from a string
    - Check for incremental movements (G91)
    - Find M3 commands (spindle on) searching backwards
    - Find M6 commands (tool change) searching backwards
    """
    
    def __init__(self):
        """Initialize the GCode parser."""
        self.lines: List[str] = []
        self.line_numbers: List[int] = []
        self._parsed_lines: List[dict] = []
        
    def load_gcode(self, gcode_string: str) -> None:
        """
        Load GCode from a provided string into the parser.
        
        Args:
            gcode_string: The GCode content as a string
        """
        # Clear any existing data
        self.lines.clear()
        self.line_numbers.clear()
        self._parsed_lines.clear()
        
        # Split the string into lines and process each line
        raw_lines = gcode_string.split('\n')
        
        for line_num, line in enumerate(raw_lines, start=1):
            # Strip whitespace and skip empty lines
            stripped_line = line.strip()
            if not stripped_line:
                continue
                
            # Skip comments (lines starting with ; or ( or containing only comments)
            if stripped_line.startswith(';') or stripped_line.startswith('('):
                continue
                
            # Remove inline comments (everything after ; or between parentheses)
            # Remove comments between parentheses
            cleaned_line = re.sub(r'\([^)]*\)', '', stripped_line)
            # Remove inline comments starting with ;
            cleaned_line = re.sub(r';.*$', '', cleaned_line)
            cleaned_line = cleaned_line.strip()
            
            if not cleaned_line:
                continue
                
            # Store the cleaned line and its line number
            self.lines.append(cleaned_line)
            self.line_numbers.append(line_num)
            
            # Parse the line for easier access later
            self._parsed_lines.append(self._parse_gcode_line(cleaned_line))
    
    def _parse_gcode_line(self, line: str) -> dict:
        """
        Parse a single GCode line into a structured format.
        
        Args:
            line: The GCode line to parse
            
        Returns:
            Dictionary containing parsed GCode elements
        """
        result = {
            'original': line,
            'g_codes': [],
            'm_codes': [],
            'coordinates': {},
            'feed_rate': None,
            'spindle_speed': None,
            'tool_number': None,
            'is_incremental': False
        }
        
        # Split the line into words
        words = line.upper().split()
        
        for word in words:
            if not word:
                continue
                
            # Extract the command letter and value
            if len(word) >= 2:
                cmd_letter = word[0]
                cmd_value = word[1:]
                
                try:
                    # Handle different command types
                    if cmd_letter == 'G':
                        g_code = float(cmd_value)
                        result['g_codes'].append(g_code)
                        # Check for G91 (incremental mode)
                        if g_code == 91:
                            result['is_incremental'] = True
                            
                    elif cmd_letter == 'M':
                        m_code = float(cmd_value)
                        result['m_codes'].append(m_code)
                        
                    elif cmd_letter in ['X', 'Y', 'Z', 'A', 'B', 'C']:
                        result['coordinates'][cmd_letter] = float(cmd_value)
                        
                    elif cmd_letter == 'F':
                        result['feed_rate'] = float(cmd_value)
                        
                    elif cmd_letter == 'S':
                        result['spindle_speed'] = float(cmd_value)
                        
                    elif cmd_letter == 'T':
                        result['tool_number'] = int(cmd_value)
                        
                except (ValueError, TypeError):
                    # Skip invalid numeric values
                    continue
        
        return result
    
    def has_incremental_movements(self) -> bool:
        """
        Check if the GCode has any incremental movements (G91 commands).
        
        Returns:
            True if any G91 commands are found, False otherwise
        """
        for parsed_line in self._parsed_lines:
            if parsed_line['is_incremental']:
                return True
        return False
    
    def find_closest_m3_backwards(self, from_line_number: int) -> Optional[int]:
        """
        Find the closest M3 command searching backwards from a provided line number.
        
        Args:
            from_line_number: The line number to start searching backwards from
            
        Returns:
            The line number of the closest M3 command, or None if not found
        """
        # Find the index of the line number in our stored line numbers
        try:
            start_index = self.line_numbers.index(from_line_number)
        except ValueError:
            # If the line number is not found, start from the end
            start_index = len(self.line_numbers) - 1
        
        # Search backwards from the start index
        for i in range(start_index, -1, -1):
            parsed_line = self._parsed_lines[i]
            if 3.0 in parsed_line['m_codes']:
                return self.line_numbers[i]
        
        return None
    
    def find_closest_m6_backwards(self, from_line_number: int) -> Optional[int]:
        """
        Find the closest M6 command searching backwards from a provided line number.
        
        Args:
            from_line_number: The line number to start searching backwards from
            
        Returns:
            The line number of the closest M6 command, or None if not found
        """
        # Find the index of the line number in our stored line numbers
        try:
            start_index = self.line_numbers.index(from_line_number)
        except ValueError:
            # If the line number is not found, start from the end
            start_index = len(self.line_numbers) - 1
        
        # Search backwards from the start index
        for i in range(start_index, -1, -1):
            parsed_line = self._parsed_lines[i]
            if 6.0 in parsed_line['m_codes']:
                return self.line_numbers[i]
        
        return None
    
    def get_line_count(self) -> int:
        """
        Get the total number of parsed GCode lines.
        
        Returns:
            Number of GCode lines
        """
        return len(self.lines)
    
    def get_line(self, line_number: int) -> Optional[str]:
        """
        Get a specific line by its line number.
        
        Args:
            line_number: The line number to retrieve
            
        Returns:
            The GCode line content, or None if not found
        """
        try:
            index = self.line_numbers.index(line_number)
            return self.lines[index]
        except ValueError:
            return None
    
    def get_parsed_line(self, line_number: int) -> Optional[dict]:
        """
        Get the parsed data for a specific line number.
        
        Args:
            line_number: The line number to retrieve
            
        Returns:
            The parsed line data, or None if not found
        """
        try:
            index = self.line_numbers.index(line_number)
            return self._parsed_lines[index]
        except ValueError:
            return None
    
    def clear(self) -> None:
        """Clear all loaded GCode data."""
        self.lines.clear()
        self.line_numbers.clear()
        self._parsed_lines.clear() 