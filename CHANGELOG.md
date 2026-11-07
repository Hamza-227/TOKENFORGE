# Changelog

## 1.2.0 — UI redesign
- Home page opens first with a **Try it out** button; tool and home page combined in one self-contained HTML file; embedded premium fonts; bigger logo; footer with repo and author links.
- New HTML/CSS/JS interface (`web/`) on a FastAPI backend (`server.py`); Streamlit UI kept as optional `app.py`.
- New monochrome "silver on black" theme (`theme.py`), pure CSS and fully offline.
- Three-step workflow on the main page; settings moved out of the sidebar.
- Hero metric for net token reduction; numeric results table with progress bars.
- Primary/secondary button hierarchy.
- Landing page for GitHub Pages (`docs/index.html`).
- CI workflow, issue template, theme test. Streamlit requirement raised to >=1.35.
- No changes to extraction, optimization or validation logic.

## 1.1.0
- OCR fixes, cleaner PDF/Word table output, protected URLs/emails/code during compression, improved validation and portable image links.
