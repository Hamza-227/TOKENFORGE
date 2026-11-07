"""
TOKENFORGE — Desktop Application
================================
Convert documents into token-efficient, LLM-ready content.
Local, secure, database-free, and privacy-preserving.
"""

import os
import sys
import time
import inspect
import tempfile
import shutil
from pathlib import Path
import streamlit as st

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    APP_NAME,
    APP_VERSION,
    APP_TAGLINE,
    SUPPORTED_EXTENSIONS,
    OUTPUT_ROOT,
    OptimizationMode,
    DEFAULT_ENCODING,
)
from theme import THEME_CSS
from core.dispatcher import process_document
from core.validation_engine import ValidationEngine
from core.export_engine import ExportEngine
from core.token_counter import TokenCounter, format_token_count
from core.ocr_engine import OCREngine
from utils.file_utils import collect_files_from_folder, get_file_size_mb

# Streamlit renamed use_container_width -> width="stretch"; support both.
_NEW_WIDTH_API = "width" in inspect.signature(st.button).parameters
STRETCH = {"width": "stretch"} if _NEW_WIDTH_API else {"use_container_width": True}

# ── Streamlit Page Configuration ─────────────────────────────────────────────
st.set_page_config(
    page_title=f"{APP_NAME} — Document to LLM Optimizer",
    page_icon="assets/logo-mark.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme ────────────────────────────────────────────────────────────────────
st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)

def initialize_session_state():
    """Set default session state variables."""
    if "results" not in st.session_state:
        st.session_state.results = []
    if "validations" not in st.session_state:
        st.session_state.validations = []
    if "zip_path" not in st.session_state:
        st.session_state.zip_path = None
    if "output_paths" not in st.session_state:
        st.session_state.output_paths = None
    if "summary_path" not in st.session_state:
        st.session_state.summary_path = None
    if "sample_loaded" not in st.session_state:
        st.session_state.sample_loaded = False
    if "staging_dir" not in st.session_state:
        st.session_state.staging_dir = tempfile.mkdtemp(prefix="tokenforge_")
    if "errors" not in st.session_state:
        st.session_state.errors = []


initialize_session_state()

