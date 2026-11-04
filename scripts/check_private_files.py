"""Reject private filenames in the index, including files added with git add -f.

This is a filename safeguard, not a scan of file contents. Only the three exact
sample paths are allowed as spreadsheets; keep their contents fictitious.
"""

import fnmatch
import json
import os
from pathlib import PurePosixPath
import subprocess
import sys


SAMPLES = {
    "src/assets/catalogue_modele.xlsx",
    "modele/catalogue_modele.xlsx",
    "modele/catalogue_modele.csv",
}
PRIVATE_DIRS = {
    "prive", "signature_android", "ne pas upload", "storage", "photos",
    "sauvegardes", "build", "releases", ".flet", ".claude",
}
PRIVATE_NAMES = (
    "*.xls", "*.xlsx", "*.xlsm", "*.csv", "*.ods",
    "*.jks", "*.keystore", "*.p12", "*.pfx", "*.pem", "*.key",
    "*.apk", "*.aab", "*.zip", "*mot_de_passe*",
    "commandes*.json", "catalogue_perso*.json", "regles_catalogue*.json",
    "catalogue_importe*", ".env", ".env.*", "credentials*.json",
    "claude.md", "claude.local.md", ".mcp.json",
)


def is_private(path):
    if path in SAMPLES:
        return False
    parts = PurePosixPath(path).parts
    return (
        any(part.casefold() in PRIVATE_DIRS for part in parts[:-1])
        or any(fnmatch.fnmatchcase(parts[-1].casefold(), pattern)
               for pattern in PRIVATE_NAMES)
    )


def main():
    # NUL separators preserve spaces, accents, tabs and newlines in filenames.
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        stdout=subprocess.PIPE, check=True,
    )
    blocked = [os.fsdecode(path) for path in result.stdout.split(b"\0")
               if path and is_private(os.fsdecode(path))]
    if not blocked:
        return 0
    print("COMMIT REFUSE : fichiers prives dans le commit :", file=sys.stderr)
    for path in blocked:
        # Escape control characters; never print any file contents.
        print("  - " + json.dumps(path, ensure_ascii=True), file=sys.stderr)
    print("Retirez ces fichiers de l'index avec git restore --staged -- <chemin>.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
