from app.ingestion.tasks import (
    DEFAULT_BATCH_SIZE,
    LARGE_FILE_BATCH_SIZE,
    PDF_HEAVY_BATCH_SIZE,
    _split_elements_for_batches,
)


def _build_elements(count: int):
    return [{"type": "paragraph", "text": f"line-{i}", "metadata": {"page_number": i + 1}} for i in range(count)]


def test_split_elements_uses_default_batch_size_for_normal_file():
    elements = _build_elements(DEFAULT_BATCH_SIZE + 5)
    batches = _split_elements_for_batches(elements, {"file_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "file_size": 1024})
    assert len(batches) == 2
    assert len(batches[0]) == DEFAULT_BATCH_SIZE


def test_split_elements_uses_large_file_batch_size():
    elements = _build_elements(LARGE_FILE_BATCH_SIZE + 3)
    batches = _split_elements_for_batches(
        elements,
        {"file_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "file_size": 60 * 1024 * 1024},
    )
    assert len(batches[0]) == LARGE_FILE_BATCH_SIZE


def test_split_elements_uses_pdf_heavy_batch_size_when_many_pages():
    elements = _build_elements(150)
    batches = _split_elements_for_batches(elements, {"file_type": "application/pdf", "file_size": 1024})
    assert len(batches[0]) == PDF_HEAVY_BATCH_SIZE
