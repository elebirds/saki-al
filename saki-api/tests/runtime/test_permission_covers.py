from saki_api.modules.access.domain.rbac.permission import parse_permission


def test_specific_permission_does_not_cover_all_permissions_wildcard() -> None:
    have = parse_permission("project:create:all")
    required = parse_permission("*:*:all")
    assert have.covers(required) is False


def test_all_permissions_wildcard_covers_specific_permission() -> None:
    have = parse_permission("*:*:all")
    required = parse_permission("project:read:assigned")
    assert have.covers(required) is True


def test_specific_action_does_not_cover_other_action_same_target() -> None:
    have = parse_permission("project:create:all")
    required = parse_permission("project:read:assigned")
    assert have.covers(required) is False


def test_target_wildcard_on_required_side_does_not_match_specific_target() -> None:
    have = parse_permission("dataset:read:all")
    required = parse_permission("*:read:assigned")
    assert have.covers(required) is False


def test_action_wildcard_on_required_side_does_not_match_specific_action() -> None:
    have = parse_permission("dataset:read:all")
    required = parse_permission("dataset:*:assigned")
    assert have.covers(required) is False

