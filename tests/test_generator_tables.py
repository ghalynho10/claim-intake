"""The value tables, formatters and phrase tables (spec 0003, Values and formatters).

Pure functions, tested without fakes. Every formatter output must parse back to
its canonical value, and no table word may be another table's word, or a name
could match a street and a label would lie.
"""

import itertools
import random
import re
from datetime import date, timedelta

import pytest

from claim_intake.fields import FieldName
from claim_intake.generator.families import FAMILIES
from claim_intake.generator.formatters import (
    DATE_FORMAT_COUNT,
    PHONE_FORMAT_COUNT,
    PHRASE_CUES,
    PHRASES,
    TIME_FORMAT_COUNT,
    all_phrases,
    count_protected_words,
    format_date,
    format_phone,
    format_time,
    has_word,
    has_word_normalized,
    parse_date,
    parse_phone,
    parse_phrase,
    parse_time,
)
from claim_intake.generator.models import FAMILY_ORDER, Scenario
from claim_intake.generator.values import (
    LOSS_DESCRIPTIONS,
    LOSS_WINDOW_END,
    LOSS_WINDOW_START,
    VEHICLES,
    WORD_TABLES,
    collisions,
    sample_scenario,
)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def test_no_table_word_is_another_tables_word() -> None:
    words = {name: set().union(*(_words(v) for v in table)) for name, table in WORD_TABLES.items()}
    for (a, a_words), (b, b_words) in itertools.combinations(words.items(), 2):
        assert not a_words & b_words, f"{a} and {b} share words"


def test_tables_are_ascii_and_unique() -> None:
    for name, table in WORD_TABLES.items():
        assert all(value.isascii() for value in table), name
        if name != "models":
            assert len(set(table)) == len(table), name


def test_every_model_belongs_to_one_make() -> None:
    models = [model for _, group in VEHICLES for model in group]
    assert len(models) == len(set(models))


def test_no_description_heading_or_filler_holds_a_phrase() -> None:
    texts = list(LOSS_DESCRIPTIONS) + [t for spec in FAMILIES for t in spec.fixed_text]
    for field in PHRASES:
        for text in texts:
            for phrase in all_phrases(field):
                assert not has_word_normalized(text, phrase), (field, text)


def test_every_phrase_parses_back_and_none_contains_another() -> None:
    phrases = [
        (field, value, text)
        for field, by_family in PHRASES.items()
        for by_value in by_family.values()
        for value, text in by_value.items()
    ]
    for field, value, text in phrases:
        assert parse_phrase(field, text) == value
        assert parse_phrase(field, text.upper()) == value
    for (_, _, a), (_, _, b) in itertools.permutations(phrases, 2):
        assert a == b or not has_word_normalized(b, a), (a, b)


def test_every_phrase_carries_its_family_cue() -> None:
    for field, by_family in PHRASES.items():
        for family, by_value in by_family.items():
            cue = PHRASE_CUES[field][family]
            assert all(cue in text for text in by_value.values()), (field, family)


def test_bare_yes_or_no_is_not_a_phrase() -> None:
    for field in PHRASES:
        assert parse_phrase(field, "yes") is None
        assert parse_phrase(field, "no") is None


@pytest.mark.parametrize("style", range(DATE_FORMAT_COUNT))
def test_every_loss_window_date_parses_back(style: int) -> None:
    day = LOSS_WINDOW_START
    while day <= LOSS_WINDOW_END:
        surface = format_date(day.isoformat(), style)
        assert "2026" in surface
        assert parse_date(surface) == day.isoformat()
        day += timedelta(days=1)


@pytest.mark.parametrize("style", range(TIME_FORMAT_COUNT))
def test_every_time_of_day_parses_back(style: int) -> None:
    for hour, minute in itertools.product(range(24), range(60)):
        value = f"{hour:02d}:{minute:02d}"
        surface = format_time(value, style)
        assert "about" not in surface
        assert parse_time(surface) == value


@pytest.mark.parametrize("style", range(PHONE_FORMAT_COUNT))
def test_every_fictional_phone_parses_back(style: int) -> None:
    for last in range(100, 200):
        value = f"555-{last:04d}"
        assert parse_phone(format_phone(value, style)) == value


@pytest.mark.parametrize(
    ("parse", "junk"),
    [
        (parse_date, "February 30, 2026"),
        (parse_date, "14/03/2026"),
        (parse_time, "13:30 PM"),
        (parse_time, "24:00"),
        (parse_phone, "555-0200"),
        (parse_phone, "555-1234"),
    ],
)
def test_parsers_reject_what_no_formatter_writes(parse: object, junk: str) -> None:
    assert callable(parse)
    assert parse(junk) is None


