# Copyright © 2026 Alen Pepa.
"""Build the complete downloadable app without caches, credentials or nested ZIPs."""
from branding import validate_footer
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build():
    root = Path(__file__).resolve().parent.parent
    validate_footer((root / 'dist' / 'index.html').read_text(encoding='utf-8'))
    target = root / 'dist' / 'alen-stb-local.zip'
    files = [root / 'README.md', *root.glob('*.cmd'), *(root / 'dist').glob('*'),
             *(root / 'local').glob('*.py'), *(root / 'local').glob('*.cjs'), *(root / 'local' / 'i18n-tools').glob('*'),
             *(root / 'companion').rglob('*'), root / 'bin' / 'README.md']
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for file in files:
            if file.is_file() and file.suffix != '.zip' and '__pycache__' not in file.parts:
                archive.write(file, 'Alen-STB/' + file.relative_to(root).as_posix())
    return target


if __name__ == '__main__':
    print(build())
