"""Tests for LLM prompt sanitization and output path validation."""
from the_maid.models import LLMManager


def test_sanitize_filename_strips_control_chars():
    m = LLMManager()
    assert m._sanitize_filename_for_prompt("foo\x00bar\x1fbaz") == "foobarbaz"
    assert "\x7f" not in m._sanitize_filename_for_prompt("abc\x7f")


def test_sanitize_filename_escapes_quotes_and_backslashes():
    m = LLMManager()
    assert m._sanitize_filename_for_prompt('a"b\\c') == 'a\\"b\\\\c'


def test_sanitize_filename_clamps_length():
    m = LLMManager()
    long_name = "a" * 300
    assert len(m._sanitize_filename_for_prompt(long_name)) == 255


def test_categorization_result_rejects_escape_path(monkeypatch, tmp_path):
    m = LLMManager()
    monkeypatch.setattr(m, "_loaded", True)
    # stub LLM to avoid real model
    monkeypatch.setattr(
        m,
        "llm",
        lambda prompt, **kwargs: {
            "choices": [
                {
                    "text": '{"proposed_path": "/tmp/evil.txt", "tags": [], "rationale": "x"}'
                }
            ]
        },
    )

    metadata = {"path": str(tmp_path / "file.txt"), "filename": "file.txt"}
    result = m.categorize_file(metadata, sandbox_folders=[str(tmp_path)])
    assert result["proposed_path"] == metadata["path"]
    assert "rejected" in result["rationale"]


def test_categorization_result_accepts_safe_path(monkeypatch, tmp_path):
    m = LLMManager()
    monkeypatch.setattr(m, "_loaded", True)
    safe_path = str(tmp_path / "sub" / "file.txt")
    monkeypatch.setattr(
        m,
        "llm",
        lambda prompt, **kwargs: {
            "choices": [
                {
                    "text": f'{{"proposed_path": "{safe_path}", "tags": ["t"], "rationale": "ok"}}'
                }
            ]
        },
    )

    metadata = {"path": safe_path, "filename": "file.txt"}
    result = m.categorize_file(metadata, sandbox_folders=[str(tmp_path)])
    assert result["proposed_path"] == safe_path
    assert result["tags"] == ["t"]
