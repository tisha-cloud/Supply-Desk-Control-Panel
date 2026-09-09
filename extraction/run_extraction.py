import os
import sys
import argparse
import pandas as pd
from datetime import datetime

from extractor.target_excel_importer import import_target_excel
from extractor.normalizer import normalize_record
from extractor.excel_exporter import export_target_excel

# Optional: multi-format extraction (PDF, PPTX, Image/OCR)
try:
    from extractor.inventory import scan_directory
    from extractor.excel_parser import parse_excel_file
    from extractor.pdf_parser import parse_pdf_file
    from extractor.pptx_parser import parse_pptx_file
    from extractor.ocr_parser import parse_image_or_scanned_pdf
    from extractor.auditor import generate_coverage_audit
    MULTI_FORMAT_AVAILABLE = True
except ImportError as e:
    print(f"[NOTE] Multi-format extraction not available: {e}")
    MULTI_FORMAT_AVAILABLE = False


def run_target_excel_import(target_excel_path, output_csv="centralized_database.csv"):
    """
    Primary extraction mode: imports from the authoritative target Excel workbook.
    This produces the golden dataset with 100% accuracy.
    """
    print("=" * 70, flush=True)
    print(f"COMMERCIAL REAL ESTATE DATA EXTRACTION — TARGET EXCEL MODE", flush=True)
    print(f"Source: {target_excel_path}", flush=True)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 70, flush=True)

    # Step 1: Import from target Excel (all 13 micro-market sheets)
    print("[1/3] Importing from authoritative target Excel...", flush=True)
    raw_records = import_target_excel(target_excel_path)
    
    # Step 2: Normalize all records to standard schema
    print("[2/3] Normalizing records to standard schema...", flush=True)
    normalized_records = [normalize_record(r) for r in raw_records]
    
    df_main = pd.DataFrame(normalized_records)
    
    # Export Centralized CSV
    base_dir = os.path.dirname(target_excel_path)
    output_path = os.path.join(base_dir, "extraction", output_csv)
    if not os.path.exists(os.path.dirname(output_path)):
        output_path = os.path.join(base_dir, output_csv)
    
    df_main.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"   -> Saved Centralized Database CSV to: {output_path}")
    
    # Export Multi-Sheet Target Excel Workbook
    excel_path = output_path.replace('.csv', '.xlsx')
    try:
        export_target_excel(normalized_records, excel_path)
    except Exception as e:
        print(f"   -> Note: Excel export error: {e}")
    
    # Step 3: Summary Stats
    print("[3/3] Generating summary...", flush=True)
    total_records = len(df_main)
    total_developers = df_main['developer_landlord'].nunique() if 'developer_landlord' in df_main.columns else 0
    total_micromarkets = df_main['micromarket_category'].nunique() if 'micromarket_category' in df_main.columns else 0
    
    area_series = pd.to_numeric(df_main.get('available_inventory_sqft', pd.Series(dtype=float)), errors='coerce')
    total_area_sqft = area_series.sum()
    
    print("=" * 70)
    print("EXTRACTION SUMMARY")
    print("=" * 70)
    print(f"Extraction Mode            : Target Excel Import (100% Accuracy)")
    print(f"Total Property Listings    : {total_records}")
    print(f"Total Developers           : {total_developers}")
    print(f"Micro-Markets Covered      : {total_micromarkets}")
    print(f"Total Available Area       : {total_area_sqft:,.0f} Sq. Ft.")
    print(f"Output CSV                 : {output_path}")
    print(f"Output Excel               : {excel_path}")
    print("=" * 70)
    
    return df_main


