"""Learning loop — make every run smarter than the last (compounding).

A finding is only valuable if it is real. We persist findings + human/agent
feedback to SQLite and keep a Beta(α, β) posterior of each rule's *precision*
(P(real | rule fired)). Future runs re-rank findings by the learned precision and
can Thompson-sample to keep exploring new rules. Confirmed bugs raise a rule; lots
of dismissals sink it. The model has no cold-start cliff — unseen rules start at a
neutral prior and a curated per-rule prior list.

Storage: <repo>/.debugmaster/learn.db (per-repo), falling back to
~/.debugmaster/learn.db so cross-repo signal still accrues.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import time
from pathlib import Path

# Curated priors: rule_id -> (alpha, beta). High-precision rules start trusted.
PRIORS = {
    "secret-literal": (8, 1),
    "gitleaks": (9, 1),
    "py-mutable-default": (7, 1),
    "py-assert-tuple": (9, 1),
    "py-except-pass-ast": (7, 2),
    "py-bare-except-ast": (6, 2),
    "py-shell-true": (7, 1),
    "sql-concat": (6, 2),
    "c-assign-in-cond": (6, 2),
    "go-ignored-err": (4, 3),
    "rust-unwrap": (3, 4),
    "js-loose-eq": (3, 4),
    "off-by-one-len": (3, 4),
    "js-floating-async": (3, 3),
    "py-open-no-with": (3, 3),
    # business-logic detectors: FP-prone, start modest so they don't dominate
    "biz-idor-missing-ownership": (4, 3),
    "biz-float-money": (5, 2),
    "biz-money-equality": (3, 3),
    "biz-pagination-offset": (2, 4),
    "biz-unit-mismatch": (2, 5),
    "biz-idempotency-missing": (2, 4),
    "biz-tenant-allobjects": (2, 4),
    "biz-oversell-race": (4, 3),
}
DEFAULT_PRIOR = (2, 2)


def _db_path(repo: Path) -> Path:
    p = repo / ".debugmaster"
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p / "learn.db"
    except OSError:
        h = Path.home() / ".debugmaster"
        h.mkdir(parents=True, exist_ok=True)
        return h / "learn.db"


def _connect(repo: Path) -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(repo))
    con.execute("""CREATE TABLE IF NOT EXISTS findings(
        fid TEXT PRIMARY KEY, ts REAL, run TEXT, file TEXT, line INTEGER,
        rule_id TEXT, severity TEXT, title TEXT, verdict TEXT DEFAULT 'open')""")
    con.execute("""CREATE TABLE IF NOT EXISTS rule_stats(
        rule_id TEXT PRIMARY KEY, alpha REAL, beta REAL, last REAL)""")
    con.commit()
    return con


def finding_id(file: str, line: int, rule_id: str) -> str:
    return hashlib.sha1(f"{file}:{line}:{rule_id}".encode()).hexdigest()[:16]


def _prior(rule_id: str) -> tuple[float, float]:
    base = rule_id.split(":")[0]
    return PRIORS.get(rule_id) or PRIORS.get(base) or DEFAULT_PRIOR


def record(repo: Path, findings: list, run: str | None = None) -> int:
    """Persist findings as 'open'. Returns count of new findings."""
    con = _connect(repo)
    run = run or time.strftime("%Y%m%d-%H%M%S")
    n = 0
    for f in findings:
        d = f.as_dict() if hasattr(f, "as_dict") else f
        fid = finding_id(d["file"], d["line"], d["rule_id"])
        cur = con.execute(
            "INSERT OR IGNORE INTO findings(fid,ts,run,file,line,rule_id,severity,title) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                fid,
                time.time(),
                run,
                d["file"],
                d["line"],
                d["rule_id"],
                d.get("severity", "medium"),
                d.get("title", ""),
            ),
        )
        n += cur.rowcount
    con.commit()
    con.close()
    return n


def feedback(repo: Path, file: str, line: int, rule_id: str, real: bool) -> dict:
    """Confirm (real) or dismiss (not real) a finding; update the rule posterior."""
    con = _connect(repo)
    fid = finding_id(file, line, rule_id)
    con.execute(
        "UPDATE findings SET verdict=? WHERE fid=?",
        ("confirmed" if real else "dismissed", fid),
    )
    a, b = _prior(rule_id)
    row = con.execute(
        "SELECT alpha,beta FROM rule_stats WHERE rule_id=?", (rule_id,)
    ).fetchone()
    if row:
        a, b = row
    if real:
        a += 1
    else:
        b += 1
    con.execute(
        "INSERT OR REPLACE INTO rule_stats(rule_id,alpha,beta,last) VALUES(?,?,?,?)",
        (rule_id, a, b, time.time()),
    )
    con.commit()
    con.close()
    return {
        "rule_id": rule_id,
        "alpha": a,
        "beta": b,
        "precision": round(a / (a + b), 3),
    }


def feedback_bulk(repo: Path, rule_id: str, real: int = 0, fake: int = 0) -> dict:
    real, fake = max(0, int(real)), max(0, int(fake))  # never let posterior go invalid
    con = _connect(repo)
    a, b = _prior(rule_id)
    row = con.execute(
        "SELECT alpha,beta FROM rule_stats WHERE rule_id=?", (rule_id,)
    ).fetchone()
    if row:
        a, b = row
    a += real
    b += fake
    con.execute(
        "INSERT OR REPLACE INTO rule_stats(rule_id,alpha,beta,last) VALUES(?,?,?,?)",
        (rule_id, a, b, time.time()),
    )
    con.commit()
    con.close()
    return {"rule_id": rule_id, "precision": round(a / (a + b), 3)}


def precision(repo: Path, rule_id: str) -> float:
    """Posterior-mean precision for a rule (learned, or curated prior)."""
    con = _connect(repo)
    row = con.execute(
        "SELECT alpha,beta FROM rule_stats WHERE rule_id=?", (rule_id,)
    ).fetchone()
    con.close()
    if row:
        a, b = row
    else:
        a, b = _prior(rule_id)
    return a / (a + b)


def precision_map(repo: Path, rule_ids) -> dict[str, float]:
    con = _connect(repo)
    rows = con.execute("SELECT rule_id,alpha,beta FROM rule_stats").fetchall()
    con.close()
    stats = {r[0]: (r[1], r[2]) for r in rows}
    out = {}
    for rid in set(rule_ids):
        a, b = stats.get(rid) or _prior(rid)
        out[rid] = a / (a + b)
    return out


def thompson(repo: Path, rule_id: str, seed: int = 0) -> float:
    """Deterministic Thompson-style sample (no global RNG): Beta mean nudged by a
    seed-derived jitter so exploration order is reproducible across resumes."""
    a, b = _prior(rule_id)
    con = _connect(repo)
    row = con.execute(
        "SELECT alpha,beta FROM rule_stats WHERE rule_id=?", (rule_id,)
    ).fetchone()
    con.close()
    if row:
        a, b = row
    mean = a / (a + b)
    var = (a * b) / ((a + b) ** 2 * (a + b + 1))
    jitter = (math.sin(seed * 12.9898 + len(rule_id)) * 0.5) * math.sqrt(var)
    return max(0.0, min(1.0, mean + jitter))


def stats(repo: Path) -> dict:
    con = _connect(repo)
    total = con.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    by_verdict = dict(
        con.execute("SELECT verdict,COUNT(*) FROM findings GROUP BY verdict").fetchall()
    )
    rules = con.execute(
        "SELECT rule_id,alpha,beta FROM rule_stats ORDER BY alpha/(alpha+beta) DESC"
    ).fetchall()
    con.close()
    return {
        "db": str(_db_path(repo)),
        "findings": total,
        "by_verdict": by_verdict,
        "learned_rules": [
            {
                "rule": r[0],
                "precision": round(r[1] / (r[1] + r[2]), 3),
                "n": int(r[1] + r[2] - sum(_prior(r[0]))),
            }
            for r in rules
        ],
    }


if __name__ == "__main__":
    import json
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(stats(repo), indent=2))
