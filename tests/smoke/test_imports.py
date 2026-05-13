# =========================================================
# test_imports.py
# Smoke test for SalvageIQ package imports.
# =========================================================

def test_import_smoke() -> None:
    from config.settings import (
        PROJECT_ROOT,
        DATA_DIR,
        START_YEAR,
        END_YEAR,
        TOP_N_PARTS,
    )

    from config.taxonomy import (
        PART_TAXONOMY,
        CATEGORY_PRIORITY,
        ECM_TERMS,
        TCM_TERMS,
    )

    from config.vehicles import (
        SUPPORTED_VEHICLES,
        MAKE_ALIASES,
        MODEL_ALIASES,
        HEAVY_DUTY_EXCLUSIONS,
    )

    from config.scrape_config import ScrapeConfig
    from config.config_builder import build_scrape_config

    assert START_YEAR <= END_YEAR
    assert isinstance(PART_TAXONOMY, dict)
    assert isinstance(CATEGORY_PRIORITY, list)
    assert isinstance(SUPPORTED_VEHICLES, list)
    assert ScrapeConfig is not None
    assert callable(build_scrape_config)


if __name__ == "__main__":
    test_import_smoke()
