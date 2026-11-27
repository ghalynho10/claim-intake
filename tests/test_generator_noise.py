"""The noise stage and its guard (spec 0003, AC-6).

Noise may only touch characters outside protected spans. A noise function that
breaks a span must stop generation with PacketVerificationError.
"""

import random

import pytest

from claim_intake.fields import FieldName
from claim_intake.generator.families.base import Assertion, Line, merge_spans
from claim_intake.generator.noise import apply_noise, no_noise
from claim_intake.generator.pipeline import build_packet, generate_dataset
from claim_intake.generator.verify import PacketVerificationError

TIME = Assertion(FieldName.LOSS_TIME, "14:30", "2:30 PM", "It was at about")
LINE = Line("It was at about 2:30 PM, which is not unusual around Riverton.", (TIME,))


def test_spans_cover_surface_cue_and_protected_words() -> None:
    covered = [LINE.text[start:end] for start, end in LINE.protected_spans()]
    assert "It was at about" in covered
    assert "2:30 PM" in covered
    assert "not" in covered


@pytest.mark.parametrize(
    ("spans", "merged"),
    [
        ([(5, 9), (0, 3)], ((0, 3), (5, 9))),
        ([(0, 4), (2, 6)], ((0, 6),)),
        ([(0, 4), (4, 6)], ((0, 6),)),
        ([(0, 10), (2, 3)], ((0, 10),)),
        ([], ()),
    ],
)
def test_overlapping_or_touching_spans_merge(
    spans: list[tuple[int, int]], merged: tuple[tuple[int, int], ...]
) -> None:
    # covers: AC-6 ("Overlapping spans merge")
    assert merge_spans(spans) == merged


def test_an_email_address_is_a_protected_span() -> None:
    # covers: AC-9 (noise never edits an address, so it stays @example.com)
    line = Line("Please write to claims@example.com tomorrow.")
    covered = [line.text[start:end] for start, end in line.protected_spans()]
    assert "claims@example.com" in covered


def test_noise_never_edits_a_protected_span() -> None:
    for seed in range(300):
        [text] = apply_noise([LINE], random.Random(seed))
        assert text.startswith("It was at about")
        assert "2:30 PM" in text
        assert " not " in text


def test_noise_does_edit_unprotected_words() -> None:
    outputs = {apply_noise([LINE], random.Random(seed))[0] for seed in range(300)}
    assert any("unusual" not in text or "Riverton" not in text for text in outputs)


def test_fixed_and_fully_covered_lines_are_untouched() -> None:
    header = Line("Subject: Car accident report submitted", fixed=True)
    name = Line(
        "Maria Lopez", (Assertion(FieldName.REPORTER_NAME, "Maria Lopez", "Maria Lopez", ""),)
    )
    for seed in range(200):
        assert apply_noise([header, name, Line("")], random.Random(seed)) == [
            header.text,
            name.text,
            "",
        ]


def test_noise_is_part_of_the_dev_set() -> None:
    noisy = generate_dataset(count=20)
    clean = generate_dataset(count=20, noise=no_noise)
    assert noisy != clean
    for a, b in zip(noisy, clean, strict=True):
        assert len(a.documents[0].lines) == len(b.documents[0].lines)


def _break_cues(lines: list[Line], rng: random.Random) -> list[str]:
    """Misspells the cue on every claim line: exactly what noise must never do."""
    del rng
    out = []
    for line in lines:
        text = line.text
        for assertion in line.assertions:
            if len(assertion.cue) > 3:
                text = text.replace(assertion.cue, assertion.cue[:-2] + assertion.cue[-1])
        out.append(text)
    return out


def _drop_negations(lines: list[Line], rng: random.Random) -> list[str]:
    del rng
    return [line.text.replace(" not ", " ").replace("about ", "") for line in lines]


def _add_a_line(lines: list[Line], rng: random.Random) -> list[str]:
    return [*no_noise(lines, rng), "extra"]


def test_span_breaking_noise_stops_generation() -> None:
    with pytest.raises(PacketVerificationError) as caught:
        build_packet(0, noise=_break_cues)
    assert any("noise changed a protected span" in p for p in caught.value.problems)


def test_negation_dropping_noise_stops_generation() -> None:
    # Packet index 0 carries "about" on its loss time line.
    with pytest.raises(PacketVerificationError) as caught:
        build_packet(0, noise=_drop_negations)
    assert any("protected word" in p for p in caught.value.problems)


def test_line_adding_noise_stops_generation() -> None:
    with pytest.raises(PacketVerificationError) as caught:
        build_packet(0, noise=_add_a_line)
    assert caught.value.problems == ["noise: line count changed"]
