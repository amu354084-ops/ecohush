from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRITICAL_CHECKS = {
    "development auth fallback": (ROOT / "app/services/auth.py", "erp-local-development-secret"),
    "wildcard credentialed CORS": (ROOT / "app/main.py", 'allow_origins=["*"]'),
    "default admin password": (ROOT / "app/services/seed.py", 'hash_password("admin")'),
}


def main() -> int:
    failures = []
    for name, (path, forbidden) in CRITICAL_CHECKS.items():
        if forbidden in path.read_text(encoding="utf-8"):
            failures.append(f"{name}: {path.relative_to(ROOT)}")

    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    if not re.search(r'Source:\s*"dist\\erp_offline\.exe"', installer):
        failures.append("installer executable path is missing or incorrect")
    if not (ROOT / "dist/erp_offline.exe").exists():
        failures.append("dist/erp_offline.exe is missing")

    if failures:
        print("SECURITY CHECK FAILED")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print("SECURITY CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
