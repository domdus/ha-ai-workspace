from app.files import attach_files_to_message, file_events, parse_client_files


def test_parse_yaml_with_empty_mime() -> None:
    files = parse_client_files(
        [
            {"name": "automations.yaml", "mime": "", "text": "id: 1\nalias: Test\n"},
            {"name": "notes.pdf", "mime": "application/pdf", "text": "%PDF"},
            {"name": "empty.yaml", "mime": "text/yaml", "text": "   "},
        ]
    )
    assert len(files) == 1
    assert files[0]["name"] == "automations.yaml"
    assert "alias: Test" in files[0]["text"]
    assert file_events(files) == [{"type": "file", "name": "automations.yaml"}]


def test_attach_files_to_message_keeps_prompt() -> None:
    files = parse_client_files([{"name": "foo.yml", "text": "mode: single\n"}])
    out = attach_files_to_message("Fix this automation", files)
    assert out.startswith("Fix this automation")
    assert "```yaml" in out
    assert "mode: single" in out
    assert "foo.yml" in out
