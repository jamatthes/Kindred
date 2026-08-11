"""Put the development database into a sensible demo state.

**Development only.** It refuses to run against a database whose name is not the configured
development one, and it is not imported by the app — `app/core/seed.py` is the real first-run
seed and creates only the admin and the trip.

What it makes, and why this shape:

* the seeded ``admin`` becomes the trip **owner** with a real name, a family, and a spouse —
  so the owner is visibly *also* an ordinary head of a family, which is the point of the two
  role kinds being independent;
* a second family with a head, a spouse and a child, to exercise the spouse asymmetry;
* a third family with one member and no home address, so the "not set" state is on screen
  without anyone having to break something to see it;
* an **organiser** who is only a plain member of their own family, because that is the case a
  demo built from heads alone would never show;
* one outstanding invite of each kind, so the invite block is not empty;
* the **three worked-example polls** from `plan/features/polls/requirements.md`, with
  partial votes — so review and the family demo meet the feature's own reference case
  rather than an empty screen.

The destination poll's numbers are chosen so the thing the feature exists to show is
visible on first load: **Cornwall and the Lake District have the same average, and only
the spread tells them apart.** Two people have not voted at all and one has voted
partially, so the non-responder block and the nudge button are both live.

Home addresses are set directly rather than through the endpoint: there is no Google key in
development, and the point of the demo data is the *placed* state, not a live geocode.

Run: ``server/.venv/Scripts/python.exe scripts/seed_demo.py``
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionFactory, engine  # noqa: E402
from app.core.security import hash_password, hash_token  # noqa: E402
from app.models import (  # noqa: E402
    Comment,
    Family,
    FamilyMember,
    Invite,
    Poll,
    PollOption,
    PollScore,
    Trip,
    TripCategorySetting,
    TripOrganiser,
    User,
    UserSettings,
)

DEMO_PASSWORD = "kindred-demo"


async def _person(
    db, username: str, first: str, last: str, *, sharing: bool = False
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(DEMO_PASSWORD),
        first_name=first,
        last_name=last,
        display_name=f"{first} {last}".strip(),
    )
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id, live_location_enabled=sharing))
    return user


async def _seed_polls(db, trip, people: dict[str, User]) -> None:
    """The three polls from the worked example (`plan/features/polls/requirements.md`).

    Scores are partial on purpose. A demo in which everyone has voted hides the two things
    reviewers most need to see: the non-responder block with a live Nudge button, and the
    hatched "not scored yet" cells that prove a silence is not being counted as a zero.
    """
    # The `poll` category's mode governs every poll. Set explicitly so the demo does not
    # depend on whatever admin-console last left it at.
    mode = await db.scalar(
        select(TripCategorySetting).where(
            TripCategorySetting.trip_id == trip.id,
            TripCategorySetting.category == "poll",
        )
    )
    if mode is None:
        db.add(TripCategorySetting(trip_id=trip.id, category="poll", voting_mode="score"))
    else:
        mode.voting_mode = "score"

    owner = people["admin"]

    # --- 1. Where shall we go? — the reference case ------------------------------------
    destinations = Poll(
        trip_id=trip.id,
        title="Where shall we go?",
        description=(
            "Score every option from 1 (really rather not) to 10 (yes please). "
            "Only scores people actually cast count towards the average."
        ),
        kind="score_matrix",
        created_by=owner.id,
        allow_member_options=True,
    )
    db.add(destinations)
    await db.flush()

    located = {
        "York": (53.9600, -1.0873),
        "Cornwall": (50.2660, -5.0527),
        "Somerset": (51.1050, -2.9262),
        "Lake District": (54.4609, -3.0886),
        "Peak District": (53.3403, -1.8120),
    }
    options: dict[str, PollOption] = {}
    for index, (label, (lat, lng)) in enumerate(located.items()):
        option = PollOption(
            poll_id=destinations.id,
            label=label,
            lat=lat,
            lng=lng,
            sort=index,
            created_by=owner.id,
        )
        db.add(option)
        options[label] = option
    await db.flush()

    # Five scorers. Cornwall and the Lake District both average 7.4; Cornwall's spread is
    # 0.5 and the Lake District's is 3.2, so the split flag fires on exactly one of them.
    voters = ["admin", "alex", "jibby", "jas", "stu"]
    matrix = {
        "York":          [5, 6, 5, 6, 5],
        "Cornwall":      [7, 8, 7, 8, 7],
        "Somerset":      [4, 5, 6, 4, 5],
        "Lake District": [10, 10, 10, 3, 4],
        "Peak District": [6, 7, 5, 6, 7],
    }
    for label, scores in matrix.items():
        for username, score in zip(voters, scores, strict=True):
            db.add(
                PollScore(
                    poll_id=destinations.id,
                    option_id=options[label].id,
                    user_id=people[username].id,
                    score=score,
                )
            )

    # One partial responder: Chris has an opinion about two places and not the rest, which
    # is what makes "partly done" visible next to "not started".
    for label, score in (("Cornwall", 9), ("York", 3)):
        db.add(
            PollScore(
                poll_id=destinations.id,
                option_id=options[label].id,
                user_id=people["chris"].id,
                score=score,
            )
        )
    # Alicia and Luis have not started at all.

    db.add(
        Comment(
            subject_type="poll",
            subject_id=destinations.id,
            author_id=people["jas"].id,
            body="The Lake District average looks fine until you see the spread — half of us love it.",
        )
    )
    db.add(
        Comment(
            subject_type="poll",
            subject_id=destinations.id,
            author_id=people["alex"].id,
            body="Cornwall is the safe pick. Nobody scored it below 7.",
        )
    )

    # --- 2. How long shall we go for? — a single-choice poll ----------------------------
    duration = Poll(
        trip_id=trip.id,
        title="How long shall we go for?",
        description="One choice each.",
        kind="options",
        created_by=owner.id,
    )
    db.add(duration)
    await db.flush()
    durations = {}
    for index, label in enumerate(("5 days", "7 days", "10 days")):
        option = PollOption(poll_id=duration.id, label=label, sort=index, created_by=owner.id)
        db.add(option)
        durations[label] = option
    await db.flush()

    # The presence of the row is the choice; the stored 10 is never displayed.
    for username, label in (
        ("admin", "7 days"),
        ("alex", "7 days"),
        ("jibby", "10 days"),
        ("jas", "7 days"),
        ("chris", "5 days"),
    ):
        db.add(
            PollScore(
                poll_id=duration.id,
                option_id=durations[label].id,
                user_id=people[username].id,
                score=10,
            )
        )

    # --- 3. What do we want to do? — decided, and closed --------------------------------
    interests = Poll(
        trip_id=trip.id,
        title="What do we want to do?",
        description="Scoring these shapes what people suggest on the map later.",
        kind="score_matrix",
        created_by=owner.id,
    )
    db.add(interests)
    await db.flush()
    activities = {}
    for index, label in enumerate(
        ("Beaches", "Hiking", "Historic houses", "Food and drink", "Kid-friendly days out")
    ):
        option = PollOption(poll_id=interests.id, label=label, sort=index, created_by=owner.id)
        db.add(option)
        activities[label] = option
    await db.flush()

    interest_matrix = {
        "Beaches":              [9, 8, 9, 7, 8],
        "Hiking":               [6, 9, 4, 8, 5],
        "Historic houses":      [4, 3, 7, 5, 6],
        "Food and drink":       [8, 9, 8, 9, 9],
        "Kid-friendly days out": [7, 6, 8, 7, 7],
    }
    for label, scores in interest_matrix.items():
        for username, score in zip(voters, scores, strict=True):
            db.add(
                PollScore(
                    poll_id=interests.id,
                    option_id=activities[label].id,
                    user_id=people[username].id,
                    score=score,
                )
            )

    # Decided and closed, so the archive presentation and the decision banner are both on
    # screen without anyone having to close a poll to see them.
    interests.decision_option_id = activities["Food and drink"].id
    interests.decided_by = owner.id
    interests.decided_at = datetime.now(UTC)
    interests.status = "closed"
    interests.closed_by = owner.id
    interests.closed_at = datetime.now(UTC)


async def main() -> None:
    if settings.database_url.rstrip("/").endswith("_test"):
        raise SystemExit("Refusing to seed demo data into the test database.")

    async with SessionFactory() as db:
        trip = await db.scalar(select(Trip).order_by(Trip.created_at).limit(1))
        if trip is None:
            raise SystemExit("No trip yet — start the API once so the first-run seed runs.")

        if await db.scalar(select(func.count()).select_from(Family)):
            print("Families already exist; leaving the database alone.")
            return

        admin = await db.scalar(select(User).where(User.is_platform_admin.is_(True)))
        if admin is None:
            raise SystemExit("No seeded admin — start the API once first.")

        # The owner is a person, not just an account.
        admin.first_name, admin.last_name = "Jacob", "Parker"
        admin.display_name = "Jacob Parker"
        trip.name = "Cornwall · July 2027"
        trip.owner_user_id = admin.id

        # --- the owner's own family: owner AND head, which are different things ----------
        parkers = Family(
            trip_id=trip.id,
            name="The Parkers",
            color=1,
            home_address="12 Elm Row, Bristol BS1 4AA",
            home_locality="Bristol",
            home_lat=51.4545,
            home_lng=-2.5879,
            home_geocoded_at=datetime.now(UTC),
            geocode_status="ok",
        )
        db.add(parkers)
        await db.flush()
        db.add(FamilyMember(family_id=parkers.id, user_id=admin.id, role="head"))

        alex = await _person(db, "alex", "Alex", "Parker", sharing=True)
        chris = await _person(db, "chris", "Chris", "Parker")
        db.add(FamilyMember(family_id=parkers.id, user_id=alex.id, role="spouse"))
        db.add(FamilyMember(family_id=parkers.id, user_id=chris.id, role="member"))

        # --- a second family, head + spouse + child: the asymmetry, on screen ------------
        jiangs = Family(
            trip_id=trip.id,
            name="The Jiangs",
            color=5,
            home_address="8 Kelham Bank, Sheffield S3 8SD",
            home_locality="Sheffield",
            home_lat=53.3872,
            home_lng=-1.4701,
            home_geocoded_at=datetime.now(UTC),
            geocode_status="ok",
            member_location_default=True,
        )
        db.add(jiangs)
        await db.flush()
        jibby = await _person(db, "jibby", "Jibby", "Jiang", sharing=True)
        jas = await _person(db, "jas", "Jas", "Jiang", sharing=True)
        alicia = await _person(db, "alicia", "Alicia", "Jiang")
        db.add(FamilyMember(family_id=jiangs.id, user_id=jibby.id, role="head"))
        db.add(FamilyMember(family_id=jiangs.id, user_id=jas.id, role="spouse"))
        # Consented, but switched off by their family — the "you have turned this off for
        # them" row, which is otherwise only reachable by fiddling with the database.
        db.add(
            FamilyMember(
                family_id=jiangs.id,
                user_id=alicia.id,
                role="member",
                location_sharing_allowed=False,
            )
        )

        # --- a third family with no address, so the empty state is visible ---------------
        riveras = Family(trip_id=trip.id, name="The Riveras", color=6)
        db.add(riveras)
        await db.flush()
        luis = await _person(db, "luis", "Luis", "Rivera")
        db.add(FamilyMember(family_id=riveras.id, user_id=luis.id, role="head"))

        # --- an organiser who is a plain member of their own family ----------------------
        # The case a demo built only from heads would never show: trip-level and family-level
        # roles are independent.
        stu = await _person(db, "stu", "Stu", "Rivera")
        db.add(FamilyMember(family_id=riveras.id, user_id=stu.id, role="member"))
        db.add(TripOrganiser(trip_id=trip.id, user_id=stu.id, granted_by=admin.id))

        # --- one outstanding invite of each kind -----------------------------------------
        # The raw tokens are printed below; only their hashes are stored, exactly as in
        # production. They are demo tokens on a development database, not secrets.
        db.add(
            Invite(
                trip_id=trip.id,
                mode="join",
                family_id=jiangs.id,
                token_hash=hash_token("demo-join-the-jiangs"),
                expires_at=datetime.now(UTC) + timedelta(days=7),
                created_by=jibby.id,
            )
        )
        db.add(
            Invite(
                trip_id=trip.id,
                mode="create_family",
                token_hash=hash_token("demo-new-family"),
                expires_at=datetime.now(UTC) + timedelta(days=7),
                created_by=admin.id,
            )
        )

        await _seed_polls(
            db,
            trip,
            {
                "admin": admin,
                "alex": alex,
                "chris": chris,
                "jibby": jibby,
                "jas": jas,
                "alicia": alicia,
                "luis": luis,
                "stu": stu,
            },
        )

        await db.commit()

    await engine.dispose()

    print(
        "Demo data ready.\n"
        f"  owner + head of The Parkers : admin / {settings.seed_admin_password} "
        "(or whatever it was changed to)\n"
        f"  spouse of The Parkers       : alex / {DEMO_PASSWORD}\n"
        f"  head of The Jiangs          : jibby / {DEMO_PASSWORD}\n"
        f"  spouse of The Jiangs        : jas / {DEMO_PASSWORD}\n"
        f"  plain member                : chris / {DEMO_PASSWORD}\n"
        f"  organiser (plain member)    : stu / {DEMO_PASSWORD}\n"
        "  join invite   : /join/demo-join-the-jiangs\n"
        "  new-family    : /join/demo-new-family\n"
        "\n"
        "  Polls: 'Where shall we go?' (open, 5 scorers + 1 partial + 2 not started —\n"
        "  Cornwall and the Lake District both average 7.4, only the spread tells them\n"
        "  apart), 'How long shall we go for?' (single choice), and 'What do we want to\n"
        "  do?' (decided: Food and drink, closed)."
    )


if __name__ == "__main__":
    asyncio.run(main())
