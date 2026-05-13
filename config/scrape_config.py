# =========================================================
# scrape_config.py
# Runtime configuration for the SalvageIQ pipeline.
# =========================================================

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from config.settings import (
    CONFIDENCE_ACTIVE_TARGET,
    CONFIDENCE_ACTIVE_WEIGHT,
    CONFIDENCE_MAX_SCORE,
    CONFIDENCE_SOLD_TARGET,
    CONFIDENCE_SOLD_WEIGHT,
    ENABLE_RESUME,
    END_YEAR,
    LOW_SAMPLE_TOTAL_THRESHOLD,
    MAX_PAGES_PER_SEARCH,
    RESET_OUTPUTS_ON_RUN,
    RUNS_DIR,
    SEARCH_SCOPE,
    STALE_SNAPSHOT_HOURS,
    START_YEAR,
    TOP_N_PARTS,
    USED_ONLY,
    VERY_LOW_SOLD_THRESHOLD,
    WEAK_RESULT_SKIP_THRESHOLD,
)
from config.taxonomy import SEARCH_PART_TERMS
from config.vehicles import SUPPORTED_VEHICLES
from config.schema import SOLD_COLUMN_MAP, ACTIVE_COLUMN_MAP


class VehicleConfig(TypedDict):
    year_range: tuple[int, int]
    make: str
    model: str


@dataclass(slots=True)
class ScrapeConfig:
    # =========================================================
    # Run mode
    # "full"  — all configured vehicles, full year range
    # "mini"  — small subset for quick pipeline checks
    # "test"  — single vehicle/part/year smoke test
    # =========================================================
    mode: str = "full"

    run_id: str = field(default_factory=lambda: str(uuid4()))
    runs_dir: Path = RUNS_DIR

    # =========================================================
    # Search behavior
    # =========================================================
    search_scope: str = SEARCH_SCOPE
    used_only: bool = USED_ONLY
    enable_resume: bool = ENABLE_RESUME
    reset_outputs_on_run: bool = RESET_OUTPUTS_ON_RUN
    max_pages_per_search: int = MAX_PAGES_PER_SEARCH
    weak_result_skip_threshold: int = WEAK_RESULT_SKIP_THRESHOLD

    # =========================================================
    # Search scope
    # =========================================================
    start_year: int = START_YEAR
    end_year: int = END_YEAR
    parts: list[str] = field(default_factory=lambda: SEARCH_PART_TERMS.copy())
    supported_vehicles: list[VehicleConfig] = field(
        default_factory=lambda: [v.copy() for v in SUPPORTED_VEHICLES]
    )

    # =========================================================
    # Confidence scoring
    # =========================================================
    confidence_sold_target: int = CONFIDENCE_SOLD_TARGET
    confidence_active_target: int = CONFIDENCE_ACTIVE_TARGET
    confidence_sold_weight: float = CONFIDENCE_SOLD_WEIGHT
    confidence_active_weight: float = CONFIDENCE_ACTIVE_WEIGHT
    confidence_max_score: float = CONFIDENCE_MAX_SCORE

    # =========================================================
    # Data quality thresholds
    # =========================================================
    low_sample_total_threshold: int = LOW_SAMPLE_TOTAL_THRESHOLD
    very_low_sold_threshold: int = VERY_LOW_SOLD_THRESHOLD
    stale_snapshot_hours: int = STALE_SNAPSHOT_HOURS

    # =========================================================
    # Output
    # =========================================================
    top_n_parts: int = TOP_N_PARTS

    # =========================================================
    # Column maps (used by aggregation stage)
    # =========================================================
    sold_column_map: dict = field(default_factory=lambda: SOLD_COLUMN_MAP.copy())
    active_column_map: dict = field(default_factory=lambda: ACTIVE_COLUMN_MAP.copy())

    # =========================================================
    # Directory structure
    # =========================================================
    @property
    def run_dir(self) -> Path:
        return self.runs_dir / self.run_id

    @property
    def raw_dir(self) -> Path:
        return self.run_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.run_dir / "processed"

    @property
    def outputs_dir(self) -> Path:
        return self.run_dir / "outputs"

    @property
    def logs_dir(self) -> Path:
        return self.outputs_dir / "logs"

    @property
    def analysis_dir(self) -> Path:
        return self.outputs_dir / "analysis"

    # =========================================================
    # File paths
    # =========================================================
    @property
    def raw_csv_path(self) -> Path:
        return self.raw_dir / "raw_listings.csv"

    @property
    def checkpoint_path(self) -> Path:
        return self.logs_dir / "scrape_checkpoint.json"

    @property
    def cleansed_csv_path(self) -> Path:
        return self.processed_dir / "cleansed_listings.csv"

    @property
    def normalized_csv_path(self) -> Path:
        return self.processed_dir / "normalized_listings.csv"

    @property
    def market_summary_csv_path(self) -> Path:
        return self.processed_dir / "market_summary.csv"

    @property
    def analysis_summary_csv_path(self) -> Path:
        return self.analysis_dir / "analysis_summary.csv"

    @property
    def full_ranked_output_csv_path(self) -> Path:
        return self.analysis_dir / "ranked_parts_all.csv"

    @property
    def top_10_output_csv_path(self) -> Path:
        return self.analysis_dir / "ranked_parts_top10.csv"

    @property
    def eda_summary_csv_path(self) -> Path:
        return self.analysis_dir / "eda_category_summary.csv"

    @property
    def scrape_log_path(self) -> Path:
        return self.logs_dir / "scrape_run.log"

    @property
    def pipeline_log_path(self) -> Path:
        return self.logs_dir / f"pipeline_{self.run_id}.log"

    # =========================================================
    # Make-model map (built from supported_vehicles)
    # =========================================================
    make_model_map: dict[str, list[str]] = field(init=False)

    def __post_init__(self) -> None:
        result: dict[str, list[str]] = {}
        for vehicle in self.supported_vehicles:
            make = vehicle["make"]
            model = vehicle["model"]
            result.setdefault(make, [])
            if model not in result[make]:
                result[make].append(model)
        self.make_model_map = result
