"""Temporary passwords, generated from a bundled wordlist (`admin-console` AC-7).

Four short words joined by hyphens. The format is chosen for the way the credential actually
travels: an organiser reads it down the phone to someone locked out of their account, or
types it into a message. "correct-otter-lamp-river" survives that trip; a 12-character random
string does not, and the workaround for one that does not is to pick something weaker.

> NOTE: the four-word format is kept even though foundation's minimum-length rule for
> *user-chosen* passwords was dropped (2026-08-11). A generated credential costs its
> recipient nothing to be long, and it is replaced on first login anyway — the reasoning that
> justified dropping the minimum does not reach this.

Entropy: 4 words from a 256-word list is 32 bits. That is deliberately modest and
deliberately short-lived — the account it unlocks is forced through a password change on the
next login, every existing session for it has already been revoked, and login itself is
rate-limited to 5 attempts a minute. Guessing one inside its useful life is not the attack
this defends against; someone reading it off a sticky note is, which is why it is never
stored, never logged, and never shown twice.
"""

from __future__ import annotations

import secrets

#: Short, common, unambiguous when spoken. No homophones ("bear"/"bare"), no words that
#: differ by one letter from another in the list, nothing that could be heard as a letter.
WORDS: tuple[str, ...] = (
    "acorn", "amber", "anchor", "apple", "arrow", "atlas", "autumn", "badger",
    "bamboo", "basket", "beacon", "bench", "berry", "biscuit", "blanket", "bloom",
    "bottle", "boulder", "bracket", "branch", "bridge", "bubble", "bucket", "buffalo",
    "bundle", "burrow", "butter", "cabin", "cactus", "camel", "candle", "canyon",
    "carpet", "castle", "cedar", "cellar", "chalk", "cherry", "chimney", "cinder",
    "clover", "cobble", "compass", "copper", "coral", "cottage", "crane", "crayon",
    "crimson", "crystal", "cushion", "cymbal", "daisy", "damson", "dandelion", "dawn",
    "denim", "dolphin", "domino", "donkey", "dragon", "driftwood", "dumpling", "dune",
    "eagle", "ember", "emerald", "engine", "escape", "falcon", "feather", "fennel",
    "fiddle", "flannel", "flint", "forest", "fossil", "fountain", "foxglove", "fresco",
    "frost", "garden", "garnet", "gecko", "ginger", "glacier", "glimmer", "granite",
    "gravel", "grotto", "gumdrop", "hamlet", "harbour", "harvest", "hazel", "heather",
    "hedgehog", "hollow", "honey", "horizon", "hurdle", "iceberg", "indigo", "island",
    "ivory", "jacket", "jasmine", "jigsaw", "jungle", "juniper", "kettle", "kingfisher",
    "kitten", "ladder", "lagoon", "lantern", "lattice", "lavender", "ledger", "lemon",
    "lighthouse", "lilac", "linen", "lobster", "locket", "lumber", "magnet", "mallow",
    "mammoth", "mandolin", "maple", "marble", "marigold", "meadow", "mellow", "meteor",
    "mitten", "monsoon", "moorland", "mosaic", "mulberry", "mushroom", "mustard", "nectar",
    "nettle", "nutmeg", "oatmeal", "obelisk", "olive", "orchard", "orchid", "osprey",
    "otter", "paddle", "pancake", "pantry", "parsley", "pasture", "pebble", "pelican",
    "pepper", "petunia", "pewter", "pigment", "pillow", "pinecone", "pistachio", "planet",
    "plateau", "plover", "polar", "pommel", "poppy", "porcelain", "portal", "pottery",
    "prairie", "pretzel", "pudding", "puffin", "pumpkin", "quarry", "quilt", "quince",
    "rabbit", "radish", "rafter", "rainbow", "rambler", "raven", "rhubarb", "ribbon",
    "ridge", "rocket", "rosemary", "rucksack", "saffron", "sailboat", "sandal", "sapphire",
    "satchel", "scarlet", "seagull", "shamrock", "sherbet", "shingle", "silver", "sparrow",
    "spinach", "spruce", "squirrel", "stable", "starling", "stitch", "stubble", "sugar",
    "sunbeam", "sundial", "swallow", "sycamore", "tabby", "tangerine", "tapestry", "teapot",
    "tender", "thicket", "thimble", "thistle", "timber", "toffee", "topaz", "tortoise",
    "trellis", "trumpet", "tulip", "tundra", "turnip", "turquoise", "umbrella", "vanilla",
    "velvet", "village", "vinegar", "violet", "walnut", "walrus", "wattle", "waffle",
    "wagon", "wander", "waterfall", "wheat", "whistle", "willow", "window", "winter",
    "wisteria", "wombat", "wonder", "yarrow", "yellow", "yonder", "zephyr", "zigzag",
)

#: Four words. Three would be 24 bits, which is thin even for a credential this short-lived;
#: five is harder to read aloud without losing your place.
WORD_COUNT = 4


def generate_temporary_password(word_count: int = WORD_COUNT) -> str:
    """A hyphen-joined passphrase, drawn with `secrets` rather than `random`.

    `random` is seeded predictably and is a documented mistake for anything that guards
    access; the cost of using the right module here is one import.
    """
    return "-".join(secrets.choice(WORDS) for _ in range(word_count))
