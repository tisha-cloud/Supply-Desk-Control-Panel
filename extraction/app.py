from fastapi import FastAPI, File, UploadFile, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import pandas as pd
import os
import shutil
from datetime import datetime

from run_extraction import run_pipeline

app = FastAPI(title="Commercial Real Estate Data Extraction Engine", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "BLR_Builders_Developers_Supply")
CSV_PATH = os.path.join(BASE_DIR, "centralized_database.csv")
AUDIT_PATH = os.path.join(BASE_DIR, "file_coverage_audit.csv")
WEB_DIR = os.path.join(BASE_DIR, "web")

os.makedirs(WEB_DIR, exist_ok=True)

# Serve static web frontend
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.get("/")
def get_index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

@app.get("/api/data")
def get_extracted_data(
    search: str = Query(None),
    developer: str = Query(None),
    micromarket: str = Query(None),
    fitout: str = Query(None),
    min_area: float = Query(None),
    max_area: float = Query(None),
    min_rent: float = Query(None),
    max_rent: float = Query(None)
):
    if not os.path.exists(CSV_PATH):
        # Run extraction if CSV doesn't exist yet
        run_pipeline(DATA_DIR)

    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    
    # Filter logic
    if developer and developer.lower() != 'all':
        df = df[df['developer_name'].str.lower() == developer.lower()]
        
    if micromarket and micromarket.lower() != 'all':
        df = df[df['micromarket_location'].str.lower() == micromarket.lower()]
        
    if fitout and fitout.lower() != 'all':
        df = df[df['fitout_status'].str.lower() == fitout.lower()]
        
    if search:
        s = search.lower()
        df = df[
            df['developer_name'].str.lower().str.contains(s) |
            df['property_name'].str.lower().str.contains(s) |
            df['micromarket_location'].str.lower().str.contains(s) |
            df['source_file'].str.lower().str.contains(s) |
            df['raw_remarks'].str.lower().str.contains(s)
        ]
        
    if min_area is not None:
        areas = pd.to_numeric(df['available_area_sqft'], errors='coerce')
        df = df[areas >= min_area]
        
    if max_area is not None:
        areas = pd.to_numeric(df['available_area_sqft'], errors='coerce')
        df = df[areas <= max_area]
        
    if min_rent is not None:
        rents = pd.to_numeric(df['rent_rate_sqft_pm'], errors='coerce')
        df = df[rents >= min_rent]
        
    if max_rent is not None:
        rents = pd.to_numeric(df['rent_rate_sqft_pm'], errors='coerce')
        df = df[rents <= max_rent]
        
    records = df.to_dict(orient="records")
    
    # Options for filter dropdowns
    df_raw = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    developers = sorted([d for d in df_raw['developer_name'].unique() if d])
    micromarkets = sorted([m for m in df_raw['micromarket_location'].unique() if m])
    fitouts = sorted([f for f in df_raw['fitout_status'].unique() if f])
    
    # Metrics
    area_series = pd.to_numeric(df_raw['available_area_sqft'], errors='coerce')
    rent_series = pd.to_numeric(df_raw['rent_rate_sqft_pm'], errors='coerce')
    
    metrics = {
        'total_records': len(df_raw),
        'total_developers': df_raw['developer_name'].nunique(),
        'total_area_sqft': float(area_series.sum()) if not area_series.empty else 0,
        'avg_rent_sqft': round(float(rent_series.mean()), 2) if not rent_series.empty and not pd.isna(rent_series.mean()) else 0,
        'filtered_count': len(records)
    }
    
    return {
        'metrics': metrics,
        'filters': {
            'developers': developers,
            'micromarkets': micromarkets,
            'fitouts': fitouts
        },
        'data': records
    }

@app.get("/api/audit")
def get_audit_log():
    if not os.path.exists(AUDIT_PATH):
        run_pipeline(DATA_DIR)
        
    df_audit = pd.read_csv(AUDIT_PATH, dtype=str).fillna("")
    records = df_audit.to_dict(orient="records")
    
    total_files = len(df_audit)
    extracted_files = len(df_audit[df_audit['status'] == '100% EXTRACTED'])
    coverage_pct = round((extracted_files / total_files) * 100, 1) if total_files > 0 else 0
    
    return {
        'summary': {
            'total_files': total_files,
            'extracted_files': extracted_files,
            'coverage_pct': coverage_pct
        },
        'audit_records': records
    }

@app.post("/api/reextract")
def trigger_reextract():
    try:
        run_pipeline(DATA_DIR)
        return {"status": "success", "message": "Re-extraction completed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download/csv")
def download_csv():
    if os.path.exists(CSV_PATH):
        return FileResponse(CSV_PATH, filename="centralized_database.csv", media_type="text/csv")
    raise HTTPException(status_code=404, detail="CSV file not found")

@app.get("/api/download/audit")
def download_audit():
    if os.path.exists(AUDIT_PATH):
        return FileResponse(AUDIT_PATH, filename="file_coverage_audit.csv", media_type="text/csv")
    raise HTTPException(status_code=404, detail="Audit CSV file not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
