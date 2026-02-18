from __future__ import annotations

from saki_api.modules.annotation.extensions.data_formats.fedo.config import get_fedo_config


def test_get_fedo_config_ignores_unrelated_env_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/saki",
                "INTERNAL_TOKEN=dev-secret",
                "DISPATCHER_ADMIN_TARGET=localhost:50052",
                "RUNTIME_DOMAIN_GRPC_BIND=0.0.0.0:50053",
            ]
        ),
        encoding="utf-8",
    )

    config = get_fedo_config()
    assert config.dpi == 200
    assert config.max_file_size_mb == 50


def test_get_fedo_config_accepts_runtime_overrides():
    config = get_fedo_config(
        {
            "dpi": 144,
            "max_file_size_mb": 10,
            "mapping_time_gap_threshold": 72,
        }
    )
    assert config.dpi == 144
    assert config.max_file_size_mb == 10
    assert config.mapping_time_gap_threshold == 72
