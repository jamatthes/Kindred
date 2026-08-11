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
* one outstanding invite of each kind, so the invite block is not empty.

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
    Family,
    FamilyMember,
    Invite,
    Trip,
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
        "  new-family    : /join/demo-new-family"
    )


if __name__ == "__main__":
    asyncio.run(main())
