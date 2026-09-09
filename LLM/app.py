from fastapi import FastAPI, File, UploadFile, Query, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os
import shutil
from pydantic import BaseModel
from typing import Optional, List

from requirement_engine import RequirementEngine
from ppt_generator import PPTGenerator
from template_manager import TemplateManager
from ai_client import AIClient

app = FastAPI(title="LLM Commercial Real Estate PPT Generator Engine", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DECKS_DIR = os.path.join(BASE_DIR, "generated_decks")

os.makedirs(WEB_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(DECKS_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

req_engine = RequirementEngine()
template_mgr = TemplateManager(TEMPLATES_DIR)
ai_client = AIClient()

@app.get("/api/ai-status")
def get_ai_status():
    provider = ai_client.get_active_provider()
    return {
        "active_provider": provider,
        "gemini_model": ai_client.gemini_model if ai_client.gemini_key else None,
        "openai_model": ai_client.openai_model if ai_client.openai_key else None,
        "claude_model": ai_client.claude_model if ai_client.claude_key else None,
        "configured": provider != "none"
    }

class PPTRequest(BaseModel):
    client_name: Optional[str] = "Valued Client"
    requirement_summary: Optional[str] = "Commercial Office Space Requirements"
    query: Optional[str] = None
    micromarket: Optional[str] = None
    fitout: Optional[str] = None
    developer: Optional[str] = None
    min_area: Optional[float] = None
    max_area: Optional[float] = None
    min_rent: Optional[float] = None
    max_rent: Optional[float] = None
    template_name: Optional[str] = None

@app.get("/")
def get_index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

@app.get("/api/options")
def get_filter_options():
    options = req_engine.get_filter_options()
    options["templates"] = template_mgr.list_templates()
    return options

@app.post("/api/search")
def search_listings(req: PPTRequest):
    records = req_engine.match_requirements(
        query=req.query,
        micromarket=req.micromarket,
        min_area=req.min_area,
        max_area=req.max_area,
        min_rent=req.min_rent,
        max_rent=req.max_rent,
        fitout=req.fitout,
        developer=req.developer,
        top_n=30
    )
    summary = req_engine.generate_summary(records)
    return {
        "summary": summary,
        "count": len(records),
        "records": records
    }

@app.post("/api/generate-ppt")
def generate_ppt(req: PPTRequest):
    # 1. Match property options
    records = req_engine.match_requirements(
        query=req.query,
        micromarket=req.micromarket,
        min_area=req.min_area,
        max_area=req.max_area,
        min_rent=req.min_rent,
        max_rent=req.max_rent,
        fitout=req.fitout,
        developer=req.developer,
        top_n=20
    )
    
    if not records:
        raise HTTPException(status_code=400, detail="No commercial properties matched your criteria to generate a presentation.")

    summary = req_engine.generate_summary(records)
    
    # 2. Build presentation deck
    generator = PPTGenerator(template_name=req.template_name)
    clean_client_filename = (req.client_name or "Client").replace(" ", "_").strip()
    filename = f"Commercial_Pitch_Deck_{clean_client_filename}.pptx"
    
    output_path = generator.generate_presentation(
        matched_records=records,
        summary_data=summary,
        client_name=req.client_name or "Valued Client",
        requirement_summary=req.requirement_summary or "Office Space Requirement",
        output_filename=filename
    )
    
    return {
        "status": "SUCCESS",
        "message": "PowerPoint Presentation generated successfully!",
        "filename": filename,
        "download_url": f"/api/download/{filename}",
        "summary": summary,
        "options_included": len(records)
    }

@app.get("/api/download/{filename}")
def download_deck(filename: str):
    file_path = os.path.join(DECKS_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested presentation file not found.")
    return FileResponse(file_path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", filename=filename)

@app.post("/api/upload-template")
async def upload_template(file: UploadFile = File(...)):
    if not file.filename.endswith(('.pptx', '.potx')):
        raise HTTPException(status_code=400, detail="Only PowerPoint .pptx or .potx template files are allowed.")
    
    dest_path = os.path.join(TEMPLATES_DIR, file.filename)
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {
        "status": "SUCCESS",
        "message": f"Template '{file.filename}' uploaded successfully!",
        "filename": file.filename
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