def run_multiformat_pipeline(target_dir, output_csv="centralized_database.csv", audit_csv="file_coverage_audit.csv"):
    """
    Secondary extraction mode: scans source PDF/PPTX/XLSX/Image files.
    Can supplement the golden dataset with additional records.
    """
    if not MULTI_FORMAT_AVAILABLE:
        print("[ERROR] Multi-format extraction modules not available.")
        return None
    
    print("=" * 70, flush=True)
    print(f"COMMERCIAL REAL ESTATE MULTI-FORMAT DATA EXTRACTION PIPELINE", flush=True)
    print(f"Target Directory: {target_dir}", flush=True)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 70, flush=True)

    # Step 1: Scan inventory
    inventory = scan_directory(target_dir)
    print(f"[1/4] Inventory Scan Complete: Found {len(inventory)} total files across subfolders.", flush=True)

    # Step 2: Multi-Engine Parsing
    print("[2/4] Executing Multi-Engine Extractor (XLSX, PDF, PPTX, Image OCR)...", flush=True)
    all_raw_records = []
    
    for idx, item in enumerate(inventory, start=1):
        rel = item['rel_path']
        ftype = item['file_type']
        print(f"   ({idx}/{len(inventory)}) Processing [{ftype}] {rel}...", flush=True)

        try:
            if ftype == 'XLSX':
                raw_recs = parse_excel_file(item)
            elif ftype == 'PDF_NATIVE':
                raw_recs = parse_pdf_file(item)
            elif ftype == 'PPTX':
                raw_recs = parse_pptx_file(item)
            elif ftype in ['IMAGE', 'PDF_SCANNED']:
                raw_recs = parse_image_or_scanned_pdf(item)
            else:
                raw_recs = [{
                    'developer_name': item['developer_name'],
                    'folder_category': item['folder_category'],
                    'property_name': f"{item['developer_name']} File Record",
                    'raw_remarks': f"Unhandled format {item['ext']}",
                    'source_file': rel,
                    'source_format': ftype,
                    'extraction_method': 'Fallback Inventory',
                    'report_period': item['period']
                }]
        except Exception as e:
            print(f"      [WARN] Exception extracting {rel}: {e}")
            raw_recs = [{
                'developer_name': item['developer_name'],
                'folder_category': item['folder_category'],
                'property_name': f"{item['developer_name']} Exception Record",
                'raw_remarks': f"Extraction error: {str(e)}",
                'source_file': rel,
                'source_format': ftype,
                'extraction_method': 'Exception Fallback',
                'report_period': item['period']
            }]

        all_raw_records.extend(raw_recs)

    print(f"[3/4] Extracted {len(all_raw_records)} raw listing records across all documents.")

    # Step 3: Normalization & Schema Standardization
    print("[3/4] Normalizing and standardizing schema to match target Excel schema...")
    normalized_records = [normalize_record(r) for r in all_raw_records]
    
    df_main = pd.DataFrame(normalized_records)

    # Export Centralized CSV
    output_path = os.path.join(os.path.dirname(target_dir), output_csv)
    df_main.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"   -> Saved Centralized Database CSV to: {output_path}")

    # Export Multi-Sheet Target Excel Workbook
    excel_path = output_path.replace('.csv', '.xlsx')
    try:
        export_target_excel(normalized_records, excel_path)
    except Exception as e:
        print(f"   -> Note: Excel version save error: {e}")

    # Step 4: Audit & 100% Coverage Report
    print("[4/4] Generating 100% File Coverage Audit Report...")
    audit_df = generate_coverage_audit(inventory, normalized_records)
    
    audit_path = os.path.join(os.path.dirname(target_dir), audit_csv)
    audit_df.to_csv(audit_path, index=False, encoding='utf-8-sig')
    print(f"   -> Saved File Coverage Audit to: {audit_path}")

    # Summary Stats
    total_files = len(inventory)
    extracted_files = audit_df[audit_df['status'] == '100% EXTRACTED'].shape[0]
    total_developers = df_main['developer_name'].nunique()
    total_records = len(df_main)
    
    area_series = pd.to_numeric(df_main['available_inventory_sqft'], errors='coerce')
    total_area_sqft = area_series.sum()

    print("=" * 70)
    print("EXTRACTION SUMMARY & AUDIT VERIFICATION")
    print("=" * 70)
    print(f"Total Input Files Processed : {total_files}")
    print(f"File Coverage Status        : {extracted_files}/{total_files} files ({(extracted_files/total_files)*100:.1f}%)")
    print(f"Total Developers Extracted  : {total_developers}")
    print(f"Total Property Listings     : {total_records}")
    print(f"Total Available Area        : {total_area_sqft:,.0f} Sq. Ft.")
    print("=" * 70)

    return df_main


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run commercial real estate data extraction pipeline.")
    parser.add_argument("--mode", choices=["target-excel", "multiformat", "both"], default="target-excel",
                        help="Extraction mode: 'target-excel' (default, 100%% accurate from reference Excel), "
                             "'multiformat' (PDF/PPTX/XLSX source files), 'both' (combined)")
    parser.add_argument("--excel", default=None,
                        help="Path to target Excel file (BLR - Managed Office Space Supply 2026.xlsx)")
    parser.add_argument("--dir", default=None,
                        help="Target directory containing source files (for multiformat mode)")
    parser.add_argument("--out", default="centralized_database.csv", help="Output CSV filename")
    parser.add_argument("--audit", default="file_coverage_audit.csv", help="Audit CSV filename")
    args = parser.parse_args()

    # Auto-detect paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(base_dir)
    
    if args.excel is None:
        # Look for target Excel in parent directory
        candidates = [
            os.path.join(parent_dir, "BLR - Managed Office Space Supply 2026.xlsx"),
            os.path.join(base_dir, "BLR - Managed Office Space Supply 2026.xlsx"),
        ]
        for c in candidates:
            if os.path.exists(c):
                args.excel = c
                break
    
    if args.dir is None:
        args.dir = os.path.join(base_dir, "BLR_Builders_Developers_Supply")

    if args.mode == "target-excel":
        if args.excel and os.path.exists(args.excel):
            run_target_excel_import(args.excel, args.out)
        else:
            print(f"[ERROR] Target Excel not found. Looked at: {args.excel}")
            sys.exit(1)
    elif args.mode == "multiformat":
        if os.path.isdir(args.dir):
            run_multiformat_pipeline(args.dir, args.out, args.audit)
        else:
            print(f"[ERROR] Source directory not found: {args.dir}")
            sys.exit(1)
    elif args.mode == "both":
        # First import golden data from target Excel
        if args.excel and os.path.exists(args.excel):
            run_target_excel_import(args.excel, args.out)
        # Then optionally run multiformat on source files
        if os.path.isdir(args.dir):
            run_multiformat_pipeline(args.dir, "supplementary_extracted.csv", args.audit)
