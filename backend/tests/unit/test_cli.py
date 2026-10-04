import pytest

from matchlens import __version__
from matchlens.cli import main


def test_info_reports_active_modes(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["info"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"matchlens {__version__}" in output
    assert "llm_mode=" in output


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out