def test_date_formats_avoid_the_email_header_shape() -> None:
    # The Date header writes "14 Mar 2026"; no loss date surface may look like it.
    value = date(2026, 3, 14).isoformat()
    surfaces = [format_date(value, style) for style in range(DATE_FORMAT_COUNT)]
    assert not any(has_word_normalized("Sat, 14 Mar 2026 09:05:31", s) for s in surfaces)


def test_sampled_scenarios_are_collision_free() -> None:
    for index in range(60):
        scenario = sample_scenario(index, random.Random(index))
        assert collisions(scenario) == []


def test_collisions_catch_a_make_inside_the_other_vehicle() -> None:
    scenario = sample_scenario(0, random.Random(0))
    assert scenario.vehicle_make is not None
    clash = scenario.model_copy(update={"other_party_vehicle": f"{scenario.vehicle_make} Camry"})
    assert (FieldName.VEHICLE_MAKE, FieldName.OTHER_PARTY_VEHICLE) in collisions(clash)


def test_people_are_four_different_people() -> None:
    for index in range(60):
        s: Scenario = sample_scenario(index, random.Random(index))
        names = [s.reporter_name, s.driver_name, s.other_party_name]
        names += [s.injuries_who] if s.injuries_who else []
        firsts = [n.split()[0] for n in names if n]
        lasts = [n.split()[1] for n in names if n]
        assert len(set(firsts)) == len(firsts)
        assert len(set(lasts)) == len(lasts)


def test_family_order_is_the_registry_order() -> None:
    assert tuple(spec.family for spec in FAMILIES) == FAMILY_ORDER[: len(FAMILIES)]


# --- checks added by /test ------------------------------------------------------


@pytest.mark.parametrize(
    ("haystack", "needle", "found"),
    [
        ("Ref PA1234567.", "PA1234567", True),
        ("Ref PA12345678.", "PA1234567", False),
        ("Ref XPA1234567", "PA1234567", False),
        ("Policy number: PA1", "Policy number:", True),
        ("Policy number:x", "Policy number:", False),
        ("It was 2:30 PM.", "2:30 PM", True),
        ("It was 12:30 PM.", "2:30 PM", False),
        ("maria lopez", "Maria Lopez", False),
    ],
)
def test_has_word_matches_only_on_word_boundaries(haystack: str, needle: str, found: bool) -> None:
    # covers: AC-3 (the surface is matched on word boundaries)
    assert has_word(haystack, needle) is found


def test_normalized_match_ignores_case_and_runs_of_whitespace() -> None:
    # covers: AC-4 (checks run after lowercasing and collapsing whitespace)
    assert has_word_normalized("Luckily NO  one\twas\nhurt.", "No one was hurt")
    assert not has_word_normalized("Nobody was hurt.", "No one was hurt")


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("It was not about 2:30 PM, no, never.", 4),
        ("Nothing noted; notice the boat.", 0),
        ("NOT about", 2),
    ],
)
def test_protected_words_are_counted_as_whole_words_only(text: str, count: int) -> None:
    # covers: AC-6 (the per line count of not, no, never, about)
    assert count_protected_words(text) == count


def test_sampled_values_stay_in_their_ranges() -> None:
    # Values and formatters, Planning rules "Dates"
    for index in range(100):
        s = sample_scenario(index, random.Random(index))
        assert s.loss_date is not None and s.loss_time is not None
        assert LOSS_WINDOW_START <= date.fromisoformat(s.loss_date) <= LOSS_WINDOW_END
        assert "06:00" <= s.loss_time <= "22:59"
        assert s.vehicle_year is not None and 2008 <= int(s.vehicle_year) <= 2023
        assert s.policy_number is not None
        assert re.fullmatch(r"[A-Z]{2}\d{7}", s.policy_number)
        if s.police_report_number is not None:
            assert re.fullmatch(r"[A-Z]{2}\d{7}", s.police_report_number)
        assert s.reporter_contact is not None
        assert re.fullmatch(r"555-01\d\d", s.reporter_contact)


def test_replaced_descriptions_stay_out_and_the_table_keeps_its_length() -> None:
    # Planning rules "Loss descriptions": guards the first AC-10 read. Entries
    # were replaced in place, so positions (and every packet's draws) hold.
    assert len(LOSS_DESCRIPTIONS) == 8
    for gone in (
        "Hit a parked car while reversing out of a space",
        "Clipped a mirror passing a delivery truck",
        "Slid into a guardrail on a wet ramp",
    ):
        assert gone not in LOSS_DESCRIPTIONS