# ── Sidebar: brand + engine status ───────────────────────────────────────────
ocr_eng = OCREngine()
_tok = TokenCounter()
with st.sidebar:
    _logo = PROJECT_ROOT / "assets" / "logo-mark.png"
    if _logo.exists():
        st.image(str(_logo), **STRETCH)
    st.caption(f"v{APP_VERSION} · {APP_TAGLINE}")
    st.markdown("---")
    tok_label = DEFAULT_ENCODING if _tok.is_exact else "estimate (offline)"
    st.markdown(
        f"""
        <div class="tf-status">
          <div class="t">Engine status</div>
          <div class="r"><span>Tokenizer</span><span class="{'ok' if _tok.is_exact else 'warn'}">{tok_label}</span></div>
          <div class="r"><span>OCR</span><span class="{'ok' if ocr_eng.is_available() else 'warn'}">{'Tesseract ready' if ocr_eng.is_available() else 'Not installed'}</span></div>
          <div class="r"><span>Privacy</span><span class="ok">100% local</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not _tok.is_exact:
        st.caption("⚠️ Exact token counting needs a one-time download of the tiktoken vocabulary. Counts are approximate until then.")
    if not ocr_eng.is_available():
        st.caption("⚠️ Tesseract OCR not found — scanned PDFs / images won't be read. See README for install steps.")

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="tf-hero">
      <div class="tf-badge"><i></i>Local document-to-LLM pipeline</div>
      <div class="tf-h1">Turn messy documents into<br/><em>token-efficient</em> context.</div>
      <div class="tf-lede">PDF, Word, slides, spreadsheets and images → clean Markdown for ChatGPT, Claude, Gemini and NotebookLM. Nothing leaves your machine.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Step 1: documents ────────────────────────────────────────────────────────
files_to_process: list[Path] = []
st.markdown('<div class="tf-step"><b>1</b>Add documents</div>', unsafe_allow_html=True)

upload_tab, folder_tab = st.tabs(["Drag & drop", "Local folder"])
with upload_tab:
    uploaded_files = st.file_uploader(
        "Upload files:",
        type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
        label_visibility="collapsed",
        help="Supported: PDF, PPTX, DOCX, XLSX, CSV, TXT, PNG, JPG, JPEG, TIFF",
    )
    if uploaded_files:
        staging_dir = Path(st.session_state.staging_dir)
        staging_dir.mkdir(exist_ok=True)
        for uf in uploaded_files:
            target_path = staging_dir / Path(uf.name).name
            with open(target_path, "wb") as f:
                f.write(uf.getbuffer())
            files_to_process.append(target_path)
        st.caption(f"✓ {len(uploaded_files)} file(s) ready for optimization.")
    if st.button("Try with sample files", type="secondary"):
        st.session_state.sample_loaded = True
        st.rerun()

with folder_tab:
    folder_path_input = st.text_input(
        "Enter directory path containing documents:",
        placeholder=r"C:\Users\User\Documents\ResearchPapers",
        label_visibility="collapsed",
    )
    if folder_path_input:
        f_path = Path(folder_path_input.strip().strip('"').strip("'")).expanduser()
        if f_path.is_dir():
            found = collect_files_from_folder(f_path)
            st.success(f"Discovered {len(found)} supported document(s) in folder.")
            files_to_process.extend(found)
        else:
            st.error("Directory not found or inaccessible.")

if st.session_state.sample_loaded:
    sample_txt = PROJECT_ROOT / "sample_data" / "sample_research_note.txt"
    sample_csv = PROJECT_ROOT / "sample_data" / "sample_quarterly_financials.csv"
    if sample_txt.exists():
        files_to_process.append(sample_txt)
    if sample_csv.exists():
        files_to_process.append(sample_csv)
    st.info(f"Loaded {len(files_to_process)} benchmark sample file(s): `sample_research_note.txt`, `sample_quarterly_financials.csv`.")

# ── Step 2: compression mode ─────────────────────────────────────────────────
st.markdown('<div class="tf-step"><b>2</b>Choose compression</div>', unsafe_allow_html=True)
selected_mode = st.radio(
    "Compression profile:",
    options=[OptimizationMode.BALANCED, OptimizationMode.PRESERVATION, OptimizationMode.MAX_COMPRESSION],
    format_func=lambda m: OptimizationMode.LABELS[m],
    index=0,
    horizontal=True,
    label_visibility="collapsed",
)
st.caption(OptimizationMode.DESCRIPTIONS[selected_mode])

default_out = str(PROJECT_ROOT / OUTPUT_ROOT)
with st.expander("Advanced: output folder & bundle options"):
    output_dir_input = st.text_input(
        "Output folder path:",
        value=default_out,
        help="All generated Markdown files, assets, and reports will be saved here.",
    )
    include_originals = st.checkbox(
        "Include original source copies in bundle",
        value=False,
        help="Preserves untouched duplicate copies of input documents in originals/.",
    )

# De-duplicate (same file selected twice, sample + upload, ...)
_seen, _unique = set(), []
for _p in files_to_process:
    if str(_p) not in _seen:
        _seen.add(str(_p))
        _unique.append(_p)
files_to_process = _unique

# ── Step 3: run ──────────────────────────────────────────────────────────────
st.markdown('<div class="tf-step"><b>3</b>Run</div>', unsafe_allow_html=True)
col_run, col_clear, col_space = st.columns([1.6, 1, 3])
with col_run:
    start_btn = st.button(
        "Start optimization",
        type="primary",
        disabled=not files_to_process,
        help=None if files_to_process else "Add at least one file first.",
        **STRETCH,
    )
with col_clear:
    if st.session_state.results or st.session_state.sample_loaded:
        if st.button("Clear / reset", type="secondary", **STRETCH):
            st.session_state.results = []
            st.session_state.validations = []
            st.session_state.errors = []
            st.session_state.zip_path = None
            st.session_state.summary_path = None
            st.session_state.sample_loaded = False
            shutil.rmtree(st.session_state.staging_dir, ignore_errors=True)
            st.session_state.staging_dir = tempfile.mkdtemp(prefix="tokenforge_")
            st.rerun()

if start_btn and files_to_process:
    try:
        export_mgr = ExportEngine(output_dir_input.strip() or default_out)
    except Exception as exc:
        st.error(f"Cannot use output folder '{output_dir_input}': {exc}")
        st.stop()

    paths = export_mgr.get_output_paths()
    st.session_state.output_paths = {k: str(v) for k, v in paths.items()}

    results, validations, errors = [], [], []
    val_engine = ValidationEngine()
    registry: dict = {}
    progress_bar = st.progress(0.0, text="Initializing pipeline...")
    total_files = len(files_to_process)

    for idx, file_p in enumerate(files_to_process):
        progress_bar.progress(idx / total_files, text=f"Optimizing ({idx + 1}/{total_files}): {file_p.name} ...")
        try:
            res = process_document(
                filepath=file_p,
                output_dir=paths["optimized"],
                assets_dir=paths["assets"],
                mode=selected_mode,
                name_registry=registry,
            )
            val = val_engine.validate(res["original_text"], res["optimized_text"], mode=selected_mode)
            res["validation"] = val
            export_mgr.export_result(res, include_original=include_originals)
            results.append(res)
            validations.append(val)
        except Exception as exc:  # keep going — one bad file must not stop the batch
            errors.append((file_p.name, str(exc)))

    progress_bar.progress(1.0, text="Writing reports and ZIP bundle...")
    st.session_state.errors = errors

    if results:
        export_mgr.generate_compression_report(results)
        export_mgr.generate_validation_report(validations)
        st.session_state.summary_path = export_mgr.generate_summary(results, validations)
        st.session_state.zip_path = export_mgr.create_zip_export()
        st.session_state.results = results
        st.session_state.validations = validations
        st.rerun()
    else:
        progress_bar.empty()

for _name, _err in st.session_state.errors:
    st.error(f"**{_name}** could not be processed: {_err}")


# ── Results & Dashboard Section ──────────────────────────────────────────────
if st.session_state.results:
    results = st.session_state.results
    validations = st.session_state.validations

    st.markdown("---")
    st.markdown("### Results")

    total_files = len(results)
    total_orig_tok = sum(r["original_tokens"] for r in results)
    total_opt_tok = sum(r["optimized_tokens"] for r in results)
    total_saved = total_orig_tok - total_opt_tok
    overall_reduction = (
        round((total_saved / total_orig_tok) * 100, 1) if total_orig_tok > 0 else 0.0
    )

    # Metric Row — one hero number, three supporting ones
    c_main, c_rest = st.columns([1.35, 2], gap="large")
    with c_main:
        st.markdown(
            f"""
            <div class="metric-card" style="padding:26px 28px;">
                <div class="metric-label">Net token reduction</div>
                <div class="tf-big" style="color:#4ade80;margin-top:10px;">{overall_reduction}<small>%</small></div>
                <div class="tf-sub">{total_saved:,} tokens saved across {total_files} document(s)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c_rest:
        a, b, c = st.columns(3)
        a.metric("Documents", f"{total_files}")
        b.metric("Original tokens", f"{total_orig_tok:,}")
        c.metric("Optimized tokens", f"{total_opt_tok:,}")

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # Export & Download Quick-Actions Bar
    col_zip, col_sum, col_folder = st.columns([1.2, 1.2, 1.6])
    with col_zip:
        if st.session_state.zip_path and os.path.exists(st.session_state.zip_path):
            with open(st.session_state.zip_path, "rb") as zf:
                st.download_button(
                    label="Download ZIP bundle", type="primary",
                    data=zf.read(),
                    file_name=Path(st.session_state.zip_path).name,
                    mime="application/zip",
                    **STRETCH,
                )
    with col_sum:
        if st.session_state.summary_path and os.path.exists(st.session_state.summary_path):
            with open(st.session_state.summary_path, "r", encoding="utf-8") as sf:
                st.download_button(
                    label="Download summary", type="secondary",
                    data=sf.read(),
                    file_name="TOKENFORGE_SUMMARY.md",
                    mime="text/markdown",
                    **STRETCH,
                )
    with col_folder:
        out_root = output_dir_input
        st.markdown(
            f"""
            <div class="tf-out">Output: <code>{out_root}</code></div>
            """,
            unsafe_allow_html=True,
        )

    # ── Document Comparison Table ─────────────────────────────────────────────
    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("#### Comparison & validation")

    table_rows = []
    for idx, r_ in enumerate(results):
        v = validations[idx] if idx < len(validations) else {}
        table_rows.append({
            "Document": Path(r_["source_file"]).name,
            "Representation": r_.get("format_type", "markdown"),
            "Original": int(r_.get("original_tokens", 0)),
            "Optimized": int(r_.get("optimized_tokens", 0)),
            "Saved": int(r_.get("tokens_saved", 0)),
            "Reduction": float(r_.get("reduction_pct", 0.0)),
            "Latency (s)": float(r_.get("processing_time", 0.0)),
            "Fact score": float(v.get("preservation_score", 1.0)) * 100,
            "Status": v.get("status", "pass").upper(),
        })

    st.dataframe(
        table_rows,
        hide_index=True,
        column_config={
            "Original": st.column_config.NumberColumn(format="%d"),
            "Optimized": st.column_config.NumberColumn(format="%d"),
            "Saved": st.column_config.NumberColumn(format="%d"),
            "Reduction": st.column_config.ProgressColumn("Reduction", format="%.1f%%", min_value=0, max_value=100),
            "Latency (s)": st.column_config.NumberColumn(format="%.2f"),
            "Fact score": st.column_config.ProgressColumn("Fact score", format="%.1f%%", min_value=0, max_value=100),
        },
        **STRETCH,
    )
    if total_opt_tok > total_orig_tok:
        st.info(
            "ℹ️ Optimized output is slightly larger than the raw text for some files. That happens on short, "
            "already-clean documents: Markdown headings/tables add structure that helps LLMs, while real savings "
            "come from removing repeated headers/footers, duplicates, empty cells and layout noise. "
            "Choose **Maximum Compression** for the smallest output."
        )
    for _r in results:
        for _w in _r.get("warnings", []):
            st.warning(f"**{Path(_r['source_file']).name}:** {_w}")

    # ── Document Inspector ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Inspector")

    doc_names = [Path(r["source_file"]).name for r in results]
    selected_name = st.selectbox(
        "Select document to inspect:",
        options=doc_names,
        index=0,
    )
    sel_idx = doc_names.index(selected_name)
    selected_doc = results[sel_idx]
    selected_val = validations[sel_idx]

    tab_preview, tab_copy, tab_raw, tab_assets, tab_validation = st.tabs(
        ["Preview", "Copy Markdown", "Original text", "Images", "Validation"]
    )

    with tab_copy:
        st.caption("Use the copy icon (top-right of the box) and paste straight into ChatGPT / Claude / Gemini.")
        st.code(selected_doc["optimized_text"], language="markdown")

    with tab_preview:
        col_down, col_info = st.columns([1, 4])
        with col_down:
            st.download_button(
                f"Download {selected_name}.md",
                data=selected_doc["optimized_text"],
                file_name=f"{Path(selected_doc['source_file']).stem}.md",
                mime="text/markdown",
            )
        with col_info:
            tok_count = selected_doc.get("optimized_tokens", 0)
            red_pct = selected_doc.get("reduction_pct", 0.0)
            st.caption(f"Formatted as **{selected_doc.get('format_type', 'markdown')}** • **{tok_count:,} tokens** ({red_pct:.1f}% savings)")

        try:
            _box = st.container(border=True)
        except TypeError:  # very old Streamlit
            _box = st.container()
        with _box:
            st.markdown(selected_doc["optimized_text"])

    with tab_raw:
        st.text_area(
            "Original Extracted Baseline (before deduplication & compaction):",
            value=selected_doc["original_text"][:25000],
            height=400,
            disabled=True,
        )
        if len(selected_doc["original_text"]) > 25000:
            st.caption(f"*Showing first 25,000 characters of {len(selected_doc['original_text']):,} total.*")

    with tab_assets:
        images = selected_doc.get("images_extracted", [])
        if not images:
            st.info("No visual images or diagrams were detected in this document.")
        else:
            st.markdown(f"**Preserved Document Visuals ({len(images)} item(s)):**")
            cols = st.columns(3)
            for i, img_path in enumerate(images):
                with cols[i % 3]:
                    opt_dir = Path((st.session_state.output_paths or {}).get("optimized", output_dir_input))
                    real_img = (opt_dir / img_path).resolve()
                    if not real_img.exists():
                        real_img = Path(img_path)
                    if real_img.exists():
                        st.image(str(real_img), caption=Path(img_path).name, **STRETCH)
                    else:
                        st.caption(f"Asset: `{img_path}`")

    with tab_validation:
        v_status = selected_val.get("status", "pass")
        score = selected_val.get("preservation_score", 1.0) * 100
        st.markdown(
            f"""
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
                <span class="stat-badge" style="font-size:13px;">Validation Status: {v_status.upper()}</span>
                <span style="font-size:14px; color:#f0f6fc;">Fact Retention Score: <b>{score:.1f}%</b></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for chk in selected_val.get("checks", []):
            st.markdown(f"- **{chk['name'].replace('_', ' ').title()}:** {chk['details']}")

        if selected_val.get("warnings"):
            st.warning("Validation Warnings:\n" + "\n".join(f"- {w}" for w in selected_val["warnings"]))

else:
    st.markdown(
        """
        <div class="tf-empty">
            <span>Numerical fact preservation</span>·<span>SHA-256 image dedup</span>·<span>Offline engine</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
