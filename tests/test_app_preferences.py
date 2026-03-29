from __future__ import annotations

from app_preferences import AppPreferences, AppPreferencesStore


def test_app_preferences_default_to_auto_compile_off(tmp_path) -> None:
    store = AppPreferencesStore(tmp_path / "ui_preferences.json")

    preferences = store.load()

    assert preferences.auto_compile_enabled is False


def test_app_preferences_store_persists_auto_compile_state(tmp_path) -> None:
    storage_path = tmp_path / "ui_preferences.json"
    store = AppPreferencesStore(storage_path)

    store.save(AppPreferences(auto_compile_enabled=True))
    reloaded = AppPreferencesStore(storage_path).load()

    assert storage_path.exists()
    assert reloaded.auto_compile_enabled is True
