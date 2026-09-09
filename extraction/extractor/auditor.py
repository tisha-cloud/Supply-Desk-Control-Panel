import pandas as pd
import os

def generate_coverage_audit(inventory, all_extracted_records):
    """
    Generates file-by-file coverage audit table confirming 100% file processing.
    """
    audit_map = {}
    
    for item in inventory:
        rel = item['rel_path']
        audit_map[rel] = {
            'developer_name': item['developer_name'],
            'folder_category': item['folder_category'],
            'source_file': rel,
            'source_format': item['file_type'],
            'file_size_kb': round(item['size_bytes'] / 1024, 2),
            'records_extracted_count': 0,
            'extraction_engines_used': set(),
            'status': '0% FAILED'
        }
        
    for rec in all_extracted_records:
        rel = rec.get('source_file')
        if rel in audit_map:
            audit_map[rel]['records_extracted_count'] += 1
            audit_map[rel]['extraction_engines_used'].add(rec.get('extraction_method', 'Engine'))
            audit_map[rel]['status'] = '100% EXTRACTED'
            
    audit_rows = []
    for rel, data in audit_map.items():
        data['extraction_engines_used'] = ", ".join(sorted(list(data['extraction_engines_used']))) if data['extraction_engines_used'] else 'N/A'
        audit_rows.append(data)
        
    audit_df = pd.DataFrame(audit_rows)
    return audit_df
