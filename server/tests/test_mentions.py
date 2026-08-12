"""The mention parser — pure functions over a string, no database.

`@[Display Name](user:<uuid>)`. The uuid is the identity and the name is a rendering snapshot,
which is why a display-name change cannot orphan a mention and why the parser reads only the
uuid.
"""

from __future__ import annotations

import uuid

from app.services.mentions import mention_names, newly_mentioned, parse_mentions

ALICE = uuid.UUID("11111111-1111-1111-1111-111111111111")
BOB = uuid.UUID("22222222-2222-2222-2222-222222222222")


def mention(name: str, user_id: uuid.UUID) -> str:
    return f"@[{name}](user:{user_id})"


# --- parsing ------------------------------------------------------------------------------------


def test_a_single_mention_is_found():
    assert parse_mentions(f"Morning {mention('Alice', ALICE)}!") == [ALICE]


def test_several_mentions_come_back_in_the_order_they_were_written():
    body = f"{mention('Bob', BOB)} and {mention('Alice', ALICE)} — thoughts?"
    assert parse_mentions(body) == [BOB, ALICE]


def test_mentioning_the_same_person_three_times_is_emphasis_not_three_notifications():
    body = " ".join(mention("Alice", ALICE) for _ in range(3))
    assert parse_mentions(body) == [ALICE]


def test_a_body_with_no_mentions_yields_none():
    assert parse_mentions("Just a comment about the weather") == []
    assert parse_mentions("") == []


def test_the_name_is_a_rendering_snapshot_not_an_identity():
    """Two mentions of one person under different names still resolve to one uuid — which is
    the whole reason the uuid is stored rather than the name."""
    body = f"{mention('Alice', ALICE)} {mention('Alice Smith', ALICE)}"
    assert parse_mentions(body) == [ALICE]
    assert mention_names(body)[ALICE] == "Alice"


# --- malformed markup degrades to plain text -------------------------------------------------


def test_markup_with_no_user_prefix_is_plain_text():
    assert parse_mentions(f"@[Alice]({ALICE})") == []


def test_markup_with_something_that_is_not_a_uuid_is_plain_text():
    assert parse_mentions("@[Alice](user:not-a-uuid)") == []
    assert parse_mentions("@[Alice](user:11111111-1111-1111-1111-11111111111)") == []


def test_an_unclosed_mention_is_plain_text():
    assert parse_mentions(f"@[Alice(user:{ALICE})") == []


def test_a_bare_at_name_is_plain_text():
    """The picker always writes the full markup; typing `@alice` by hand notifies nobody, which
    is what stops a mention being something you can fake with a keyboard."""
    assert parse_mentions("@alice what do you think?") == []


# --- the edit diff --------------------------------------------------------------------------------


def test_an_edit_that_adds_somebody_notifies_only_them():
    before = f"Hi {mention('Alice', ALICE)}"
    after = f"Hi {mention('Alice', ALICE)} and {mention('Bob', BOB)}"
    assert newly_mentioned(before, after) == [BOB]


def test_an_edit_that_changes_nothing_notifies_nobody():
    body = f"Hi {mention('Alice', ALICE)}"
    assert newly_mentioned(body, body) == []


def test_fixing_a_typo_does_not_re_ping_the_person_already_mentioned():
    before = f"Hi {mention('Alice', ALICE)}, teh barn?"
    after = f"Hi {mention('Alice', ALICE)}, the barn?"
    assert newly_mentioned(before, after) == []


def test_removing_a_mention_notifies_nobody():
    before = f"{mention('Alice', ALICE)} {mention('Bob', BOB)}"
    after = mention("Alice", ALICE)
    assert newly_mentioned(before, after) == []


def test_re_adding_a_removed_mention_in_the_same_edit_counts_as_new():
    """The diff is against the *previous stored body*, not against every body there has ever
    been — there is no vote history and no mention history, and reconstructing one would be a
    feature nobody asked for."""
    assert newly_mentioned("nobody", mention("Alice", ALICE)) == [ALICE]
