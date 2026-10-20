"""Runtime configuration, read from environment (and the repo-root .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DATA_DIR = Path(os.getenv("CB_DATA_DIR", REPO_DIR / "data"))
GENERATED_DIR = DATA_DIR / "generated"

load_dotenv(REPO_DIR / ".env")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
GRAPH = os.getenv("GRAPH", "claimbridge")

LEASE_TTL_S = float(os.getenv("LEASE_TTL_S", "20"))
HEARTBEAT_S = float(os.getenv("HEARTBEAT_S", "5"))
POLL_S = float(os.getenv("POLL_S", "1"))
STEP_DELAY_S = float(os.getenv("STEP_DELAY_S", "0"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = 384
EMBED_CACHE = os.getenv("EMBED_CACHE", str(REPO_DIR / ".fastembed_cache"))

# Retrieval
MAX_CANDIDATES = 8
VECTOR_NEIGHBORS = 10
# Ablation: hide semantic memory (Findings) from Retrieval. Used by the evaluation.
NO_MEMORY = os.getenv("CB_NO_MEMORY", "0") == "1"

# Evaluation
# RESULTS_DIR holds the PROMOTED run (what the API and the site serve); every run lives in RUNS_DIR.
RESULTS_DIR = Path(os.getenv("CB_RESULTS_DIR", REPO_DIR / "eval" / "results"))
RUNS_DIR = Path(os.getenv("CB_RUNS_DIR", REPO_DIR / "eval" / "runs"))
ARCHIVE_DIR = Path(os.getenv("CB_ARCHIVE_DIR", REPO_DIR / "eval" / "archive"))
# The baseline uses ClaimBridge's own embedding model by default, so only graph reasoning differs.
BASELINE_EMBED_MODEL = os.getenv("BASELINE_EMBED_MODEL", EMBED_MODEL)
BASELINE_STRONG_EMBED_MODEL = os.getenv("BASELINE_STRONG_EMBED_MODEL", "mixedbread-ai/mxbai-embed-large-v1")
BASELINE_TOP_K = int(os.getenv("BASELINE_TOP_K", "8"))

# LLM
#   LLM_PLATFORM: groq | openai | claude | fake (deterministic stub for tests)
#   LLM_MODE:     cached  = replay a recorded response if there is one, else call and record
#                 live    = always call (and re-record)
#                 offline = replay only; fail if nothing is recorded
LLM_PLATFORM = os.getenv("LLM_PLATFORM", "groq").strip().lower()
LLM_MODE = os.getenv("LLM_MODE", "cached").strip().lower()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "medium").strip()
# Comma-separated models the investigator tries, in order, when the provider answers 429 (rate limit).
LLM_MODEL_FALLBACKS = [m.strip() for m in os.getenv("LLM_MODEL_FALLBACKS", "").split(",") if m.strip()]
PLANNER_DRAFT_AUDIT = os.getenv("PLANNER_DRAFT_AUDIT", "0") == "1"
LLM_CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", DATA_DIR / "llm_cache"))
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "openai": "gpt-5-mini",
    "claude": "claude-opus-5-5",
    "fake": "fake",
}


def env_any(*names: str) -> str | None:
    """First non-empty env var among `names` (the .env may use informal names)."""
    for n in names:
        for k, v in os.environ.items():
            if k.strip().lower() == n.lower() and v.strip():
                return v.strip()
    return None
