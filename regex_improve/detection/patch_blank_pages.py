import re
import sys
import json
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime


def find_blank_pages(txt_path: Path) -> list[int]:
    """
    Find blank pages in a text file.
    
    A blank page is identified by consecutive --- Page N --- markers with
    no text between them (or only whitespace).
    
    Args:
        txt_path: Path to the text file
        
    Returns:
        List of blank page numbers (1-based, matching the --- Page N --- format)
    """
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all page markers
    page_markers = list(re.finditer(r'^--- Page (\d+) ---$', content, re.MULTILINE))
    
    if not page_markers:
        return []
    
    blank_pages = []
    total_pages = len(page_markers)
    
    # Check each page (except the last one)
    for i in range(len(page_markers) - 1):
        page_match = page_markers[i]
        next_match = page_markers[i + 1]
        
        page_num = int(page_match.group(1))
        
        # Skip front/back matter (pages 1-10 and last 10 pages)
        if page_num <= 10 or page_num > total_pages - 10:
            continue
        
        # Get content between markers
        start_pos = page_match.end()
        end_pos = next_match.start()
        page_content = content[start_pos:end_pos].strip()
        
        # If content is empty or whitespace-only, it's blank
        if not page_content:
            blank_pages.append(page_num)
    
    return blank_pages


def preprocess_image(pil_image):
    """
    Preprocess a scanned page image to improve OCR accuracy.
    CPU-only version matching the one in 02_processor.ipynb.
    
    Steps: denoise (median filter) → contrast stretch → adaptive binarization → sharpen
    """
    import cv2
    import numpy as np
    from PIL import Image
    
    # Convert PIL → numpy array (already grayscale from convert_from_path)
    img = np.array(pil_image, dtype=np.uint8)
    
    # CPU processing (no GPU)
    img = cv2.medianBlur(img, 3)
    p2, p98 = np.percentile(img, (2, 98))
    scale = max(float(p98 - p2), 1.0)
    img = np.clip((img.astype(np.float32) - p2) * 255.0 / scale, 0, 255).astype(np.uint8)
    
    # Adaptive threshold (Gaussian)
    img = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 31, 15)
    
    # Mild unsharp mask (sharpen text edges)
    blurred = cv2.GaussianBlur(img, (0, 0), 1.0)
    img = cv2.addWeighted(img, 1.5, blurred, -0.5, 0)
    
    return Image.fromarray(img)


