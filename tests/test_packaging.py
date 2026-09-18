"""Packaging contracts for installable command-line entry points."""

from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_console_script_modules_are_included_in_wheel() -> None:
    """Every console-script target must be selected by the Hatch wheel build."""
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    scripts = config["project"]["scripts"]
    wheel_config = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    packaged_directories = {Path(path).name for path in wheel_config["packages"]}
    forced_files = wheel_config.get("force-include", {})

    for command, target in scripts.items():
        module = target.split(":", 1)[0]
        top_level_module = module.split(".", 1)[0]

        if "." in module:
            assert top_level_module in packaged_directories, (
                f"Console script {command!r} targets {module!r}, but its package "
                "is not selected by the Hatch wheel build"
            )
            continue

        module_file = f"{module}.py"
        assert (PROJECT_ROOT / module_file).is_file(), (
            f"Console script {command!r} targets missing module {module_file!r}"
        )
        assert forced_files.get(module_file) == module_file, (
            f"Console script {command!r} targets top-level module {module!r}, but "
            "the module is not force-included at the wheel root"
        )
