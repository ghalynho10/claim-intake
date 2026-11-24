"""Starter noise: letter swaps in filler words and spacing quirks, nothing else.

Noise runs before verification, so every label is proven on the noisy text.
It edits only characters outside a line's protected spans (claim surfaces,
cues, negation and qualifier words, addresses, machine text), never adds,
removes or reorders lines, and leaves a fully covered line alone. Distractor
numbers and misspelled names are feature 11's hard cases, not noise.
"""

import random
import re
from collections.abc import Callable

from claim_intake.generator.families.base import Line
from claim_intake.generator.formatters import PROTECTED_WORDS

NoiseFn = Callable[[list[Line], random.Random], list[str]]

SWAP_RATE = 0.2
DOUBLE_SPACE_RATE = 0.15
TRAILING_SPACE_RATE = 0.1
_FILLER_WORD = re.compile(r"[A-Za-z]{5,}")


def _mask(line: Line) -> list[bool]:
    mask = [False] * len(line.text)
    for start, end in line.protected_spans():
        mask[start:end] = [True] * (end - start)
    return mask


def _swap_letters(text: str, mask: list[bool], rng: random.Random) -> str:
    """Swap two adjacent letters inside one unprotected word of 5 letters or more."""
    words = [m for m in _FILLER_WORD.finditer(text) if not any(mask[m.start() : m.end()])]
    if not words:
        return text
    word = rng.choice(words)
    at = rng.randrange(word.start(), word.end() - 1)
    swapped = text[:at] + text[at + 1] + text[at] + text[at + 2 :]
    new_word = swapped[word.start() : word.end()]
    if new_word == word.group() or new_word.lower() in PROTECTED_WORDS:
        return text
    return swapped


def _double_a_space(text: str, mask: list[bool], rng: random.Random) -> str:
    """Turn one unprotected space into two."""
    spaces = [i for i, char in enumerate(text) if char == " " and not mask[i]]
    if not spaces:
        return text
    at = rng.choice(spaces)
    return text[:at] + " " + text[at:]


def _noisy(line: Line, rng: random.Random) -> str:
    swap, double, trailing = rng.random(), rng.random(), rng.random()
    text = line.text
    mask = _mask(line)
    if not text or all(mask):
        return text
    if swap < SWAP_RATE:
        text = _swap_letters(text, mask, rng)
    if double < DOUBLE_SPACE_RATE:
        text = _double_a_space(text, mask, rng)
    if trailing < TRAILING_SPACE_RATE:
        text += " "
    return text


def apply_noise(lines: list[Line], rng: random.Random) -> list[str]:
    """The final text of each rendered line, one output line per input line."""
    return [_noisy(line, rng) for line in lines]


def no_noise(lines: list[Line], rng: random.Random) -> list[str]:
    """Leave every line as rendered (for tests that need clean text)."""
    del rng
    return [line.text for line in lines]
