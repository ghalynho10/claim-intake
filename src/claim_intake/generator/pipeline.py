"""The fixed stage order that turns a seed and an index into a verified packet.

Each packet gets its own random generator, seeded from the master seed and its
index, so packet `i` never changes when the set grows. Noise is an argument so
a test can pass one that breaks a protected span and watch generation stop.
"""

import random
from collections.abc import Callable

from claim_intake.fields import FieldName
from claim_intake.generator.derive import derive_expected
from claim_intake.generator.families import family_spec
from claim_intake.generator.families.base import Line
from claim_intake.generator.models import Claim, Document, EvidenceLine, Packet, family_for
from claim_intake.generator.plan import plan_claims
from claim_intake.generator.values import sample_scenario
from claim_intake.generator.verify import PacketVerificationError, verify_packet

DEV_SEED = 2026
DEV_COUNT = 20
DOCUMENT_ID = "doc-1"

NoiseFn = Callable[[list[Line], random.Random], list[str]]


def no_noise(lines: list[Line], rng: random.Random) -> list[str]:
    """Leave every line as rendered."""
    del rng
    return [line.text for line in lines]


def packet_seed(master_seed: int, index: int) -> int:
    """The seed of packet `index`'s own generator."""
    return master_seed * 10_000 + index


def packet_id(index: int) -> str:
    """`pkt-001` for index 0."""
    return f"pkt-{index + 1:03d}"


def assemble_claims(rendered: list[Line], final: list[str]) -> list[Claim]:
    """One claim per asserted field, listing every line that carries it, with each
    evidence text taken from the final lines (after noise)."""
    claims: list[Claim] = []
    for field in FieldName:
        carrying = [
            (index, assertion)
            for index, line in enumerate(rendered)
            for assertion in line.assertions
            if assertion.field is field
        ]
        if not carrying:
            continue
        first = carrying[0][1]
        if any((a.value, a.surface) != (first.value, first.surface) for _, a in carrying):
            raise ValueError(f"field {field} is written with two different surfaces")
        cue = next((a.cue for _, a in carrying if a.cue), "")
        evidence = [EvidenceLine(index=index, text=final[index]) for index, _ in carrying]
        claims.append(
            Claim(field=field, value=first.value, surface=first.surface, cue=cue, evidence=evidence)
        )
    return claims


def build_packet(index: int, seed: int = DEV_SEED, noise: NoiseFn = no_noise) -> Packet:
    """Scenario, plan, render, noise, derive, verify: one packet or an error."""
    own_seed = packet_seed(seed, index)
    rng = random.Random(own_seed)
    spec = family_spec(family_for(index))
    scenario = sample_scenario(index, rng)
    planned = plan_claims(scenario, index)
    rendered = spec.render(scenario, planned, rng)
    before = [line.text for line in rendered]
    final = noise(rendered, rng)
    pid = packet_id(index)
    if len(final) != len(rendered):
        raise PacketVerificationError(pid, ["noise: line count changed"])
    claims = assemble_claims(rendered, final)
    document = Document(
        document_id=DOCUMENT_ID,
        source_ref=f"{pid}/{DOCUMENT_ID}",
        kind=spec.kind,
        lines=final,
        claims=claims,
    )
    packet = Packet(
        packet_id=pid,
        family=spec.family,
        seed=own_seed,
        scenario=scenario,
        documents=[document],
        expected=derive_expected(scenario, claims),
    )
    problems = verify_packet(packet, before)
    if problems:
        raise PacketVerificationError(pid, problems)
    return packet


def generate_dataset(
    seed: int = DEV_SEED, count: int = DEV_COUNT, noise: NoiseFn = no_noise
) -> list[Packet]:
    """Build and verify `count` packets; any failure raises before anything is returned."""
    return [build_packet(index, seed, noise) for index in range(count)]
