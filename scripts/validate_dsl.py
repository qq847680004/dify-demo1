#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

SKILL_SCRIPT = (
    Path.home() / ".cursor" / "skills" / "dify-workflow-dsl" / "scripts" / "validate_dsl.py"
)

if not SKILL_SCRIPT.is_file():
    sys.exit(f"未找到校验器: {SKILL_SCRIPT}")

raise SystemExit(
    subprocess.call(
        [sys.executable, str(SKILL_SCRIPT), *sys.argv[1:]],
        cwd=str(SKILL_SCRIPT.parent),
    )
)
