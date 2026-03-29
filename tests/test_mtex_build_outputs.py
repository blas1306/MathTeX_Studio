import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from latex_lang import env_ast
from mtex_executor import ejecutar_mtex
from project_outputs import BUILD_DIRNAME, COMPILE_LOG_FILENAME, ProjectOutputManager

TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "tmp_test_projects"


class ProjectOutputManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TMP_ROOT / f"outputs_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_artifacts_live_under_project_build_directory(self) -> None:
        project_root = self.root / "DemoProject"
        source_path = project_root / "chapters" / "main.mtex"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n", encoding="utf-8")

        manager = ProjectOutputManager()
        artifacts = manager.artifacts_for_source(source_path, project_root=project_root)

        self.assertEqual(artifacts.build_dir, project_root / BUILD_DIRNAME)
        self.assertEqual(artifacts.tex_path, project_root / BUILD_DIRNAME / "main.tex")
        self.assertEqual(artifacts.pdf_path, project_root / BUILD_DIRNAME / "main.pdf")
        self.assertEqual(artifacts.compile_log_path, project_root / BUILD_DIRNAME / COMPILE_LOG_FILENAME)


class EjecutarMtexBuildOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TMP_ROOT / f"build_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_root = self.root / "BuildProject"
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.source_path = self.project_root / "main.mtex"
        self.source_path.write_text(
            "\\documentclass{article}\n\\begin{document}\nHello build output\n\\end{document}\n",
            encoding="utf-8",
        )
        self.build_dir = self.project_root / BUILD_DIRNAME

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_ejecutar_mtex_writes_outputs_to_build_dir(self) -> None:
        calls: list[tuple[str, str, bool, str | None]] = []

        def _fake_pdflatex(
            tex_filename: str,
            cwd: str,
            draftmode: bool = False,
            output_dir: str | None = None,
            synctex: bool = False,
        ):
            del synctex
            calls.append((tex_filename, cwd, draftmode, output_dir))
            target_dir = Path(output_dir or cwd)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "main.log").write_text("Compilation finished.\n", encoding="utf-8")
            if not draftmode:
                (target_dir / "main.pdf").write_bytes(b"%PDF-1.4\n%mock\n")

            class _Result:
                returncode = 0

            return _Result()

        with patch("mtex_executor._run_pdflatex", side_effect=_fake_pdflatex):
            generated_pdf = ejecutar_mtex(str(self.source_path), env_ast, abrir_pdf=False, build_dir=self.build_dir)

        self.assertEqual(Path(generated_pdf), self.build_dir / "main.pdf")
        self.assertTrue((self.build_dir / "main.tex").exists())
        self.assertTrue((self.build_dir / "main.pdf").exists())
        self.assertTrue((self.build_dir / COMPILE_LOG_FILENAME).exists())
        self.assertFalse((self.project_root / "main.tex").exists())
        self.assertFalse((self.project_root / "main.pdf").exists())
        self.assertTrue(calls)
        self.assertEqual(Path(calls[0][1]), self.project_root)
        self.assertEqual(Path(calls[0][3]), self.build_dir.resolve())


if __name__ == "__main__":
    unittest.main()
