"""TOKENFORGE UI theme — monochrome "silver on black" with film grain.

Pure CSS, no external requests (the app stays 100% local / offline).
Fonts: Inter if installed, otherwise the system UI font; Georgia italic stands in for the serif accent.
"""

GRAIN = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E"
    "%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E"
    "%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")"
)

THEME_CSS = """
:root{
  --bg:#000; --text:#fff; --muted:#9a9a9a; --stat:#d8d8d8; --accent:#4ade80;
  --border:rgba(255,255,255,.16); --border-soft:rgba(255,255,255,.10);
  --card:rgba(255,255,255,.035); --silver:rgba(198,198,198,.45);
  --serif:"Instrument Serif",Georgia,"Times New Roman",serif;
}
html,body,.stApp{background:var(--bg)!important;color:var(--text)!important;
  font-family:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;letter-spacing:-.01em}
.stApp{background:radial-gradient(1100px 520px at 50% -8%,rgba(255,255,255,.085),transparent 62%),#000!important}
.stApp::before{content:"";position:fixed;inset:0;z-index:999;pointer-events:none;opacity:.06;background-image:__GRAIN__}
header[data-testid="stHeader"],.stAppHeader{background:transparent!important}
.stDeployButton,[data-testid="stToolbar"]{display:none!important}
.block-container{padding-top:2.2rem!important;padding-bottom:4rem!important;max-width:1080px!important}
h1,h2,h3,h4,h5{letter-spacing:-.035em!important;font-weight:500!important;color:#fff!important}
hr{border-color:var(--border-soft)!important}
a{color:#fff}

/* entrance motion */
@keyframes tf-in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.block-container>div>div>div{animation:tf-in .9s cubic-bezier(.16,1,.3,1) both}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

/* hero */
.tf-hero{text-align:center;padding:34px 0 30px}
.tf-badge{display:inline-flex;align-items:center;gap:8px;padding:8px 15px;border-radius:5px;font-size:12.5px;color:#f2f2f2;
  background:linear-gradient(90deg,#7d7d7d 0%,#2a2a2a 52%,#0a0a0a 100%)}
.tf-badge i{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
.tf-h1{font-size:clamp(34px,5.2vw,56px);font-weight:500;letter-spacing:-.045em;line-height:1.1;margin:22px 0 0;color:#fff}
.tf-h1 em{font-family:var(--serif);font-style:italic;font-weight:400;font-size:1.08em;letter-spacing:-.03em;color:#9a9a9a}
.tf-lede{max-width:560px;margin:18px auto 0;color:var(--muted);font-size:16px;line-height:1.55}
.tf-step{display:flex;align-items:center;gap:12px;margin:34px 0 12px;font-size:13px;color:var(--stat);letter-spacing:.02em}
.tf-step b{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;border:1px solid var(--silver);
  background:linear-gradient(135deg,rgba(255,255,255,.14),rgba(0,0,0,.5));font-weight:500;font-size:12px}

/* sidebar */
section[data-testid="stSidebar"]{background:#050505!important;border-right:1px solid var(--border-soft)!important}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:var(--stat)!important}
.tf-status{background:var(--card);border:1px solid var(--border-soft);border-radius:10px;padding:14px;font-size:12px}
.tf-status .t{color:var(--muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px;font-weight:600}
.tf-status .r{display:flex;justify-content:space-between;margin-bottom:6px;color:var(--stat)}
.tf-status .ok{color:var(--accent);font-weight:600}.tf-status .warn{color:#facc15;font-weight:600}

/* inputs */
.stTextInput input,.stSelectbox [data-baseweb="select"]>div,.stTextArea textarea{background:var(--card)!important;color:#fff!important;
  border:1px solid var(--border)!important;border-radius:8px!important;transition:border-color .25s,box-shadow .25s}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:rgba(235,235,235,.9)!important;box-shadow:0 0 18px rgba(200,210,230,.16)!important}

/* mode selector = segmented cards */
[data-testid="stRadio"] [role="radiogroup"]{gap:10px}
[data-testid="stRadio"] [role="radiogroup"]>label{flex:1;padding:12px 16px!important;border:1px solid var(--border);border-radius:10px;
  background:var(--card);transition:border-color .3s,background .3s,box-shadow .3s}
[data-testid="stRadio"] [role="radiogroup"]>label:hover{border-color:var(--silver);background:rgba(255,255,255,.06)}
[data-testid="stRadio"] [role="radiogroup"]>label:has(input:checked){border-color:#fff;background:rgba(255,255,255,.09);box-shadow:0 0 22px rgba(186,208,255,.14)}
[data-testid="stRadio"] label p{color:#fff!important;font-size:14px!important}

/* tabs */
.stTabs [data-baseweb="tab-list"]{gap:6px;border-bottom:1px solid var(--border-soft)!important}
.stTabs [data-baseweb="tab"]{padding:10px 16px;color:var(--muted)!important;font-weight:500;background:transparent!important;border-radius:7px 7px 0 0}
.stTabs [data-baseweb="tab"]:hover{color:#fff!important}
.stTabs [aria-selected="true"]{color:#fff!important}
[data-baseweb="tab-highlight"]{background:#fff!important}[data-baseweb="tab-border"]{background:transparent!important}

/* uploader */
[data-testid="stFileUploaderDropzone"]{background:var(--card)!important;border:1.5px dashed var(--silver)!important;border-radius:14px!important;
  padding:34px 20px!important;transition:border-color .3s,background .3s,box-shadow .3s}
[data-testid="stFileUploaderDropzone"]:hover{border-color:#fff!important;background:rgba(255,255,255,.06)!important;box-shadow:0 0 30px rgba(170,200,255,.12)}
[data-testid="stFileUploaderDropzoneInstructions"] *{color:var(--muted)!important}

/* buttons: silver (primary) / glass ghost (secondary) with shine sweep */
.stButton>button,.stDownloadButton>button,[data-testid="stFileUploader"] button{position:relative;overflow:hidden;height:42px;border-radius:6px!important;
  font-weight:500!important;letter-spacing:-.02em;transition:background .35s,border-color .35s,box-shadow .35s,transform .2s!important}
.stButton>button::after,.stDownloadButton>button::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(115deg,transparent 20%,rgba(255,255,255,.45) 48%,transparent 76%);transform:translateX(-130%);transition:transform .65s}
.stButton>button:hover::after,.stDownloadButton>button:hover::after{transform:translateX(130%)}
button[kind="primary"],button[data-testid="stBaseButton-primary"]{background:linear-gradient(180deg,#fff 0%,#e7e7e7 48%,#cfcfcf 100%)!important;
  color:#111!important;border:1px solid #fff!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.95)!important}
button[kind="primary"]:hover,button[data-testid="stBaseButton-primary"]:hover{background:linear-gradient(180deg,#fff 0%,#f3f6ff 42%,#d5def2 100%)!important;
  box-shadow:inset 0 1px 0 #fff,0 0 22px rgba(186,208,255,.35),0 8px 18px rgba(255,255,255,.12)!important}
button[kind="primary"]:disabled,button[data-testid="stBaseButton-primary"]:disabled{opacity:.35}
button[kind="secondary"],button[data-testid="stBaseButton-secondary"],[data-testid="stFileUploader"] button{
  background:linear-gradient(135deg,rgba(255,255,255,.1),rgba(0,0,0,.45) 50%,rgba(160,175,200,.08))!important;color:#fff!important;
  border:1px solid var(--silver)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.12)!important}
button[kind="secondary"]:hover,button[data-testid="stBaseButton-secondary"]:hover,[data-testid="stFileUploader"] button:hover{
  border-color:rgba(220,230,255,.8)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.22),0 0 20px rgba(170,200,255,.22)!important}

/* cards & metrics */
.metric-card,.hero-card,[data-testid="stMetric"]{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;
  backdrop-filter:blur(14px);transition:border-color .3s,transform .2s}
.metric-card:hover,[data-testid="stMetric"]:hover{border-color:var(--silver);transform:translateY(-2px)}
.metric-label,[data-testid="stMetricLabel"] p{font-size:11.5px!important;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)!important;font-weight:500}
.metric-value,[data-testid="stMetricValue"]{font-size:26px;font-weight:500;color:#fff;letter-spacing:-.03em}
.metric-value-green{font-size:26px;font-weight:500;color:var(--accent)}
.tf-big{font-size:64px;font-weight:500;letter-spacing:-.05em;line-height:1;color:#fff}
.tf-big small{font-size:28px;color:var(--muted);margin-left:2px}
.tf-sub{color:var(--muted);font-size:13px;margin-top:10px}

/* misc */
.stat-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:5px;font-size:11.5px;font-weight:500;color:#f2f2f2;
  background:linear-gradient(90deg,#6d6d6d,#1b1b1b)}
.pill-green,.pill-blue{padding:2px 9px;border-radius:12px;font-size:11px;font-weight:600;background:rgba(255,255,255,.08);color:#fff}
.stDataFrame,[data-testid="stDataFrame"]{border:1px solid var(--border);border-radius:12px;overflow:hidden}
[data-testid="stExpander"]{border:1px solid var(--border)!important;border-radius:12px!important;background:var(--card)}
[data-testid="stAlert"]{border-radius:10px;border:1px solid var(--border-soft);background:var(--card)}
[data-testid="stCode"],pre{border:1px solid var(--border-soft);border-radius:10px}
.tf-empty{margin-top:30px;text-align:center;color:var(--muted);font-size:13.5px}
.tf-empty span{display:inline-block;margin:0 10px;color:var(--stat)}
.tf-out{background:var(--card);border:1px solid var(--border-soft);border-radius:8px;padding:10px 14px;font-size:12px;color:var(--muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tf-out code{color:#fff;background:transparent}
""".replace("__GRAIN__", GRAIN)
