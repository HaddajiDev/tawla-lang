"""CLI commands: version and help."""

import pytest

from tawla import __version__
from tawla.cli import main


def test_version_subcommand(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == f"tawlac {__version__}"


def test_version_flag(capsys):
    # argparse's version action prints and exits.
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"tawlac {__version__}"


def test_short_version_flag(capsys):
    with pytest.raises(SystemExit):
        main(["-V"])
    assert __version__ in capsys.readouterr().out


def test_help_no_args_prints_usage(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage: tawlac" in out
    assert "run" in out and "new" in out


def test_help_command(capsys):
    assert main(["help"]) == 0
    assert "usage: tawlac" in capsys.readouterr().out


def test_help_for_specific_command(capsys):
    assert main(["help", "run"]) == 0
    out = capsys.readouterr().out
    assert "run" in out and ".twl" in out


def test_build_stub_reports_not_implemented(capsys):
    assert main(["build", "x.twl"]) != 0
    assert "isn't implemented yet" in capsys.readouterr().err
