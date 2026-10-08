import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_store():
    path = ROOT / "custom_components" / "ai_workspace" / "store.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_store_prune", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Store


Store = _load_store()


def test_prune_keeps_newest_unpinned_and_all_pinned(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    ids = []
    for _ in range(5):
        ids.append(store.create_session("user-1", "cursor").id)
        time.sleep(0.01)
        store.touch(ids[-1])
    store.set_pinned("user-1", ids[0], True)
    store.set_pinned("user-1", ids[1], True)
    # Unpinned newest → oldest: ids[4], ids[3], ids[2]. Keep 2 → drop ids[2].
    dropped = store.prune_sessions("user-1", keep=2)
    remaining = {item.id for item in store.list_sessions("user-1")}
    assert set(dropped) == {ids[2]}
    assert remaining == {ids[0], ids[1], ids[3], ids[4]}
    store.close()


def test_prune_does_not_drop_other_users(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    for _ in range(4):
        created = store.create_session("user-a", "cursor")
        time.sleep(0.01)
        store.touch(created.id)
    other = store.create_session("user-b", "cursor").id
    store.prune_sessions("user-a", keep=1)
    assert store.get_session("user-b", other) is not None
    assert len(store.list_sessions("user-a")) == 1
    store.close()
