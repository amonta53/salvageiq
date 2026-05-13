# =========================================================
# settings.py
# Central project paths and runtime defaults for SalvageIQ.
# =========================================================

from pathlib import Path

# =========================================================
# Project paths
# =========================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"

# =========================================================
# Search scope
# =========================================================
START_YEAR = 2012
END_YEAR = 2020
SEARCH_SCOPE = "sold"   # "sold" or "all"
USED_ONLY = True
ENABLE_RESUME = True
RESET_OUTPUTS_ON_RUN = True
MAX_PAGES_PER_SEARCH = 2
WEAK_RESULT_SKIP_THRESHOLD = 3

# =========================================================
# Confidence scoring
# =========================================================
CONFIDENCE_SOLD_TARGET = 10
CONFIDENCE_ACTIVE_TARGET = 10
CONFIDENCE_SOLD_WEIGHT = 0.7
CONFIDENCE_ACTIVE_WEIGHT = 0.3
CONFIDENCE_MAX_SCORE = 1.0

# =========================================================
# Data quality flags
# =========================================================
LOW_SAMPLE_TOTAL_THRESHOLD = 5
VERY_LOW_SOLD_THRESHOLD = 3
STALE_SNAPSHOT_HOURS = 48

# =========================================================
# Output
# =========================================================
TOP_N_PARTS = 10
