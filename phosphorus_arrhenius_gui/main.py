from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from phosphorus_sublimation_gui import PhosphorusTkApp

    app = PhosphorusTkApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
