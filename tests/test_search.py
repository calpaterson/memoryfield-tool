from memoryfield_tool import config, index, search, transport


def test_vector_ranking_exact_match(field_dir, fake_embed, monkeypatch):
    alpha_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    alpha_vec = fake_embed([f"search_document: {alpha_text}"])[0]
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)

    monkeypatch.setattr("memoryfield_tool.search.embed.embed_texts", lambda texts: [alpha_vec])
    results = search.search_field(transport.local(field_dir), index.index_path(field_dir), "alpha")
    assert results[0].filename == "alpha.md"
    assert results[0].distance == 0.0
    assert results[0].summary == "Notes about alpha things."
    assert results[0].frontmatter == {
        "title": "Alpha Notes",
        "summary": "Notes about alpha things.",
        "created": "2026-01-01T09:00:00Z",
        "updated": "2026-01-02T09:00:00Z",
        "uuid": results[0].frontmatter["uuid"],
    }


def _polarised_embed(texts: list[str]) -> list[list[float]]:
    """Docs mentioning Alpha sit at similarity 0.995 to the query; all others at 0.0995."""
    out = []
    for t in texts:
        if t.startswith("search_document:") and "Alpha" in t:
            out.append([1.0] + [0.0] * 767)
        elif t.startswith("search_document:"):
            out.append([0.0, 1.0] + [0.0] * 766)
        else:
            out.append([1.0, 0.1] + [0.0] * 766)
    return out


def test_vector_threshold_filters_below_default(field_dir, monkeypatch):
    monkeypatch.setattr("memoryfield_tool.embed.embed_texts", _polarised_embed)
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    results = search.search_field(
        transport.local(field_dir), index.index_path(field_dir), "some query"
    )
    assert [r.filename for r in results] == ["alpha.md"]


def test_vector_large_max_distance_returns_ranked(field_dir, monkeypatch):
    monkeypatch.setattr("memoryfield_tool.embed.embed_texts", _polarised_embed)
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    results = search.search_field(
        transport.local(field_dir),
        index.index_path(field_dir),
        "some query",
        max_distance=1.0,
    )
    filenames = [r.filename for r in results]
    assert set(filenames) == {"alpha.md", "beta.md", "gamma.md", "index.md"}
    assert filenames[0] == "alpha.md"
    assert all(r.distance is not None for r in results)
    assert results[0].distance < results[1].distance


def test_vector_returns_all_above_default_threshold(field_dir, fake_embed):
    for i in range(25):
        (field_dir / f"page-{i:02d}.md").write_text(
            f"---\ntitle: Page {i}\n---\n\nbody {i}\n", encoding="utf-8"
        )
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    results = search.search_field(
        transport.local(field_dir), index.index_path(field_dir), "anything"
    )
    assert len(results) == 29


def test_vector_result_without_frontmatter(field_dir, fake_embed):
    (field_dir / "plain.md").write_text("# Just a heading\n", encoding="utf-8")
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    results = search.search_field(transport.local(field_dir), index.index_path(field_dir), "plain")
    plain = next(r for r in results if r.filename == "plain.md")
    assert plain.frontmatter is None


def test_substring_fallback_no_index(field_dir):
    results = search.search_field(transport.local(field_dir), index.index_path(field_dir), "beta")
    assert [r.filename for r in results] == ["beta.md"]
    assert results[0].summary == "Notes about beta things."
    assert results[0].distance is None
    assert results[0].frontmatter == {
        "title": "Beta Notes",
        "summary": "Notes about beta things.",
        "created": "2026-01-01T09:00:00Z",
        "updated": "2026-01-02T09:00:00Z",
        "uuid": results[0].frontmatter["uuid"],
    }


def test_substring_fallback_page_without_frontmatter(field_dir):
    (field_dir / "plain.md").write_text("# Just a heading\n", encoding="utf-8")
    results = search.search_field(transport.local(field_dir), index.index_path(field_dir), "plain")
    assert [r.filename for r in results] == ["plain.md"]
    assert results[0].frontmatter is None


def test_substring_fallback_when_embed_none(field_dir, fake_embed, monkeypatch):
    index.build_index(transport.local(field_dir), index.index_path(field_dir), progress=False)
    monkeypatch.setattr("memoryfield_tool.embed.embed_texts", lambda texts: None)
    results = search.search_field(transport.local(field_dir), index.index_path(field_dir), "gamma")
    assert [r.filename for r in results] == ["gamma.md"]
    assert all(r.distance is None for r in results)


def test_substring_fallback_case_insensitive(field_dir):
    results = search.search_field(transport.local(field_dir), index.index_path(field_dir), "GAMMA")
    assert [r.filename for r in results] == ["gamma.md"]


def test_search_all_multiple_fields(field_dir, tmp_path):
    field2 = tmp_path / "field2"
    field2.mkdir()
    (field2 / "work.md").write_text(
        "---\ntitle: Work\nsummary: Work notes\n---\n\nwork stuff\n", encoding="utf-8"
    )
    f1 = config.Field(name="notes", transport="local", location=str(field_dir))
    f2 = config.Field(name="work", transport="local", location=str(field2))

    results, errors = search.search_all([f1, f2], "gamma")
    assert [(name, r.filename) for name, r in results] == [("notes", "gamma.md")]
    assert errors == []

    results2, errors2 = search.search_all([f1, f2], "work")
    assert [(name, r.filename) for name, r in results2] == [("work", "work.md")]
    assert errors2 == []


def test_search_all_skips_dead_field(field_dir, tmp_path):
    live = config.Field(name="notes", transport="local", location=str(field_dir))
    dead = config.Field(name="dead", transport="local", location=str(tmp_path / "gone"))
    results, errors = search.search_all([live, dead], "gamma")
    assert [(n, r.filename) for n, r in results] == [("notes", "gamma.md")]
    assert len(errors) == 1
    assert errors[0][0] == "dead"
    assert "not a directory" in errors[0][1]
