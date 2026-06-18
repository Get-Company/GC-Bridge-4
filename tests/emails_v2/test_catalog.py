from emails_v2.catalog import MJML_TAGS, MJML_TAG_MAP, MjmlTag


def test_all_layout_tags_present():
    names = [t.name for t in MJML_TAGS]
    for tag in ["mj-section", "mj-column", "mj-wrapper", "mj-group"]:
        assert tag in names, f"{tag} missing from catalog"


def test_all_content_tags_present():
    names = [t.name for t in MJML_TAGS]
    for tag in ["mj-text", "mj-image", "mj-button", "mj-divider", "mj-spacer", "mj-table", "mj-raw"]:
        assert tag in names


def test_all_advanced_tags_present():
    names = [t.name for t in MJML_TAGS]
    for tag in ["mj-hero", "mj-navbar", "mj-social", "mj-carousel", "mj-accordion"]:
        assert tag in names


def test_tag_has_required_fields():
    for tag in MJML_TAGS:
        assert tag.name, f"tag missing name"
        assert tag.category in ("layout", "content", "advanced"), f"{tag.name} bad category"
        assert tag.icon, f"{tag.name} missing icon"
        assert isinstance(tag.default_attributes, dict)
        assert isinstance(tag.droppable_in, list)


def test_tag_map_lookup():
    assert MJML_TAG_MAP["mj-text"].category == "content"
    assert MJML_TAG_MAP["mj-section"].category == "layout"
