"""TOKENFORGE web server — HTML/CSS/JS frontend on top of the same Python engine.

Run:  python server.py     (opens http://127.0.0.1:8501)
"""
import json, shutil, tempfile, threading, webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from config import APP_NAME, APP_VERSION, APP_TAGLINE, DEFAULT_ENCODING, OUTPUT_ROOT, SUPPORTED_EXTENSIONS, OptimizationMode
from core.dispatcher import process_document
from core.export_engine import ExportEngine
from core.ocr_engine import OCREngine
from core.token_counter import TokenCounter
from core.validation_engine import ValidationEngine
from utils.file_utils import collect_files_from_folder

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
app = FastAPI(title=APP_NAME, version=APP_VERSION)
STATE = {"out": None, "zip": None, "summary": None}
MODES = [OptimizationMode.BALANCED, OptimizationMode.PRESERVATION, OptimizationMode.MAX_COMPRESSION]


def _json(obj):
    return JSONResponse(json.loads(json.dumps(obj, default=str)))


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/logo.png")
def logo():
    return FileResponse(WEB / "logo.png")


@app.get("/api/status")
def status():
    tok, ocr = TokenCounter(), OCREngine()
    return {
        "name": APP_NAME, "version": APP_VERSION, "tagline": APP_TAGLINE,
        "tokenizer": DEFAULT_ENCODING if tok.is_exact else "estimate (offline)", "tokenizer_exact": tok.is_exact,
        "ocr": ocr.is_available(), "extensions": sorted(SUPPORTED_EXTENSIONS),
        "default_output": str(ROOT / OUTPUT_ROOT),
        "modes": [{"id": m, "label": OptimizationMode.LABELS[m], "desc": OptimizationMode.DESCRIPTIONS[m]} for m in MODES],
    }


@app.post("/api/process")
def process(files: list[UploadFile] = File(default=[]), mode: str = Form(OptimizationMode.BALANCED),
            folder: str = Form(""), sample: bool = Form(False), include_originals: bool = Form(False),
            output_dir: str = Form("")):
    if mode not in MODES:
        raise HTTPException(400, "Unknown mode")
    staging = Path(tempfile.mkdtemp(prefix="tokenforge_"))
    paths: list[Path] = []
    for uf in files:
        if uf.filename:
            p = staging / Path(uf.filename).name
            p.write_bytes(uf.file.read())
            paths.append(p)
    if folder.strip():
        f = Path(folder.strip().strip('"').strip("'")).expanduser()
        if not f.is_dir():
            raise HTTPException(400, "Directory not found or inaccessible.")
        paths += collect_files_from_folder(f)
    if sample:
        paths += [q for q in (ROOT / "sample_data").glob("sample_*") if q.is_file()]
    paths = list({str(p): p for p in paths}.values())
    if not paths:
        raise HTTPException(400, "Add at least one supported file.")
    try:
        export = ExportEngine(output_dir.strip() or str(ROOT / OUTPUT_ROOT))
    except Exception as exc:
        raise HTTPException(400, f"Cannot use output folder: {exc}")
    out = export.get_output_paths()
    results, vals, errors, registry, validator = [], [], [], {}, ValidationEngine()
    for p in paths:
        try:
            res = process_document(filepath=p, output_dir=out["optimized"], assets_dir=out["assets"], mode=mode, name_registry=registry)
            val = validator.validate(res["original_text"], res["optimized_text"], mode=mode)
            res["validation"] = val
            export.export_result(res, include_original=include_originals)
            results.append(res); vals.append(val)
        except Exception as exc:
            errors.append({"file": p.name, "error": str(exc)})
    if results:
        export.generate_compression_report(results)
        export.generate_validation_report(vals)
        STATE.update(out=str(export.base_dir), summary=export.generate_summary(results, vals), zip=export.create_zip_export())
    shutil.rmtree(staging, ignore_errors=True)
    return _json({"results": results, "validations": vals, "errors": errors, "output": STATE["out"]})


@app.get("/api/zip")
def get_zip():
    if not STATE["zip"] or not Path(STATE["zip"]).exists():
        raise HTTPException(404, "No bundle yet")
    return FileResponse(STATE["zip"], filename=Path(STATE["zip"]).name)


@app.get("/api/summary")
def get_summary():
    if not STATE["summary"] or not Path(STATE["summary"]).exists():
        raise HTTPException(404, "No summary yet")
    return FileResponse(STATE["summary"], filename=Path(STATE["summary"]).name)


@app.get("/api/image")
def get_image(path: str):
    p, base = Path(path).resolve(), Path(STATE["out"] or ".").resolve()
    if base not in p.parents or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:8501")).start()
    uvicorn.run(app, host="127.0.0.1", port=8501, log_level="warning")
