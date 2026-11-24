"""The value tables and the scenario sampler: what really happened in a packet.

Plain tuples of ASCII strings, curated so no word of one table is a word of
another, which keeps a name from ever matching a street or a make. The sampler
draws every true value from these tables with the packet's own generator and
redraws, deterministically, until no value's surface sits inside another's.
The parent truths and the "no true value" rule are fixed by packet index, as
spec 0003's Planning rules set them.
"""

import random
from datetime import date

from claim_intake.fields import FieldName
from claim_intake.generator.formatters import (
    FIELD_KINDS,
    Kind,
    has_word_normalized,
    surface_forms,
)
from claim_intake.generator.models import Family, Scenario, family_for

FIRST_NAMES: tuple[str, ...] = (
    "Maria",
    "Daniel",
    "Priya",
    "Tomas",
    "Aisha",
    "Kenji",
    "Olga",
    "Rafael",
    "Ingrid",
    "Mateo",
    "Leila",
    "Dmitri",
    "Sofia",
    "Arjun",
    "Hana",
    "Emeka",
    "Lucia",
    "Bjorn",
    "Fatima",
    "Nikolai",
    "Yara",
    "Caleb",
    "Amara",
    "Henrik",
    "Mei",
    "Omar",
    "Greta",
    "Jamal",
    "Elena",
    "Tariq",
    "Noor",
    "Felix",
    "Zara",
    "Ivan",
    "Keiko",
    "Diego",
    "Astrid",
    "Ravi",
    "Talia",
    "Anton",
)

LAST_NAMES: tuple[str, ...] = (
    "Lopez",
    "Whitfield",
    "Nair",
    "Okafor",
    "Lindqvist",
    "Tanaka",
    "Petrov",
    "Moreau",
    "Castillo",
    "Haddad",
    "Novak",
    "Kowalski",
    "Brennan",
    "Achebe",
    "Delgado",
    "Sorensen",
    "Takahashi",
    "Ferreira",
    "Mbeki",
    "Rasmussen",
    "Ivanova",
    "Quintero",
    "Abernathy",
    "Yilmaz",
    "Kapoor",
    "Halvorsen",
    "Dubois",
    "Varga",
    "Okonkwo",
    "Esposito",
    "Lindgren",
    "Chaudhry",
    "Marchetti",
    "Nakamura",
    "Szabo",
    "Oyelaran",
    "Fitzgerald",
    "Calloway",
    "Brandt",
    "Mendoza",
)

STREETS: tuple[str, ...] = (
    "Maple Street",
    "Cedar Avenue",
    "Birch Lane",
    "Willow Road",
    "Juniper Drive",
    "Aspen Court",
    "Sycamore Way",
    "Hawthorn Street",
    "Linden Avenue",
    "Magnolia Lane",
    "Chestnut Road",
    "Alder Drive",
    "Poplar Street",
    "Hickory Avenue",
    "Laurel Lane",
    "Spruce Road",
    "Cypress Drive",
    "Redwood Court",
    "Larch Way",
    "Hemlock Street",
)

CITIES: tuple[str, ...] = (
    "Riverton",
    "Fairhaven",
    "Millbrook",
    "Ashford",
    "Brookdale",
    "Clearwater",
    "Eastport",
    "Glenwood",
    "Harborview",
    "Kingsley",
    "Lakemont",
    "Northgate",
    "Oakridge",
    "Pinecrest",
    "Rockport",
    "Stonebridge",
    "Westfield",
    "Thornbury",
    "Marlow",
    "Danbury",
)

# Two letter codes that are not also English words (no OR, IN, ME, OK, HI).
STATES: tuple[str, ...] = ("CA", "TX", "WA", "AZ", "NJ", "NC")

# Each make with models it really sells, so no packet reads "Honda Camry".
VEHICLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Toyota", ("Camry", "Corolla", "Prius")),
    ("Honda", ("Civic", "Accord", "Odyssey")),
    ("Subaru", ("Outback", "Forester", "Impreza")),
    ("Mazda", ("Miata", "Tribute")),
    ("Hyundai", ("Elantra", "Sonata", "Tucson")),
    ("Kia", ("Sorento", "Optima", "Sportage")),
    ("Nissan", ("Altima", "Sentra", "Rogue")),
    ("Volkswagen", ("Jetta", "Passat", "Tiguan")),
    ("Chevrolet", ("Malibu", "Impala", "Equinox")),
)
MAKES: tuple[str, ...] = tuple(make for make, _ in VEHICLES)
MODELS: tuple[str, ...] = tuple(model for _, models in VEHICLES for model in models)

INSURERS: tuple[str, ...] = (
    "Harborline Mutual",
    "Keystone Assurance",
    "Summitview Casualty",
    "Northwind Indemnity",
    "Bluecrest Mutual",
    "Ironvale Assurance",
)

LOSS_DESCRIPTIONS: tuple[str, ...] = (
    "Rear ended while stopped at a red light",
    "Sideswiped by a car changing lanes",
    "Hit a parked car while reversing out of a space",
    "Struck at an intersection by a car that ran a stop sign",
    "Clipped a mirror passing a delivery truck",
    "Slid into a guardrail on a wet ramp",
    "Bumped by a car pulling out of a driveway",
    "Hit from the side in a parking lot",
)

