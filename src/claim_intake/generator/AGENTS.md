# claim_intake.generator

Synthetic claim packets with known answers, for the extractor (feature 5) and the scoring harness (feature 8). Governing spec: spec 0003 (`docs/specs/0003-synthetic-generator/`, private).

## Commands

```bash
uv run python -m claim_intake.generator                  # 20 dev packets to data/dev/ (seed 2026); refuses a folder holding pkt-*.json
uv run python -m claim_intake.generator --force          # delete existing pkt-*.json in --out first
uv run python -m claim_intake.generator --seed N --count N --out DIR
uv run pytest tests/test_fields.py tests/test_generator_*.py   # no database, no .env, no model
```

## Layout

- `pipeline.py`: the fixed stage order (scenario, plan, render, noise, claims, derive, verify) and `generate_dataset`. `DEV_SEED`, `DEV_COUNT`.
- `values.py` (value tables, scenario sampler), `plan.py` (rotation, parent and child rules), `derive.py` (the answer key), `models.py` (the packet shape).
- `families/`: one renderer per template family, registered in `FAMILIES` (`families/__init__.py`); `base.py` holds the line type and the protected spans.
- `formatters.py`: value formats, parse back, `PHRASES` and `PHRASE_CUES`.
- `noise.py`, `verify.py`, `io.py` (byte stable files and the dataset digest), `__main__.py` (the command).
- The field list is `claim_intake/fields.py` (`FieldName`), shared with every layer.

## Conventions

- Plain typed functions, no I/O outside `io.py` and `__main__.py`. A dev tool: plain `argparse`, no pydantic settings.
- Labels are attached when a line is rendered, never found by searching text, then proven again by `verify_packet` on the final text after noise. Any problem raises `PacketVerificationError`, with no retry and no repair, and nothing is written.
- Evidence is every line that carries the claim's surface. A phrase field's cue must sit inside every one of its phrases (`test_every_phrase_carries_its_family_cue`); a cue alone on another line is not evidence.
- Noise touches only characters outside protected spans (surfaces, cues, `not`, `no`, `never`, `about`) and never adds, removes or reorders lines.
- Determinism: each packet has its own `random.Random(packet_seed(seed, index))`. Never read the clock, the environment or the network, and never iterate a set. Model field declaration order is the JSON key order.
- The bytes depend on the Python version (`requires-python` stays below 3.13). `DEV_DIGEST` in `tests/test_generator_cli.py` pins the dev set. Change it only on purpose: copy the new digest, then read by hand the packets whose hash changed.
- Value tables share no word across tables, so a name never matches a street or a make. Contact data is fictional only (`555-0100` to `555-0199`, `@example.com`).
- Logs and verifier problems carry packet ids, field names and counts, never claim text or values.
- Adding a family: one new module plus one entry in `FAMILIES`, with no change to the packet format or the verifier.
- Generated packets live only in the ignored `data/` folder; never commit them.

## Known limits

- Two claims for one field raise `ValueError` in `derive_expected` and `assemble_claims` (not yet a typed error). Feature 11 (conflicts) and feature 12 (a second document) change this, and the noise check assumes one document.

_Drafted by /sync from the introducing change, worth a quick human pass._
