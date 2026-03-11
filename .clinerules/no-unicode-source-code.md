## Brief overview
This rule file provides guidelines for avoiding Unicode characters in source code to ensure Windows console compatibility. Windows console uses cp1252 encoding which cannot render most Unicode characters, causing UnicodeEncodeError crashes.

## No Unicode in source code
- NEVER use Unicode symbols (checkmarks, crosses, arrows, bullets, emoji, etc.) in Python files, log messages, or print statements
- Use ASCII alternatives: `[OK]`, `[FAIL]`, `[->]`, `[-]`, `[PASS]`, `[ERROR]`
- This applies to all source code files, test output, log messages, and console output

## Common Unicode characters to avoid
- Checkmarks: ✓ → Use `[OK]`
- Cross marks: ✗ → Use `[FAIL]`
- Arrows: → → Use `[->]`
- Bullets: • → Use `[-]`
- Emoji: ✅ ❌ etc. → Use `[PASS]` `[ERROR]`
- Any other non-ASCII Unicode symbols

## Windows console compatibility
- Windows console uses cp1252 encoding by default
- Most Unicode characters cannot be rendered in cp1252 encoding
- Attempting to print Unicode characters causes `UnicodeEncodeError: 'charmap' codec can't encode character` crashes
- Always test console output on Windows to ensure compatibility

## Examples
- **Incorrect**: `print("✓ Test passed")`
- **Correct**: `print("[OK] Test passed")`
- **Incorrect**: `print("Error: ✗")`
- **Correct**: `print("Error: [FAIL]")`
- **Incorrect**: `logger.info("Process completed • Success")`
- **Correct**: `logger.info("Process completed - Success")`

## Testing and verification
- Always test Python scripts on Windows console before deployment
- Use `python -c "print('test')"` to verify basic output works
- Check for any Unicode characters in source code using regex searches
- Consider using ASCII art or simple text alternatives for visual indicators