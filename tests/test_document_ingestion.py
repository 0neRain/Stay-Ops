from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.document_ingestion import (
    DocumentProcessingError,
    chunk_text,
    extract_document_text,
    resolve_storage_path,
    sanitize_filename,
)


def test_sanitize_filename_removes_paths_and_control_characters() -> None:
    assert sanitize_filename("../../private/house\x00 manual.txt") == "house manual.txt"
    assert sanitize_filename(r"C:\uploads\rules.md") == "rules.md"
    assert sanitize_filename(None) == "document"


def test_extract_and_normalize_utf8_text() -> None:
    text = extract_document_text(
        b"  Wi-Fi: guest-network  \r\n\r\n\r\nCheckout: 10:00\t\r\n",
        filename="manual.txt",
        maximum_characters=1_000,
    )

    assert text == "Wi-Fi: guest-network\n\nCheckout: 10:00"


def test_extract_rejects_documents_without_readable_text() -> None:
    with pytest.raises(DocumentProcessingError, match="No readable text"):
        extract_document_text(
            b" \n\t\n ",
            filename="empty.md",
            maximum_characters=1_000,
        )


def test_storage_path_cannot_escape_upload_root(tmp_path: Path) -> None:
    with pytest.raises(DocumentProcessingError, match="path is invalid"):
        resolve_storage_path(tmp_path / "uploads", "../private.txt")


def test_chunk_text_respects_size_and_overlap() -> None:
    text = " ".join(f"instruction-{index}" for index in range(100))

    chunks = chunk_text(text, maximum_characters=120, overlap=20)

    assert len(chunks) > 1
    assert all(1 <= len(chunk) <= 120 for chunk in chunks)
    assert chunks[0].startswith("instruction-0")
    assert chunks[-1].endswith("instruction-99")


@pytest.mark.parametrize(
    ("maximum_characters", "overlap"),
    [(0, 0), (100, -1), (100, 100), (100, 101)],
)
def test_chunk_text_rejects_invalid_configuration(maximum_characters: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text(
            "house manual",
            maximum_characters=maximum_characters,
            overlap=overlap,
        )


def test_settings_reject_chunk_overlap_that_cannot_make_progress() -> None:
    with pytest.raises(ValueError, match="DOCUMENT_CHUNK_OVERLAP"):
        Settings(
            app_env="test",
            document_chunk_characters=400,
            document_chunk_overlap=400,
        )
