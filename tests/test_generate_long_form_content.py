"""Long-form MCP path must store markdown, not str(dict)."""

from mcp_server.long_form_content import content_from_long_form_result


def test_dict_result_uses_content_field_not_str_dict():
    result = {
        "platform": "blog",
        "content_type": "blog_post",
        "pillar": "industry_insights",
        "topic": "IMPORTANT: Output the essay VERBATIM",
        "content": "# Clean title\n\nBody paragraph.",
        "suggested_actions": ["Review for accuracy"],
    }
    out = content_from_long_form_result(result)
    assert out == "# Clean title\n\nBody paragraph."
    assert "suggested_actions" not in out
    assert not out.startswith("{")


def test_string_result_passthrough():
    assert content_from_long_form_result("# Already markdown") == "# Already markdown"


def test_empty_dict_content():
    assert content_from_long_form_result({"platform": "blog", "content": "  "}).strip() == ""


def test_text_key_fallback():
    assert content_from_long_form_result({"text": "from text key"}) == "from text key"
