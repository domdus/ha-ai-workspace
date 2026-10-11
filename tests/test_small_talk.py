from pathlib import Path

from app.small_talk import wants_house_tools

_ROOT = Path(__file__).resolve().parents[1]


def test_greeting_skips_tools() -> None:
    for text in ("Hello?", "Hello!", "hi", "Hallo", "Guten Morgen", "Thanks", "Danke!", "How are you?"):
        assert wants_house_tools(text) is False


def test_real_requests_keep_tools() -> None:
    for text in (
        "Yes",
        "Ja",
        "Ok",
        "Do it",
        "Hello, turn on the light",
        "What's the balcony soil moisture?",
        "",
    ):
        assert wants_house_tools(text) is True


def test_runtime_and_integration_use_the_same_rule() -> None:
    app = (_ROOT / "ai_workspace/app/small_talk.py").read_text()
    integration = (_ROOT / "custom_components/ai_workspace/small_talk.py").read_text()
    assert app == integration
