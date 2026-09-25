from app.models import Brand, EngineType
from app.query_planner import QUERY_TEMPLATES, build_queries


def make_brand(**overrides) -> Brand:
    data = {
        "id": "acme",
        "display_name": "Acme Care",
        "official_domains": ["acme.example"],
        "official_phones": ["+910000000000"],
        "aliases": ["Acme Support"],
    }
    data.update(overrides)
    return Brand(**data)


def test_templates_cover_display_name_and_each_alias():
    brand = make_brand()
    queries = build_queries(brand)
    search_queries = [q for q in queries if q.engine == EngineType.GOOGLE_SEARCH]

    expected_names = ["Acme Care", "Acme Support"]
    assert len(search_queries) == len(expected_names) * len(QUERY_TEMPLATES)
    assert {q.query_text for q in search_queries} == {
        template.format(name=name) for name in expected_names for template in QUERY_TEMPLATES
    }


def test_search_queries_use_india_geo_params():
    for query in build_queries(make_brand()):
        if query.engine == EngineType.GOOGLE_SEARCH:
            assert query.params["gl"] == "in"
            assert query.params["hl"] == "en"
            assert query.params["q"] == query.query_text


def test_ads_transparency_query_keyed_on_first_official_domain():
    brand = make_brand(official_domains=["primary.example", "secondary.example"])
    ads = [q for q in build_queries(brand) if q.engine == EngineType.ADS_TRANSPARENCY]

    assert len(ads) == 1
    assert ads[0].query_text == "primary.example"
    assert ads[0].params["text"] == "primary.example"


def test_ads_transparency_query_skipped_without_domains():
    brand = make_brand(official_domains=[])
    assert [q for q in build_queries(brand) if q.engine == EngineType.ADS_TRANSPARENCY] == []


def test_one_maps_and_one_local_query_per_brand_india_wide():
    brand = make_brand()
    queries = build_queries(brand)

    maps = [q for q in queries if q.engine == EngineType.GOOGLE_MAPS]
    local = [q for q in queries if q.engine == EngineType.GOOGLE_LOCAL]

    assert len(maps) == 1
    assert len(local) == 1
    assert maps[0].query_text == "Acme Care customer care"
    assert local[0].query_text == "Acme Care customer care"
    assert maps[0].params["type"] == "search"
    assert maps[0].params["ll"].startswith("@")
    assert maps[0].params["gl"] == "in" and maps[0].params["hl"] == "en"
    assert local[0].params["location"] == "India"
    assert local[0].params["gl"] == "in" and local[0].params["hl"] == "en"


def test_query_count_for_brand_with_one_alias():
    # 2 names x 5 search templates + 1 ads + 1 maps + 1 local
    assert len(build_queries(make_brand())) == 13
