from memoryfield_tool import config, index, search


def test_vector_ranking_exact_match(field_dir, fake_embed, monkeypatch):
    alpha_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    alpha_vec = fake_embed([f"search_document: {alpha_text}"])[0]
    index.build_index(field_dir, progress=False)

    monkeypatch.setattr("memoryfield_tool.search.embed.embed_texts", lambda texts: [alpha_vec])
    results = search.search_field(field_dir, "alpha")
    assert results[0].filename == "alpha.md"
    assert results[0].distance == 0.0
    assert results[0].summary == "Notes about alpha things."


def test_distance_threshold_filters(field_dir, monkeypatch):
    def controlled(texts):
        out = []
        for t in texts:
            if t.startswith("search_document:"):
                if "Alpha" in t:
                    out.append([1.0] + [0.0] * 767)
                else:
                    out.append([0.0, 1.0] + [0.0] * 766)
            else:
                out.append([1.0, 0.1] + [0.0] * 766)
        return out

    monkeypatch.setattr("memoryfield_tool.embed.embed_texts", controlled)
    index.build_index(field_dir, progress=False)

    results = search.search_field(field_dir, "some query")
    filenames = [r.filename for r in results]
    assert "alpha.md" in filenames
    assert all(r.distance is not None for r in results)
    assert all(r.distance < 0.7 for r in results)
    assert "beta.md" not in filenames
    assert "gamma.md" not in filenames


def test_substring_fallback_no_index(field_dir):
    results = search.search_field(field_dir, "beta")
    assert [r.filename for r in results] == ["beta.md"]
    assert results[0].summary == "Notes about beta things."
    assert results[0].distance is None


def test_substring_fallback_when_embed_none(field_dir, fake_embed, monkeypatch):
    index.build_index(field_dir, progress=False)
    monkeypatch.setattr("memoryfield_tool.embed.embed_texts", lambda texts: None)
    results = search.search_field(field_dir, "gamma")
    assert [r.filename for r in results] == ["gamma.md"]
    assert all(r.distance is None for r in results)


def test_substring_fallback_case_insensitive(field_dir):
    results = search.search_field(field_dir, "GAMMA")
    assert [r.filename for r in results] == ["gamma.md"]


def test_search_all_multiple_fields(field_dir, tmp_path):
    field2 = tmp_path / "field2"
    field2.mkdir()
    (field2 / "work.md").write_text(
        "---\ntitle: Work\nsummary: Work notes\n---\n\nwork stuff\n", encoding="utf-8"
    )
    f1 = config.Field(
        name="notes", transport="local", location=str(field_dir), created="", last_used=""
    )
    f2 = config.Field(
        name="work", transport="local", location=str(field2), created="", last_used=""
    )

    results = search.search_all([f1, f2], "gamma")
    assert [(name, r.filename) for name, r in results] == [("notes", "gamma.md")]

    results2 = search.search_all([f1, f2], "work")
    assert [(name, r.filename) for name, r in results2] == [("work", "work.md")]
