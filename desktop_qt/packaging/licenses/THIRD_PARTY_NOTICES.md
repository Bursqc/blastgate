# Third-party software in Blastgate (desktop)

Blastgate for Windows is distributed together with the following components.

| Component | License | Source |
|---|---|---|
| Qt 6 and PySide6 (Qt for Python) | LGPL-3.0-only | https://www.qt.io / https://pypi.org/project/PySide6/ |
| Python | PSF License | https://www.python.org |
| pydantic, pydantic-core | MIT | https://github.com/pydantic |
| Tabler Icons | MIT | https://github.com/tabler/tabler-icons |

Qt and PySide6 are used unmodified as dynamically loaded libraries (the files
under `_internal\PySide6`). You may replace them with your own builds of the
same version; the full text of the LGPL is in `LGPL-3.0-only.txt` in this folder.