def reocr_pages(pdf_path: Path, page_numbers: list[int], dpi: int = 300, min_chars: int = 10) -> dict[int, str]:
    """
    Re-OCR specific pages from a PDF using multi-strategy approach.
    
    Args:
        pdf_path: Path to the PDF file
        page_numbers: List of page numbers to re-OCR (1-based)
        dpi: OCR DPI resolution
        min_chars: Minimum characters for a page to be considered non-blank
        
    Returns:
        Dictionary mapping page_number -> extracted_text
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        logging.error("pdf2image not installed. Install with: pip install pdf2image")
        return {}
    
    try:
        import pytesseract
    except ImportError:
        logging.error("pytesseract not installed. Install with: pip install pytesseract")
        return {}
    
    # Check cv2 availability once
    try:
        import cv2
        has_cv2 = True
    except ImportError:
        has_cv2 = False
        logging.warning("cv2 not installed — skipping preprocessed OCR strategy")
    
    page_texts = {}
    
    for page_num in page_numbers:
        try:
            # Convert just this page at default DPI
            images = convert_from_path(
                pdf_path,
                dpi=dpi,
                first_page=page_num,
                last_page=page_num,
                grayscale=True
            )
            
            if not images:
                logging.warning(f"Page {page_num}: No image generated from PDF")
                continue
            
            image = images[0]
            best_text = ""
            best_strategy = ""
            
            # Strategy 1: Raw OCR (no preprocessing)
            text = pytesseract.image_to_string(image)
            if len(text.strip()) >= min_chars:
                best_text = text
                best_strategy = "raw"
            
            # Strategy 2: Preprocessed OCR (if raw failed and cv2 available)
            if not best_text and has_cv2:
                processed = preprocess_image(image)
                text = pytesseract.image_to_string(processed)
                if len(text.strip()) >= min_chars:
                    best_text = text
                    best_strategy = "preprocessed"
            
            # Strategy 3: Higher DPI raw OCR (if still no text and DPI < 400)
            if not best_text and dpi < 400:
                hi_images = convert_from_path(
                    pdf_path,
                    dpi=400,
                    first_page=page_num,
                    last_page=page_num,
                    grayscale=True
                )
                if hi_images:
                    text = pytesseract.image_to_string(hi_images[0])
                    if len(text.strip()) >= min_chars:
                        best_text = text
                        best_strategy = "raw@400dpi"
            
            if best_text:
                page_texts[page_num] = best_text
                logging.info(f"Page {page_num}: {len(best_text.strip()):,} chars ({best_strategy})")
            else:
                logging.info(f"Page {page_num}: all strategies produced < {min_chars} chars")
            
        except Exception as e:
            logging.warning(f"Page {page_num}: re-OCR failed - {e}")
            continue
    
    return page_texts


def patch_text_file(txt_path: Path, page_texts: dict[int, str], 
                    min_chars: int = 10, backup: bool = True) -> dict:
    """
    Patch blank pages in a text file with re-OCR'd text.
    
    Args:
        txt_path: Path to the text file
        page_texts: Dictionary mapping page_number -> extracted_text
        min_chars: Minimum characters for a page to be considered non-blank
        backup: Whether to create a backup before patching
        
    Returns:
        Summary dictionary: {patched: int, still_blank: int, errors: int}
    """
    if backup:
        backup_path = txt_path.with_suffix('.txt.bak')
        shutil.copy2(txt_path, backup_path)
        logging.info(f"Created backup: {backup_path}")
    
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all page markers
    page_markers = list(re.finditer(r'^--- Page (\d+) ---$', content, re.MULTILINE))
    
    if not page_markers:
        logging.warning(f"No page markers found in {txt_path}")
        return {'patched': 0, 'still_blank': 0, 'errors': 0}
    
    # Build a mapping of page number to marker position
    marker_map = {}
    for match in page_markers:
        page_num = int(match.group(1))
        marker_map[page_num] = match
    
    summary = {'patched': 0, 'still_blank': 0, 'errors': 0}
    
    # Process pages in reverse order to avoid position shifting issues
    for page_num in sorted(page_texts.keys(), reverse=True):
        if page_num not in marker_map:
            logging.warning(f"Page {page_num}: Marker not found in file")
            summary['errors'] += 1
            continue
        
        marker_match = marker_map[page_num]
        marker_start = marker_match.start()
        marker_end = marker_match.end()
        
        # Find the next marker (if any)
        next_marker_start = None
        for next_page in sorted(marker_map.keys()):
            if next_page > page_num:
                next_marker_start = marker_map[next_page].start()
                break
        
        if next_marker_start is None:
            # This is the last page, use end of file
            next_marker_start = len(content)
        
        # Get the current content between markers
        current_content = content[marker_end:next_marker_start]
        
        # Check if we should patch this page
        text = page_texts[page_num]
        char_count = len(text.strip())
        
        if char_count >= min_chars:
            # Replace the content between markers
            new_content = f"\n{text}"
            if not text.endswith('\n'):
                new_content += '\n'
            
            # Update the content
            content = content[:marker_end] + new_content + content[next_marker_start:]
            summary['patched'] += 1
            logging.info(f"Page {page_num}: {char_count:,} chars -> PATCHED")
        else:
            summary['still_blank'] += 1
            logging.info(f"Page {page_num}: {char_count:,} chars -> still blank (genuine)")
    
    # Write the patched content back
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return summary


def scan_and_report(input_path: Path, pdf_dir: Path) -> dict:
    """
    Scan for blank pages and report summary.
    
    Args:
        input_path: Path to a single .txt file or directory containing Volume_*.txt files
        pdf_dir: Directory containing original PDFs
        
    Returns:
        Summary dictionary with per-volume blank page counts
    """
    if input_path.is_file():
        txt_files = [input_path]
    else:
        txt_files = list(input_path.glob("Volume_*.txt"))
    
    summary = {}
    
    for txt_path in txt_files:
        blank_pages = find_blank_pages(txt_path)
        
        # Check if PDF exists
        pdf_name = txt_path.stem + ".pdf"
        pdf_path = pdf_dir / pdf_name
        
        pdf_exists = pdf_path.exists()
        
        summary[txt_path.name] = {
            'blank_pages': blank_pages,
            'blank_count': len(blank_pages),
            'pdf_exists': pdf_exists,
            'pdf_path': str(pdf_path) if pdf_exists else None
        }
    
    return summary


def print_dry_run_report(summary: dict):
    """Print human-readable dry-run report."""
    print("Blank Page Scan Report")
    print("=" * 40)
    
    total_blank = 0
    total_volumes = 0
    
    for filename, info in sorted(summary.items()):
        blank_count = info['blank_count']
        pdf_status = "found" if info['pdf_exists'] else "MISSING"
        
        print(f"{filename:20} {blank_count:4d} blank content pages  (PDF: {pdf_status})")
        
        total_blank += blank_count
        if blank_count > 0:
            total_volumes += 1
    
    print("-" * 40)
    print(f"Total: {total_blank} blank pages across {total_volumes} volumes")


def print_patch_summary(volume_summaries: dict):
    """Print summary of patching results."""
    total_patched = 0
    total_still_blank = 0
    total_errors = 0
    
    for filename, summary in volume_summaries.items():
        patched = summary.get('patched', 0)
        still_blank = summary.get('still_blank', 0)
        errors = summary.get('errors', 0)
        
        total_patched += patched
        total_still_blank += still_blank
        total_errors += errors
        
        print(f"{filename}: {patched} patched, {still_blank} still blank, {errors} errors")
    
    print("-" * 40)
    print(f"Overall: {total_patched} pages patched, {total_still_blank} still blank, {total_errors} errors")


def main():
    parser = argparse.ArgumentParser(
        description="Patch blank pages in OCR text files by re-OCR'ing from original PDFs"
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to a single Volume_NNN.txt OR a directory containing Volume_*.txt files"
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=None,
        help="Directory containing original PDFs (default: same as txt dir)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report blank pages without patching"
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="OCR DPI (default: 300)"
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=10,
        help="Minimum characters for a page to be considered non-blank after re-OCR (default: 10)"
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        default=True,
        help="Create .txt.bak backup before patching (default: True)"
    )
    parser.add_argument(
        "--no-backup",
        action="store_false",
        dest="backup",
        help="Skip backup creation"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()]
    )
    
    # Determine PDF directory
    if args.pdf_dir is None:
        if args.input.is_file():
            args.pdf_dir = args.input.parent
        else:
            args.pdf_dir = args.input
    
    # Check if input exists
    if not args.input.exists():
        logging.error(f"Input path does not exist: {args.input}")
        sys.exit(1)
    
    # Scan for blank pages
    summary = scan_and_report(args.input, args.pdf_dir)
    
    if args.dry_run:
        print_dry_run_report(summary)
        return
    
    # Process each volume
    volume_summaries = {}
    
    for filename, info in summary.items():
        blank_pages = info['blank_pages']
        blank_count = info['blank_count']
        
        if blank_count == 0:
            logging.info(f"{filename}: No blank pages, skipping")
            continue
        
        if not info['pdf_exists']:
            logging.warning(f"{filename}: PDF not found at {info['pdf_path']}, skipping")
            continue
        
        txt_path = args.input if args.input.is_file() else args.input / filename
        pdf_path = args.pdf_dir / (txt_path.stem + ".pdf")
        
        logging.info(f"Patching {filename} ({blank_count} blank pages)...")
        
        # Re-OCR blank pages
        page_texts = reocr_pages(pdf_path, blank_pages, dpi=args.dpi, min_chars=args.min_chars)
        
        if not page_texts:
            logging.warning(f"{filename}: No pages re-OCR'd successfully")
            volume_summaries[filename] = {'patched': 0, 'still_blank': blank_count, 'errors': 0}
            continue
        
        # Patch the text file
        patch_summary = patch_text_file(
            txt_path, page_texts, 
            min_chars=args.min_chars, 
            backup=args.backup
        )
        
        volume_summaries[filename] = patch_summary
    
    # Print final summary
    print_patch_summary(volume_summaries)


if __name__ == "__main__":
    main()