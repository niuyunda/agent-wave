#!/usr/bin/env bash
set -euo pipefail

mkdir -p src tests

if [[ ! -f src/calculator.py ]]; then
  cat > src/calculator.py <<'PY'
"""Simple calculator module for e2e validation."""


def add(a: float, b: float) -> float:
    return a + b


def sub(a: float, b: float) -> float:
    return a - b


def mul(a: float, b: float) -> float:
    return a * b


def div(a: float, b: float) -> float:
    return a / b
PY
fi

if [[ ! -f tests/test_calculator.py ]]; then
  cat > tests/test_calculator.py <<'PY'
from src.calculator import add, div, mul, sub


def test_basic_ops() -> None:
    assert add(1, 2) == 3
    assert sub(3, 2) == 1
    assert mul(2, 4) == 8
    assert div(8, 2) == 4
PY
fi

# Retry cycle: if feedback exists, apply the requested fix exactly once.
if [[ -f .agvv/feedback.txt ]] && ! grep -q "raise ZeroDivisionError" src/calculator.py; then
  python - <<'PY'
from pathlib import Path

calc = Path("src/calculator.py")
text = calc.read_text(encoding="utf-8")
text = text.replace(
    "def div(a: float, b: float) -> float:\n    return a / b\n",
    "def div(a: float, b: float) -> float:\n    if b == 0:\n        raise ZeroDivisionError('division by zero')\n    return a / b\n",
)
calc.write_text(text, encoding="utf-8")

tests = Path("tests/test_calculator.py")
t = tests.read_text(encoding="utf-8")
if "with pytest.raises(ZeroDivisionError)" not in t:
    t = "import pytest\n" + t + "\n\ndef test_divide_by_zero() -> None:\n    with pytest.raises(ZeroDivisionError):\n        div(1, 0)\n"
tests.write_text(t, encoding="utf-8")
PY
fi
