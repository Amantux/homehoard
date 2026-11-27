import os
import re
from pathlib import Path
import pytest

def get_repo_root():
    # Resolve the repo root from __file__ (Path(__file__).resolve().parents[2])
    # This assumes the file is at backend/tests/test_dependency_inventory.py
    return Path(__file__).resolve().parents[2]

def test_every_reference_is_inventoried():
    root = get_repo_root()
    doc_path = root / "docs/open-food-facts.md"
    test_file = Path(__file__).resolve()
    
    if not doc_path.exists():
        pytest.fail(f"Inventory document not found at {doc_path}")
        
    doc_content = doc_path.read_text()
    
    found_paths = set()
    
    # Walk backend/, frontend/src/, custom_components/
    search_dirs = ["backend", "frontend/src", "custom_components"]
    extensions = {".py", ".js", ".vue", ".json", ".yaml", ".yml"}
    skip_dirs = {"node_modules", ".git", "dist", "build"}
    skip_files = {"package-lock.json"}
    
    for sdir in search_dirs:
        dir_path = root / sdir
        if not dir_path.exists():
            continue
            
        for path in dir_path.rglob("*"):
            if path.suffix in extensions:
                # Check if any part of the path is in a skip dir
                if any(part in skip_dirs for part in path.parts):
                    continue
                if path.name in skip_files:
                    continue
                if path.resolve() == test_file:
                    continue
                
                try:
                    content = path.read_text(errors="ignore")
                    if "openfoodfacts" in content.lower():
                        # Store repo-relative path
                        found_paths.add(str(path.relative_to(root)))
                except Exception:
                    # Skip files that can't be read
                    pass

    # Exclude the inventory doc itself (though it's not in search_dirs, just for safety)
    found_paths.discard("docs/open-food-facts.md")
    
    missing = []
    for path in found_paths:
        if path not in doc_content:
            missing.append(path)
            
    if missing:
        pytest.fail(f"The following paths contain references to 'openfoodfacts' but are not listed in {doc_path.relative_to(root)}:\n" 
                    f"{', '.join(missing)}\n\nadd them to docs/open-food-facts.md (Call sites / Tests tables)")

def test_no_stale_paths():
    root = get_repo_root()
    doc_path = root / "docs/open-food-facts.md"
    if not doc_path.exists():
        pytest.fail(f"Inventory document not found at {doc_path}")
        
    doc_content = doc_path.read_text()
    
    # Parse backticked paths from Call sites and Tests tables
    paths = re.findall(r'`([^`\n]+)`', doc_content)
    
    stale = []
    for p in paths:
        # Skip URLs
        if "://" in p or p.startswith("http"):
            continue
        
        # Remove line number if present (e.g. path/to/file.py:54)
        clean_path = p.split(':')[0]
        
        # To avoid picking up JSON keys or other non-path markers,
        # we verify that it looks like a relative path starting from the repo root
        # and actually exists as a file or directory.
        # We check if it's in the search dirs or docs/
        is_repo_path = any(clean_path.startswith(d) for d in ["backend", "frontend", "custom_components", "docs"])
        
        if not is_repo_path:
            continue
            
        full_path = root / clean_path
        if not full_path.exists():
            stale.append(p)
            
    if stale:
        pytest.fail(f"The following paths listed in {doc_path.relative_to(root)} do not exist on disk:\n"
                    f"{', '.join(stale)}")

def test_doc_matches_the_wire_contract():
    root = get_repo_root()
    doc_path = root / "docs/open-food-facts.md"
    if not doc_path.exists():
        pytest.fail(f"Inventory document not found at {doc_path}")
        
    doc_content = doc_path.read_text()
    
    # Wire contract facts
    facts = [
        "world.openfoodfacts.org",
        "/api/v2/product/",
        "HomeHoard/1.0",
        "status",
    ]
    
    missing_facts = []
    for fact in facts:
        if fact not in doc_content:
            missing_facts.append(fact)
            
    # Special check for 6s timeout
    if not (re.search(r'6\s*s', doc_content) or "6 second" in doc_content.lower()):
        missing_facts.append("6 s timeout")
            
    if missing_facts:
        pytest.fail(f"The documentation at {doc_path.relative_to(root)} is missing wire contract facts: {', '.join(missing_facts)}")
        
    # Check if backend/app/services/barcode.py still contains the host literal
    barcode_py = root / "backend/app/services/barcode.py"
    if not barcode_py.exists():
        pytest.fail(f"Expected file {barcode_py.relative_to(root)} does not exist")
        
    if "world.openfoodfacts.org" not in barcode_py.read_text():
        pytest.fail(f"The host literal 'world.openfoodfacts.org' was not found in {barcode_py.relative_to(root)}")
