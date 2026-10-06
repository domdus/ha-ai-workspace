from app.images import caption_for, cursor_payload, image_events, parse_client_images

PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_caption_for_images_only() -> None:
    assert caption_for("  ", 0) == ""
    assert caption_for("", 1) == "Look at this image."
    assert caption_for("", 3) == "Look at these 3 images."
    assert caption_for("What is this?", 1) == "What is this?"
    assert caption_for("", 0, 1) == "Look at this file."
    assert caption_for("", 0, 3) == "Look at these 3 files."
    assert caption_for("", 1, 1) == "Look at these attachments."


def test_parse_client_images_strips_data_url_and_rejects_junk() -> None:
    images = parse_client_images(
        [
            {"name": "kitchen.png", "mime": "image/png", "data": f"data:image/png;base64,{PNG_1PX}"},
            {"name": "note.pdf", "mime": "application/pdf", "data": PNG_1PX},
            {"name": "empty.png", "mime": "image/png", "data": ""},
        ]
    )
    assert len(images) == 1
    assert images[0]["name"] == "kitchen.png"
    assert images[0]["mime"] == "image/png"
    events = image_events(images)
    assert events[0]["type"] == "image"
    assert events[0]["src"].startswith("data:image/png;base64,")


def test_parse_client_images_caps_at_four() -> None:
    raw = [{"name": f"{i}.png", "mime": "image/png", "data": PNG_1PX} for i in range(6)]
    assert len(parse_client_images(raw)) == 4


def test_cursor_payload_with_images() -> None:
    images = parse_client_images([{"name": "x.png", "mime": "image/png", "data": PNG_1PX}])
    payload = cursor_payload("Look", images)
    if isinstance(payload, dict):
        assert payload["text"] == "Look"
        assert payload["images"][0]["mime_type"] == "image/png"
    else:
        assert getattr(payload, "text", None) == "Look"
        assert getattr(payload, "images", None)
    assert cursor_payload("plain", None) == "plain"
