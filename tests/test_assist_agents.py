import importlib.util
from pathlib import Path


def _const():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "const.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_const_assist", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_builtin_home_assistant_conversation_is_the_intent_matcher() -> None:
    fn = _const().is_builtin_assist_agent
    assert fn("conversation.home_assistant")
    assert fn("homeassistant")
    assert fn("conversation.home_assistant", "homeassistant")
    assert not fn("conversation.cursor")
    assert not fn("conversation.openai")
    assert not fn("conversation.google_generative_ai_conversation")
