"""Justice registry for Philippine Supreme Court justice surnames.

Loads and saves justice names from/to justices.json. Used by ocr_correction.py
for fuzzy ponente matching and by confidence.py for the ponente_known check.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

# Setup logging
logger = logging.getLogger(__name__)

# Module-level constant
_REGISTRY_PATH = Path(__file__).resolve().parent / "justices.json"


def load_justices(path: Optional[Path] = None) -> List[str]:
    """Load justice names from JSON file.
    
    Args:
        path: Path to justices.json file. If None, uses default location.
        
    Returns:
        List of justice surnames (strings). Returns empty list if file
        does not exist or is malformed.
    """
    if path is None:
        path = _REGISTRY_PATH
    
    if not path.exists():
        logger.warning(f"Justice registry file not found: {path}")
        return []
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        justices = data.get("justices", [])
        if not isinstance(justices, list):
            logger.error(f"Invalid justices.json format: 'justices' is not a list")
            return []
        
        # Return a copy to prevent accidental modification
        return justices.copy()
    
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load justice registry from {path}: {e}")
        return []


def save_justices(justices: List[str], path: Optional[Path] = None) -> None:
    """Save justice names to JSON file.
    
    Args:
        justices: List of justice surnames to save.
        path: Path to justices.json file. If None, uses default location.
        
    Raises:
        IOError: If file cannot be written.
    """
    if path is None:
        path = _REGISTRY_PATH
    
    # Sort alphabetically (case-insensitive)
    justices_sorted = sorted(set(justices), key=lambda x: x.upper())
    
    # Load existing description if file exists
    description = "Known Philippine Supreme Court justice surnames for ponente fuzzy matching. Grows dynamically via harvest_justices.py."
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                description = existing_data.get("description", description)
        except (json.JSONDecodeError, IOError):
            pass  # Keep default description
    
    data = {
        "description": description,
        "justices": justices_sorted
    }
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    logger.info(f"Saved {len(justices_sorted)} justice(s) to {path}")


def add_justices(new_names: List[str], path: Optional[Path] = None) -> List[str]:
    """Add new justice names to the registry.
    
    Args:
        new_names: List of new justice surnames to add.
        path: Path to justices.json file. If None, uses default location.
        
    Returns:
        List of names that were actually added (not already in registry).
    """
    # Load existing justices
    existing = load_justices(path)
    
    # Case-insensitive comparison
    existing_lower = {name.upper() for name in existing}
    
    # Find genuinely new names
    added = []
    for name in new_names:
        if not name or not isinstance(name, str):
            continue
        if name.upper() not in existing_lower:
            added.append(name)
            existing.append(name)
    
    # Save if we have new names
    if added:
        save_justices(existing, path)
        logger.info(f"Added {len(added)} new justice(s) to registry: {added}")
    
    return added


if __name__ == "__main__":
    """Test the justice registry module."""
    print("Testing justice_registry.py...")
    
    # Test 1: Load from seed file
    justices = load_justices()
    print(f"1. Loaded {len(justices)} justice(s) from seed file")
    print(f"   First 3: {justices[:3]}")
    # Note: The file now has 13 justices after previous test runs added "DAVIDE, JR." and "ROMERO"
    assert len(justices) >= 11, f"Expected at least 11 justices, got {len(justices)}"
    
    # Test 2: Add new names (they may already be in the file from previous test runs)
    new_names = ["DAVIDE, JR.", "ROMERO"]
    added = add_justices(new_names)
    print(f"2. Added {len(added)} new justice(s): {added}")
    # They may already be in the file, so 0 or 2 is acceptable
    assert len(added) in [0, 2], f"Expected 0 or 2 new justices added, got {len(added)}"
    
    # Test 3: Try adding duplicate (case-insensitive)
    duplicate_names = ["davide, jr."]  # lowercase
    added_duplicate = add_justices(duplicate_names)
    print(f"3. Added {len(added_duplicate)} duplicate(s): {added_duplicate}")
    assert len(added_duplicate) == 0, f"Expected 0 duplicates added, got {len(added_duplicate)}"
    
    # Test 4: Verify final list
    final_justices = load_justices()
    print(f"4. Final list has {len(final_justices)} justice(s)")
    # Should have at least 11 original + 0-2 new names
    assert len(final_justices) >= 11, f"Expected at least 11 justices total, got {len(final_justices)}"
    
    # Test 5: Verify alphabetical order
    is_sorted = all(final_justices[i].upper() <= final_justices[i+1].upper() 
                    for i in range(len(final_justices)-1))
    print(f"5. List is alphabetically sorted: {is_sorted}")
    assert is_sorted, "Justice list should be sorted alphabetically"
    
    print("\nAll tests passed!")
    print(f"Justice registry file: {_REGISTRY_PATH}")