# The tables whose words must never be another table's words (a unit test checks).
WORD_TABLES: dict[str, tuple[str, ...]] = {
    "first_names": FIRST_NAMES,
    "last_names": LAST_NAMES,
    "streets": STREETS,
    "cities": CITIES,
    "states": STATES,
    "makes": MAKES,
    "models": MODELS,
    "insurers": INSURERS,
    "loss_descriptions": LOSS_DESCRIPTIONS,
}

RELATIONSHIPS_BY_FAMILY: dict[Family, tuple[str, ...]] = {
    Family.INFORMAL_EMAIL: ("self", "spouse", "parent", "child"),
    Family.FORMAL_EMAIL: ("agent",),
    Family.WEB_FORM: ("self", "spouse", "parent", "child", "agent"),
}

LOSS_WINDOW_START = date(2026, 1, 1)
LOSS_WINDOW_END = date(2026, 10, 31)
VEHICLE_YEARS: tuple[str, ...] = tuple(str(year) for year in range(2008, 2024))

_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
_MAX_DRAWS = 1000


def make_reference_number(rng: random.Random) -> str:
    """A policy or police report number: two letters and seven digits, one token."""
    letters = "".join(rng.choice(_LETTERS) for _ in range(2))
    return f"{letters}{rng.randrange(10_000_000):07d}"


def _person_names(rng: random.Random, count: int) -> list[str]:
    """`count` people with pairwise different first and last names."""
    firsts = rng.sample(FIRST_NAMES, count)
    lasts = rng.sample(LAST_NAMES, count)
    return [f"{first} {last}" for first, last in zip(firsts, lasts, strict=True)]


def injuries_truth(index: int) -> str:
    """The fixed dev set rule: injuries in every even packet."""
    return "yes" if index % 2 == 0 else "no"


def police_truth(index: int) -> str:
    """The fixed dev set rule: a police report when `index % 4` is 0 or 1."""
    return "yes" if index % 4 in (0, 1) else "no"


def has_insurer(index: int) -> bool:
    """The other party's insurer has no true value in every fourth packet."""
    return index % 4 != 3


def _draw(index: int, rng: random.Random) -> Scenario:
    family = family_for(index)
    reporter, driver, other_party, passenger = _person_names(rng, 4)
    loss_day = date.fromordinal(
        rng.randrange(LOSS_WINDOW_START.toordinal(), LOSS_WINDOW_END.toordinal() + 1)
    )
    make, models = rng.choice(VEHICLES)
    other_make, other_models = rng.choice(VEHICLES)
    location = (
        f"{rng.randrange(100, 1000)} {rng.choice(STREETS)}, "
        f"{rng.choice(CITIES)}, {rng.choice(STATES)}"
    )
    injuries = injuries_truth(index)
    police = police_truth(index)
    return Scenario(
        policy_number=make_reference_number(rng),
        reporter_name=reporter,
        reporter_contact=f"555-{rng.randrange(100, 200):04d}",
        reporter_relationship=rng.choice(RELATIONSHIPS_BY_FAMILY[family]),
        loss_date=loss_day.isoformat(),
        loss_time=f"{rng.randrange(6, 23):02d}:{rng.randrange(60):02d}",
        loss_location=location,
        loss_description=rng.choice(LOSS_DESCRIPTIONS),
        vehicle_year=rng.choice(VEHICLE_YEARS),
        vehicle_make=make,
        vehicle_model=rng.choice(models),
        driver_name=driver,
        other_party_name=other_party,
        other_party_vehicle=f"{other_make} {rng.choice(other_models)}",
        other_party_insurer=rng.choice(INSURERS) if has_insurer(index) else None,
        injuries_reported=injuries,
        injuries_who=passenger if injuries == "yes" else None,
        police_report_filed=police,
        police_report_number=make_reference_number(rng) if police == "yes" else None,
    )


def collisions(scenario: Scenario) -> list[tuple[FieldName, FieldName]]:
    """Pairs of fields where a surface of one sits, on word boundaries, inside a
    surface of the other. Phrase fields are fixed template text and are skipped."""
    forms = {
        field: surface_forms(field, value)
        for field in FieldName
        if FIELD_KINDS[field] is not Kind.PHRASE and (value := scenario.value(field)) is not None
    }
    found: list[tuple[FieldName, FieldName]] = []
    for field, needles in forms.items():
        for other, haystacks in forms.items():
            if other is field:
                continue
            if any(has_word_normalized(h, n) for n in needles for h in haystacks):
                found.append((field, other))
    return found


def sample_scenario(index: int, rng: random.Random) -> Scenario:
    """Draw the true facts of packet `index`, redrawing until no value collides.

    A redraw is part of sampling (the generator keeps going from where it is),
    not a retry of verification: verification never repairs a packet.
    """
    for _ in range(_MAX_DRAWS):
        scenario = _draw(index, rng)
        if not collisions(scenario):
            return scenario
    raise RuntimeError(f"no collision free scenario for packet index {index}")
