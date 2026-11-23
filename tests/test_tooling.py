"""The commit guards and test isolation that feature 2's tooling promises, and
feature 3's import rule.

The `Co-Authored-By` hook runs through pre-commit's own CLI in a throwaway git
repo, with the hook definition read from the real `.pre-commit-config.yaml`, so
a change to that file is what these tests see. No network: the hook is local.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import _TestEnv

ROOT = Path(__file__).resolve().parent.parent
PRE_COMMIT_CONFIG = ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
LINT_IMPORTS = str(Path(sys.executable).parent / "lint-imports")
HOOK_ID = "no-co-authored-by"


def _config() -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(PRE_COMMIT_CONFIG.read_text())
    return config


def _local_hook(hook_id: str) -> dict[str, Any]:
    for repo in _config()["repos"]:
        if repo["repo"] == "local":
            for hook in repo["hooks"]:
                if hook["id"] == hook_id:
                    hook_def: dict[str, Any] = hook
                    return hook_def
    raise AssertionError(f"local hook {hook_id!r} not found in .pre-commit-config.yaml")


@pytest.fixture(scope="module")
def hook_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    """A git repo whose only hook is the real Co-Authored-By guard."""
    repo = tmp_path_factory.mktemp("hook_repo")
    # Drop any GIT_* the caller (a git hook, an IDE) set, so git works in this repo only.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PRE_COMMIT_HOME"] = str(repo / ".pre-commit-cache")
    config = {"repos": [{"repo": "local", "hooks": [_local_hook(HOOK_ID)]}]}
    (repo / ".pre-commit-config.yaml").write_text(yaml.safe_dump(config))
    for cmd in (["git", "init", "-q"], ["git", "add", ".pre-commit-config.yaml"]):
        subprocess.run(cmd, cwd=repo, env=env, check=True, capture_output=True)
    return repo, env


def _check_message(
    hook_repo: tuple[Path, dict[str, str]], message: str
) -> subprocess.CompletedProcess[str]:
    repo, env = hook_repo
    msg_file = repo / "COMMIT_EDITMSG"
    msg_file.write_text(message)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pre_commit",
            "run",
            HOOK_ID,
            "--hook-stage",
            "commit-msg",
            "--commit-msg-filename",
            str(msg_file),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "message",
    [
        "feat: add intake\n\nCo-Authored-By: Someone <someone@example.com>\n",
        "fix: typo\n\nco-authored-by: Someone <someone@example.com>\n",
        "chore: bump\n\nCO-AUTHORED-BY: Someone <someone@example.com>\n",
        "test: cover x\n\nSigned-off-by: Me <me@example.com>\n"
        "Co-Authored-By: Someone <someone@example.com>\n",
    ],
    ids=["title_case", "lower_case", "upper_case", "among_other_trailers"],
)
def test_commit_msg_hook_rejects_a_co_authored_by_trailer(
    hook_repo: tuple[Path, dict[str, str]], message: str
) -> None:
    result = _check_message(hook_repo, message)

    # Exit 1 plus the hook's own "Failed" line, so a pre-commit crash cannot pass as a rejection.
    assert result.returncode == 1
    assert "Failed" in result.stdout
    assert "Co-Authored-By" in result.stdout


@pytest.mark.parametrize(
    "message",
    [
        "feat: add intake\n\nPlain body with no trailer.\n",
        "docs: explain why we never add a co-authored-by: trailer\n",
        "chore: tidy\n\nSigned-off-by: Me <me@example.com>\n",
    ],
    ids=["plain_body", "mention_mid_line", "other_trailer"],
)
def test_commit_msg_hook_accepts_a_message_without_the_trailer(
    hook_repo: tuple[Path, dict[str, str]], message: str
) -> None:
    assert _check_message(hook_repo, message).returncode == 0


def test_pre_commit_install_sets_up_the_commit_msg_hook() -> None:
    # Without commit-msg here, `pre-commit install` skips that stage and the guard never runs.
    assert "commit-msg" in _config()["default_install_hook_types"]
    assert _local_hook(HOOK_ID)["stages"] == ["commit-msg"]


def test_commits_on_main_are_blocked() -> None:
    hooks = [hook for repo in _config()["repos"] for hook in repo["hooks"]]
    guard = next(h for h in hooks if h["id"] == "no-commit-to-branch")
    assert guard["args"] == ["--branch", "main"]


def test_test_settings_ignore_a_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("TEST_DATABASE_URL", "MIGRATE_DATABASE_URL", "ADMIN_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "TEST_DATABASE_URL=postgresql://dotenv@localhost:1/from_dotenv_test\n"
    )
    monkeypatch.chdir(tmp_path)

    env = _TestEnv()

    assert env.test_database_url is None
    # An absolute path (say ROOT / ".env") would dodge the chdir above, so pin the source too.
    assert _TestEnv.model_config.get("env_file") is None


# --- import rule (spec 0002, AC-9) -------------------------------------------


def _lint_imports(cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [LINT_IMPORTS, "--no-cache"], cwd=cwd, env=env, capture_output=True, text=True
    )


def test_import_contract_holds_on_the_repo() -> None:
    result = _lint_imports(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_contract_fails_when_another_layer_imports_the_claims_system_models(
    tmp_path: Path,
) -> None:
    """On a copy of the package, a module outside claims_system imports its models."""
    shutil.copytree(
        ROOT / "src" / "claim_intake",
        tmp_path / "src" / "claim_intake",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "src" / "claim_intake" / "api" / "_probe_violation.py").write_text(
        '"""Deliberate violation for the import contract test."""\n\n'
        "from claim_intake.claims_system.models import ClaimRecord  # noqa: F401\n"
    )
    # PYTHONPATH puts the copy ahead of the editable install.
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "src")}

    result = _lint_imports(tmp_path, env)

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "_probe_violation" in output


def test_import_contract_runs_before_each_commit_and_in_ci() -> None:
    hook = _local_hook("lint-imports")
    assert hook["entry"] == "uv run lint-imports"
    assert hook["pass_filenames"] is False
    workflow: dict[str, Any] = yaml.safe_load(CI_WORKFLOW.read_text())
    lint_steps = [step.get("run") for step in workflow["jobs"]["lint"]["steps"]]
    assert "uv run lint-imports" in lint_steps
