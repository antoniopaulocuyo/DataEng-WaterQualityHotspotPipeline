"""scripts/check_readme.py: links and backticked paths are checked, URLs and runtime folders are not."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_readme", Path(__file__).resolve().parents[1] / "scripts" / "check_readme.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def test_missing_references_found(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "here.md").write_text("x")
    readme = tmp_path / "README.md"
    readme.write_text("[ok](docs/here.md) and `docs/here.md`\n[bad](docs/gone.md)\n`src/gone.py` https://x.org/docs/a.md\n"
                      "`data/raw/x.csv` `outputs/y.csv` [anchor](docs/here.md#top)\n", encoding="utf-8")
    assert cr.missing(readme, tmp_path) == [(2, "docs/gone.md"), (3, "src/gone.py")]
    assert cr.main(["x", str(readme)]) == 1                       # exit code 1 when something is missing
    readme.write_text("[ok](docs/here.md)\n", encoding="utf-8")
    assert cr.main(["x", str(readme)]) == 0                       # and 0 when everything exists


def test_missing_readme_gives_clear_exit_code(tmp_path, capsys):
    assert cr.main(["x", str(tmp_path / "nope.md")]) == 2
    assert "not found" in capsys.readouterr().out
