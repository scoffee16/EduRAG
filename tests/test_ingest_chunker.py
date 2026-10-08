import pytest

from edurage.ingest.chunker import chunk_pages
from edurage.ingest.embedder import EMBEDDING_DIMENSIONS, HashingEmbedder


def test_chunker_uses_500_character_windows_with_80_character_overlap() -> None:
    text = "".join(str(index % 10) for index in range(1000))

    chunks = chunk_pages([{"page": 2, "text": text}])

    assert [len(chunk["text"]) for chunk in chunks] == [500, 500, 160]
    assert chunks[0]["text"][-80:] == chunks[1]["text"][:80]
    assert chunks[1]["text"][-80:] == chunks[2]["text"][:80]
    assert [chunk["chunk_index"] for chunk in chunks] == [0, 1, 2]
    assert {chunk["page"] for chunk in chunks} == {2}
    assert {chunk["modality"] for chunk in chunks} == {"text"}


def test_chunk_indexes_increase_across_pages_and_blank_pages_are_skipped() -> None:
    chunks = chunk_pages(
        [
            {"page": 1, "text": "one"},
            {"page": 2, "text": "   \n"},
            {"page": 3, "text": "three"},
        ]
    )

    assert [(chunk["page"], chunk["chunk_index"]) for chunk in chunks] == [(1, 0), (3, 1)]


def test_hashing_embedder_is_deterministic_and_returns_1024_dimensions() -> None:
    embedder = HashingEmbedder()

    first = embedder.embed(["same input", "different input"])
    second = embedder.embed(["same input", "different input"])

    assert first == second
    assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in first)
    assert first[0] != first[1]


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (500, 500), (500, -1)],
)
def test_chunker_rejects_invalid_window_parameters(chunk_size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_pages([{"page": 1, "text": "text"}], chunk_size=chunk_size, overlap=overlap)
