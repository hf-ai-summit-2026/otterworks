import shutil
import subprocess

from otter_cli import cli as cli_module


def test_completion_includes_parser_commands_and_flags(capsys):
    commands = cli_module._subcommand_parsers(cli_module.build_parser())

    for shell in ("bash", "zsh"):
        assert cli_module.main(["completion", shell]) == 0
        script = capsys.readouterr().out
        assert all(name in script for name in commands)
        assert "--dry-run" in script
        assert "--replace" in script
        if shell == "bash" and shutil.which("bash"):
            subprocess.run(
                ["bash", "-n"],
                input=script,
                text=True,
                capture_output=True,
                check=True,
            )
