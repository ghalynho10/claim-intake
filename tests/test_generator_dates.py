"""Every email is sent after the loss (spec 0003, Planning rules, Dates).

A test rather than a verifier rule, so feature 11 can plant an email sent
before the loss without changing the verifier. It guards the first AC-10 hand
read finding and adds no acceptance criterion.
"""

import random
import re
from datetime import date, datetime

import pytest

from claim_intake.generator.families.email_parts import date_line
from claim_intake.generator.formatters import MONTH_ABBREVIATIONS
from claim_intake.generator.models import Family, Scenario
from claim_intake.generator.pipeline import DEV_SEED, generate_dataset
from claim_intake.generator.values import sample_scenario

_HEADER = re.compile(r"^Date: \w{3}, (\d{2}) (\w{3}) (\d{4}) (\d{2}):(\d{2}):(\d{2}) -0500$")


def _sent(header: str) -> datetime:
    match = _HEADER.match(header)
    assert match, header
    month = MONTH_ABBREVIATIONS.index(match[2]) + 1
    day, year, hour, minute, second = (int(match[i]) for i in (1, 3, 4, 5, 6))
    return datetime(year, month, day, hour, minute, second)


def _loss(scenario: Scenario) -> datetime:
    assert scenario.loss_date is not None and scenario.loss_time is not None
    return datetime.fromisoformat(f"{scenario.loss_date}T{scenario.loss_time}")


def test_every_email_in_a_large_set_is_sent_after_the_loss() -> None:
    emails = 0
    for packet in generate_dataset(DEV_SEED, 200):
        if packet.family is Family.WEB_FORM:
            continue
        header = next(line for line in packet.documents[0].lines if line.startswith("Date: "))
        sent, loss = _sent(header), _loss(packet.scenario)
        assert sent > loss, packet.packet_id
        assert sent.hour != loss.hour or sent.date() != loss.date(), packet.packet_id
        emails += 1
    assert emails > 100


@pytest.mark.parametrize("loss_time", ["21:05", "22:30"])
def test_a_late_loss_is_sent_on_a_later_day(loss_time: str) -> None:
    scenario = sample_scenario(0, random.Random(0)).model_copy(
        update={"loss_date": "2026-05-10", "loss_time": loss_time}
    )
    for seed in range(300):
        sent = _sent(date_line(scenario, random.Random(seed)).text)
        assert date(2026, 5, 11) <= sent.date() <= date(2026, 5, 13)


def test_a_header_already_after_the_loss_keeps_its_draws() -> None:
    # Loss at 06:xx: every sent hour (07 to 21) is later, so nothing is redrawn and
    # the generator is left exactly where the plain draws leave it.
    scenario = sample_scenario(0, random.Random(0)).model_copy(update={"loss_time": "06:10"})
    for seed in range(50):
        rng = random.Random(seed)
        date_line(scenario, rng)
        after_header = rng.random()
        plain = random.Random(seed)
        plain.randrange(4)
        plain.choice([h for h in range(7, 22) if h != 6])
        plain.choice([m for m in range(60) if m != 6])
        plain.randrange(60)
        assert plain.random() == after_header


def test_a_scenario_without_a_loss_time_is_an_error() -> None:
    scenario = sample_scenario(0, random.Random(0)).model_copy(update={"loss_time": None})
    with pytest.raises(ValueError):
        date_line(scenario, random.Random(0))
