"""Build and install Nebula.app into /Applications on macOS."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEST = Path('/Applications/Nebula.app')


def main() -> int:
    if sys.platform != 'darwin':
        print('Nebula.app installation is supported on macOS only.', file=sys.stderr)
        return 1
    pyinstaller = (shutil.which('pyinstaller') or shutil.which('pyinstaller3') or
                   str(ROOT / '.venv' / 'bin' / 'pyinstaller'))
    if not pyinstaller:
        print('PyInstaller is not installed. Run: python -m pip install pyinstaller', file=sys.stderr)
        return 1
    if not Path(pyinstaller).exists() and not shutil.which(pyinstaller):
        print('PyInstaller is not installed. Run: python -m pip install pyinstaller', file=sys.stderr)
        return 1
    subprocess.run([pyinstaller, '--noconfirm', 'Nebula.spec'], cwd=ROOT, check=True)
    built = ROOT / 'dist' / 'Nebula.app'
    if not built.exists():
        print('The build completed without producing dist/Nebula.app.', file=sys.stderr)
        return 1
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(built, DEST)
    print(f'Installed {DEST}')
    print('Press Command-Space, type Nebula, and press Return to launch it.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
