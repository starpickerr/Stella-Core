import pytest

from agent.apple.category_links import reconcile_names, validate_links


def test_name_sync_is_independent_of_content_direction():
    assert reconcile_names("课程", "课程", "大学课程", "课程") == ("apple_to_stella", "大学课程")
    assert reconcile_names("课程", "课程", "课程", "大学课程") == ("stella_to_apple", "大学课程")
    assert reconcile_names("课程", "课程", "大学课程", "学期课") == ("conflict", None)
    assert reconcile_names("课程", "课程", "大学课程", "大学课程") == ("aligned", "大学课程")
    assert reconcile_names("课程", "课程", "课程", "课程") == ("unchanged", "课程")


def test_links_are_one_to_one():
    validate_links([
        {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": True},
    ])
    with pytest.raises(ValueError, match="one-to-one"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": True},
            {"apple_id": "cal-b", "stella_id": "study", "direction": "export", "enabled": True},
        ])
    with pytest.raises(ValueError, match="one-to-one"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": True},
            {"apple_id": "cal-a", "stella_id": "work", "direction": "export", "enabled": True},
        ])


def test_link_rows_reject_bad_direction_empty_ids_and_non_bool_enabled():
    with pytest.raises(ValueError, match="direction"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "both", "enabled": True},
        ])
    with pytest.raises(ValueError, match="apple_id"):
        validate_links([
            {"apple_id": "", "stella_id": "study", "direction": "import", "enabled": True},
        ])
    with pytest.raises(ValueError, match="enabled"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": 1},
        ])
