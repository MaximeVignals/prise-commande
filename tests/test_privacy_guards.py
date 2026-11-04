"""Exercise the real hook with dummy files in an isolated Git repository."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.check_private_files import is_private


ROOT = Path(__file__).resolve().parents[1]


class PrivacyGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for name in (".gitignore", ".githooks/pre-commit", "scripts/check_private_files.py"):
            destination = self.repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        (self.repo / ".githooks/pre-commit").chmod(0o755)
        self.git("init", "-q")
        self.git("config", "core.hooksPath", ".githooks")

    def git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.repo, check=check,
                              capture_output=True, timeout=20)

    def stage(self, name):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("DUMMY TEST CONTENT ONLY", encoding="utf-8")
        self.git("add", "-f", "--", name)

    def test_private_files_are_ignored_and_force_added_files_are_blocked(self):
        for name in (
            "prive/notes.txt", "nested/prive/notes.txt", "regles_catalogue.json",
            "src/assets/regles_catalogue.backup.json", "catalogue_perso.json",
            "commandes-backup.json", "catalogue_importe.csv", ".env", ".env.local",
            "config/credentials.json", "credentials.production.json",
            "signature_android/upload.jks", "Ne Pas Upload/notes.txt",
            "key.pem", "key.key", "mot_de_passe.txt", "storage/data.txt",
            "photos/test.png", "sauvegardes/test.txt", "build/test.txt",
            "releases/test.txt", "backup.zip", "CLAUDE.local.md", ".mcp.json",
            "catalogue prive.xlsx",
        ):
            with self.subTest(path=name):
                self.git("read-tree", "--empty")
                self.assertEqual(self.git("check-ignore", "--no-index", "-q", "--", name,
                                          check=False).returncode, 0)
                self.stage(name)
                result = self.git("hook", "run", "pre-commit", check=False)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(b"COMMIT REFUSE", result.stderr)
                self.assertNotIn(b"DUMMY TEST CONTENT", result.stderr)

    def test_samples_and_source_are_allowed(self):
        for name in ("src/assets/catalogue_modele.xlsx", "modele/catalogue_modele.xlsx",
                     "modele/catalogue_modele.csv", "src/example.py", "README.md"):
            self.assertEqual(self.git("check-ignore", "--no-index", "-q", "--", name,
                                      check=False).returncode, 1)
            self.stage(name)
        self.assertEqual(self.git("hook", "run", "pre-commit").returncode, 0)

    def test_case_variants_and_unusual_names_cannot_bypass_the_guard(self):
        for name in ("PRIVE/notes.txt", "REGLES_CATALOGUE.JSON", "CONFIG/.ENV.LOCAL",
                     "CATALOGUE_PERSO.JSON", "nested/catalogue_modele.xlsx",
                     "modele/catalogue_modele.xlsx.zip", "odd\nname.xlsx",
                     'odd"name.csv', "path\tname.jks", "src/assets/CATALOGUE_MODELE.XLSX"):
            with self.subTest(path=name):
                self.assertTrue(is_private(name))
        self.stage("REGLES_CATALOGUE.JSON")
        self.assertEqual(self.git("hook", "run", "pre-commit", check=False).returncode, 1)

    def test_removing_a_previously_committed_private_file_is_allowed(self):
        self.stage("regles_catalogue.json")
        self.git("-c", "core.hooksPath=/dev/null", "-c", "user.name=Privacy Test",
                 "-c", "user.email=test@example.invalid", "-c", "commit.gpgSign=false",
                 "commit", "-qm", "Dummy fixture")
        self.git("rm", "regles_catalogue.json")
        self.assertEqual(self.git("hook", "run", "pre-commit").returncode, 0)


if __name__ == "__main__":
    unittest.main()
