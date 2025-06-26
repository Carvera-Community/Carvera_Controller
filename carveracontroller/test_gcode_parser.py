"""
Test script for the GCode Parser Class

This script demonstrates how to use the GCodeParser class with example GCode.
"""

from GCodeParser import GCodeParser


def test_gcode_parser():
    """Test the GCode parser with example GCode."""
    
    # Example GCode with various commands
    example_gcode = """
; Example GCode file for testing
G21 ; Set units to mm
G90 ; Absolute positioning
G28 ; Home all axes

; Tool change
M6 T1 ; Change to tool 1

; Spindle on
M3 S1000 ; Spindle on at 1000 RPM

; Move to starting position
G0 X0 Y0 Z5

; Start cutting
G1 Z-1 F100 ; Plunge
G1 X10 Y10 F500 ; Linear move

; Incremental movement
G91 ; Switch to incremental mode
G1 X5 Y5 ; Incremental move
G90 ; Back to absolute mode

; Another tool change
M6 T2 ; Change to tool 2

; Another spindle command
M3 S2000 ; Spindle on at 2000 RPM

; More cutting
G1 X20 Y20 F300

; End program
M5 ; Spindle off
M30 ; Program end
"""

    # Create parser instance
    parser = GCodeParser()
    
    # Load the GCode
    parser.load_gcode(example_gcode)
    
    print(f"Loaded {parser.get_line_count()} GCode lines")
    print()
    
    # Test incremental movement detection
    has_incremental = parser.has_incremental_movements()
    print(f"Has incremental movements: {has_incremental}")
    print()
    
    # Test finding M3 commands backwards from different positions
    print("Finding M3 commands backwards:")
    for line_num in [15, 20, 25]:
        m3_line = parser.find_closest_m3_backwards(line_num)
        if m3_line:
            print(f"  From line {line_num}: M3 found at line {m3_line}")
            print(f"    Command: {parser.get_line(m3_line)}")
        else:
            print(f"  From line {line_num}: No M3 found")
    print()
    
    # Test finding M6 commands backwards from different positions
    print("Finding M6 commands backwards:")
    for line_num in [15, 20, 25]:
        m6_line = parser.find_closest_m6_backwards(line_num)
        if m6_line:
            print(f"  From line {line_num}: M6 found at line {m6_line}")
            print(f"    Command: {parser.get_line(m6_line)}")
        else:
            print(f"  From line {line_num}: No M6 found")
    print()
    
    # Display all parsed lines
    print("All parsed GCode lines:")
    for i, line_num in enumerate(parser.line_numbers):
        parsed = parser._parsed_lines[i]
        print(f"  Line {line_num}: {parsed['original']}")
        if parsed['g_codes']:
            print(f"    G-codes: {parsed['g_codes']}")
        if parsed['m_codes']:
            print(f"    M-codes: {parsed['m_codes']}")
        if parsed['coordinates']:
            print(f"    Coordinates: {parsed['coordinates']}")
        if parsed['is_incremental']:
            print(f"    Incremental mode: True")


if __name__ == "__main__":
    test_gcode_parser()