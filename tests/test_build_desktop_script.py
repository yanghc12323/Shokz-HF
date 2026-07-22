from pathlib import Path


def test_desktop_build_uses_an_ascii_executable_name():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "build_desktop.ps1").read_text(
        encoding="utf-8"
    )

    assert '"--name", "ShokzEarDownsamplingAnalysis"' in script
