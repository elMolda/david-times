from conftest import make_item

from davidtimes.dedupe import canonical_url, cluster_items, similar, title_tokens


def test_canonical_url_strips_tracking_and_www():
    assert canonical_url("http://www.Example.com/a/b/?utm_source=x&id=3#top") == \
        "https://example.com/a/b?id=3"
    assert canonical_url("https://example.com/story/amp") == "https://example.com/story"


def test_title_tokens_ignore_accents_and_stopwords():
    assert title_tokens("La economía de Colombia crece") == {"economia", "colombia", "crece"}


def test_similar_requires_real_overlap():
    a = title_tokens("Verstappen wins Las Vegas Grand Prix")
    b = title_tokens("Max Verstappen wins in Las Vegas")
    c = title_tokens("Arsenal beat Chelsea at Emirates")
    assert similar(a, b)
    assert not similar(a, c)


def test_cluster_merges_same_url_keeping_richest_and_groups_titles():
    items = [
        make_item("Verstappen wins Las Vegas Grand Prix", "https://bbc.co.uk/x?utm_source=rss", "BBC"),
        make_item("Verstappen wins Las Vegas Grand Prix", "https://www.bbc.co.uk/x", "BBC", content="full"),
        make_item("Max Verstappen wins in Las Vegas thriller", "https://autosport.com/y", "Autosport"),
        make_item("Arsenal beat Chelsea", "https://espn.com/z", "ESPN"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 2
    top = clusters[0]
    assert top.id == "c1"
    assert top.outlets == ["BBC", "Autosport"]
    assert top.lead.content == "full"
