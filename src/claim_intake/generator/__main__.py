"""`python -m claim_intake.generator`: generate, verify, then write the dev packets.

A development tool, so it takes plain arguments and has no pydantic settings.
Every packet is generated and verified before the first file is written, so a
failed label leaves the output folder as it was. Logs are one JSON line per
event on stderr, with packet ids and counts, never claim text or values.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from claim_intake import logging as app_logging
from claim_intake.generator.io import OutputNotEmptyError, write_packets
from claim_intake.generator.noise import NoiseFn, apply_noise
from claim_intake.generator.pipeline import DEV_COUNT, DEV_SEED, generate_dataset
from claim_intake.generator.verify import PacketVerificationError
from claim_intake.logging import claim_id_var

logger = logging.getLogger("claim_intake.generator")

DEFAULT_OUT = Path("data/dev")


def run(
    seed: int, count: int, out: Path, *, force: bool = False, noise: NoiseFn = apply_noise
) -> list[Path]:
    """Generate and verify every packet, then write one file per packet."""
    logger.info("generating %d packets", count)
    packets = generate_dataset(seed, count, noise)
    logger.info("verified %d packets", len(packets))
    paths = write_packets(packets, out, force=force)
    for packet in packets:
        token = claim_id_var.set(packet.packet_id)
        try:
            logger.info("packet written")
        finally:
            claim_id_var.reset(token)
    logger.info("wrote %d packets", len(paths))
    return paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m claim_intake.generator",
        description="Generate, verify and write synthetic claim packets.",
    )
    parser.add_argument("--seed", type=int, default=DEV_SEED, help="master seed")
    parser.add_argument("--count", type=int, default=DEV_COUNT, help="number of packets")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder")
    parser.add_argument(
        "--force", action="store_true", help="delete existing pkt-*.json files in --out first"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; returns the process exit code."""
    args = _parser().parse_args(argv)
    if args.count < 1:
        _parser().error("--count must be at least 1")
    app_logging.configure()
    try:
        run(args.seed, args.count, args.out, force=args.force)
    except PacketVerificationError as error:
        token = claim_id_var.set(error.packet_id)
        try:
            logger.error("packet failed verification: %s", "; ".join(error.problems))
        finally:
            claim_id_var.reset(token)
        return 1
    except OutputNotEmptyError as error:
        logger.error("%s; pass --force to replace them", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
