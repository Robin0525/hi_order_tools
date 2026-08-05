from pathlib import Path

import hipersonalization_assistant.config as config_module


def test_packaged_build_ignores_env_beside_executable(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "HIPERSONALIZATION_SELLER_USERNAME=should-not-load\n"
        "HIPERSONALIZATION_SELLER_PASSWORD=should-not-load\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", str(tmp_path / "assistant.exe"))

    assert config_module.load_env() == {}
    assert config_module.load_env(env_path)["HIPERSONALIZATION_SELLER_USERNAME"] == (
        "should-not-load"
    )
