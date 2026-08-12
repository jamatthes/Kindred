"""`@mention` markup: one grammar, one parser, one diff.

Mentions are stored **inline in the comment body** as ``@[Display Name](user:<uuid>)``
(`voting-comments/design.md` > Mention markup). Two consequences follow from storing the uuid
rather than the name alone, and both are the reason the format looks like this:

* a display-name change never orphans a mention — the link still points at a person;
* rendering needs no lookup table, because the name to draw is already in the markup.

The name inside the brackets is therefore a *snapshot for rendering*, not an identity. The
uuid is the identity, and it is the only part this module reads.

**Who actually gets notified is not decided here.** This module answers "which uuids does this
text mention", as a pure function over a string. Whether each of those uuids is a real account,
on this trip, and not the author is `app/services/comments.py`'s question — it has the
database. A uuid that fails any of those tests renders as plain text and notifies nobody
(V7, and `design.md`'s edge-case table), which is why an unknown uuid is not an error here.
"""

from __future__ import annotations

import re
import uuid

#: ``@[Display Name](user:<uuid>)``.
#:
#: The name is anything but a closing bracket, so a name containing brackets is simply not
#: matched rather than matched wrongly — the picker never produces one, and a hand-typed
#: malformed mention is meant to degrade to plain text.
MENTION_PATTERN = re.compile(
    r"@\[([^\]]*)\]\(user:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)"
)


def parse_mentions(body: str) -> list[uuid.UUID]:
    """Every uuid mentioned in `body`, deduplicated, in first-appearance order.

    Deduplicated because mentioning somebody three times in one comment is emphasis, not three
    notifications. Order is preserved so a caller rendering "you and 2 others were mentioned"
    names them in the order the author wrote them.
    """
    seen: list[uuid.UUID] = []
    known: set[uuid.UUID] = set()
    for _name, raw in MENTION_PATTERN.findall(body or ""):
        try:
            parsed = uuid.UUID(raw)
        except ValueError:  # pragma: no cover - the pattern already constrains the shape
            continue
        if parsed not in known:
            known.add(parsed)
            seen.append(parsed)
    return seen


def mention_names(body: str) -> dict[uuid.UUID, str]:
    """The rendering snapshot: uuid -> the name as it was written. First occurrence wins."""
    names: dict[uuid.UUID, str] = {}
    for name, raw in MENTION_PATTERN.findall(body or ""):
        try:
            parsed = uuid.UUID(raw)
        except ValueError:  # pragma: no cover
            continue
        names.setdefault(parsed, name)
    return names


def newly_mentioned(previous_body: str, next_body: str) -> list[uuid.UUID]:
    """Who the edit *added*, in the order they appear in the new text.

    An edit notifies only the people it newly mentions. Re-notifying everyone on every typo fix
    would train the group to ignore the bell, and the mention they already received still deep-
    links to the comment they are being told about — so the second ping carries no information
    (`design.md`'s edge-case table: "Only newly added mentions notify").
    """
    already = set(parse_mentions(previous_body))
    return [user_id for user_id in parse_mentions(next_body) if user_id not in already]
