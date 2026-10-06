import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_store():
    path = ROOT / "custom_components" / "ai_workspace" / "store.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_store", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Store


Store = _load_store()


def test_get_session_rejects_empty_ids(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    created = store.create_session("user-1", "cursor")
    assert store.get_session("user-1", created.id) is not None
    assert store.get_session("user-1", None) is None  # type: ignore[arg-type]
    assert store.get_session(None, created.id) is None  # type: ignore[arg-type]
    assert store.import_session(None, "x", "cursor", "T", None, "", "") is False  # type: ignore[arg-type]
    assert store.import_session("user-1", None, "cursor", "T", None, "", "") is False  # type: ignore[arg-type]
    store.close()
