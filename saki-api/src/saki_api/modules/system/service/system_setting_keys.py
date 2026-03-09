"""
System setting key constants.
"""


class SystemSettingKeys:
    GENERAL_APP_TITLE = "general.app_title"
    GENERAL_APP_FOOTER = "general.app_footer"
    GENERAL_DEFAULT_LANGUAGE = "general.default_language"

    AUTH_ALLOW_SELF_REGISTER = "auth.allow_self_register"

    DATASET_ALLOW_DUPLICATE_SAMPLE_NAMES_DEFAULT = "dataset.allow_duplicate_sample_names_default"
    IMPORT_MAX_ZIP_BYTES = "import.max_zip_bytes"

    SIMULATION_SEED_RATIO = "simulation.seed_ratio"
    SIMULATION_STEP_RATIO = "simulation.step_ratio"
    SIMULATION_MAX_ROUNDS = "simulation.max_rounds"

    MAINTENANCE_ASSET_GC_ENABLED = "maintenance.asset_gc_enabled"
    MAINTENANCE_ASSET_GC_INTERVAL_HOURS = "maintenance.asset_gc_interval_hours"
    MAINTENANCE_ASSET_GC_ORPHAN_AGE_HOURS = "maintenance.asset_gc_orphan_age_hours"
    MAINTENANCE_RUNTIME_MODE = "maintenance.runtime_mode"
