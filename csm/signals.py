"""Evaluate rules.toml against account metrics."""

import operator
import string
import tomllib
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent / "rules.toml"

OPS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
    "==": operator.eq, "!=": operator.ne,
}
SEVERITY_POINTS = {"low": 1, "medium": 3, "high": 6, "critical": 10}


def load_rules(path=RULES_PATH):
    with open(path, "rb") as f:
        return tomllib.load(f)["rule"]


class _Formatter(string.Formatter):
    """str.format that prints 'n/a' for missing values instead of failing."""

    def format_field(self, value, spec):
        if value is None:
            return "n/a"
        return super().format_field(value, spec)


_fmt = _Formatter()


def matches(rule, m):
    for metric, op, value in rule["when"]:
        actual = m.get(metric)
        if actual is None:
            return False
        if not OPS[op](actual, value):
            return False
    return True


def estimate_value(rule, m, prices):
    spec = rule.get("value")
    if not spec:
        return None
    if spec == "list":
        return int(round(prices[rule["module"]] * m["size_factor"], -2))
    if spec.startswith("arr:"):
        return int(round(m["arr_eur"] * float(spec.split(":")[1]), -2))
    raise ValueError(f"Unknown value spec {spec!r} in rule {rule['id']}")


def evaluate(m, rules, prices):
    """Return the signals that fire for one account's metrics (health included)."""
    fired = []
    for rule in rules:
        if not matches(rule, m):
            continue
        playbook = rule["playbook"]
        if m.get("channel") == "Partner" and m.get("partner"):
            playbook += f" Coordinate with partner {m['partner']}."
        fired.append({
            "account_id": m["account_id"],
            "rule_id": rule["id"],
            "kind": rule["kind"],
            "severity": rule["severity"],
            "title": rule["title"],
            "reason": _fmt.format(rule["reason"], **m),
            "playbook": playbook,
            "module_code": rule.get("module"),
            "est_value_eur": estimate_value(rule, m, prices),
        })
    return fired
