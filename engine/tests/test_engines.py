"""Regression tests for the debugmaster analysis engines (stdlib unittest).

Run: python3 -m unittest discover -s tests -v   (from the debugmaster root)
No pytest dependency; ML-dependent assertions skip cleanly when libs are absent.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import (  # noqa: E402
    audit,
    bizcatalog,
    bizlogic,
    bughunt,
    common,
    doctor,
    fusion,
    gitrisk,
    hunt,
    learn,
    mcp_server,
    metrics,
    profile,
    reach,
    riskmodel,
    suppress,
    triage,
)


def _write(d: Path, name: str, body: str) -> Path:
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


class TestBughunt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_detects_core_python_bugs(self):
        _write(
            self.tmp,
            "a.py",
            "def f(x=[]):\n"
            "    try:\n        risky()\n    except:\n        pass\n"
            "    if x == None:\n        return\n"
            "    assert (x, 'msg')\n"
            "    api_key = 'sk_live_ABCDEF1234567890'\n",
        )
        ids = {f.rule_id for f in bughunt.scan_repo(self.tmp)}
        for rid in ("py-mutable-default", "py-assert-tuple", "secret-literal"):
            self.assertIn(rid, ids, f"missing {rid}")
        # bare-except detected by either the regex or AST rule
        self.assertTrue(
            {"py-bare-except", "py-bare-except-ast", "py-except-pass-ast"} & ids
        )

    def test_ast_blocking_in_async_and_dup_boolop(self):
        _write(
            self.tmp,
            "b.py",
            "import time\n"
            "async def g(u):\n"
            "    time.sleep(1)\n"
            "    if u.ok and u.ok:\n        pass\n"
            "    u.name.strip()\n",
        )
        ids = {f.rule_id for f in bughunt.scan_repo(self.tmp)}
        self.assertIn("py-blocking-in-async", ids)
        self.assertIn("py-dup-boolop", ids)
        self.assertIn("py-must-use-return", ids)

    def test_clean_file_has_no_false_positives(self):
        _write(
            self.tmp,
            "clean.py",
            "import os\n\n\n"
            "def add(a, b):\n    return a + b\n\n\n"
            "def first(items):\n    return items[0] if items else None\n",
        )
        findings = [
            f for f in bughunt.scan_repo(self.tmp) if f.severity in ("critical", "high")
        ]
        self.assertEqual(findings, [], f"unexpected: {[f.rule_id for f in findings]}")

    def test_syntax_error_is_flagged(self):
        _write(self.tmp, "broken.py", "def f(:\n    pass\n")
        ids = {f.rule_id for f in bughunt.scan_repo(self.tmp)}
        self.assertIn("py-syntax-error", ids)


class TestFalsePositiveGuards(unittest.TestCase):
    """Regressions for FPs found auditing real repos (v0.9.2)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_localhost_fallback_is_not_a_secret(self):
        # `unwrap_or_else(|_| "http://localhost:8080")` is a benign config default,
        # not a leaked credential — must NOT fire a critical secret-in-fallback.
        _write(
            self.tmp,
            "main.rs",
            'let url = std::env::var("APP_URL")'
            '.unwrap_or_else(|_| "http://localhost:8080".into());\n',
        )
        ids = {f.rule_id for f in bughunt.scan_repo(self.tmp)}
        self.assertNotIn("secret-in-fallback", ids)

    def test_real_credential_fallback_still_flagged(self):
        # An actual hardcoded password fallback must still be critical.
        _write(
            self.tmp,
            "creds.rs",
            'let pw = std::env::var("DB_PASSWORD")'
            '.unwrap_or_else(|_| "s3cr3t_password".into());\n',
        )
        hits = [
            f for f in bughunt.scan_repo(self.tmp) if f.rule_id == "secret-in-fallback"
        ]
        self.assertTrue(hits, "real credential fallback must still flag")
        self.assertEqual(hits[0].severity, "critical")

    def test_levenshtein_dp_off_by_one_is_low_not_blocking(self):
        # Edit-distance DP over a `len+1` matrix uses `<= length` correctly. The
        # heuristic may still hint, but never at a grade/BLOCK-driving severity.
        _write(
            self.tmp,
            "dist.js",
            "function lev(a, b) {\n"
            "  const m = Array.from({length: a.length + 1}, () => Array(b.length + 1).fill(0));\n"
            "  for (let i = 0; i <= a.length; i++) m[i][0] = i;\n"
            "  return m;\n"
            "}\n",
        )
        offs = [f for f in bughunt.scan_repo(self.tmp) if f.rule_id == "off-by-one-len"]
        self.assertTrue(
            all(f.severity == "low" for f in offs),
            f"off-by-one must be low severity, got {[f.severity for f in offs]}",
        )


class TestMetrics(unittest.TestCase):
    def test_python_cyclomatic_and_proxy(self):
        tmp = Path(tempfile.mkdtemp())
        p = _write(
            tmp,
            "m.py",
            "def f(x):\n"
            + "".join(f"    if x=={i}:\n        return {i}\n" for i in range(10)),
        )
        m = metrics.file_metrics(p, "python")
        self.assertGreaterEqual(m["complexity"], 10)
        self.assertGreater(metrics.risk_proxy(m), 0)


class TestRiskModel(unittest.TestCase):
    def test_score_ranks_risky_above_clean(self):
        sig = {
            "risky.py": {
                "history": 90,
                "structure": 70,
                "finding_weight": 12,
                "dirty": True,
                "fan_in": 20,
            },
            "calm.py": {
                "history": 5,
                "structure": 10,
                "finding_weight": 0,
                "dirty": False,
                "fan_in": 0,
            },
        }
        scored = riskmodel.score_files(sig)
        self.assertGreater(scored["risky.py"]["score"], scored["calm.py"]["score"])

    def test_isolation_forest_or_heuristic(self):
        # 14 files so IsolationForest activates when sklearn present; else heuristic.
        sig = {
            f"f{i}.py": {
                "history": i,
                "structure": i,
                "finding_weight": 0,
                "dirty": False,
                "fan_in": 0,
            }
            for i in range(14)
        }
        sig["outlier.py"] = {
            "history": 100,
            "structure": 100,
            "finding_weight": 50,
            "dirty": True,
            "fan_in": 99,
        }
        scored = riskmodel.score_files(sig)
        top = max(scored.items(), key=lambda kv: kv[1]["score"])
        self.assertEqual(top[0], "outlier.py")


class TestLearnLoop(unittest.TestCase):
    def test_feedback_moves_precision(self):
        tmp = Path(tempfile.mkdtemp())
        base = learn.precision(tmp, "rust-unwrap")
        learn.feedback(tmp, "x.rs", 3, "rust-unwrap", real=False)
        after = learn.precision(tmp, "rust-unwrap")
        self.assertLess(after, base, "dismissing should lower precision")
        learn.feedback(tmp, "y.rs", 9, "rust-unwrap", real=True)
        self.assertGreater(learn.precision(tmp, "rust-unwrap"), after)

    def test_priors_make_secret_high_precision(self):
        tmp = Path(tempfile.mkdtemp())
        self.assertGreater(learn.precision(tmp, "secret-literal"), 0.7)


class TestGitRiskCochange(unittest.TestCase):
    def test_missing_cochange(self):
        mined = {
            "files": {"a.py": {"commits": 10}, "b.py": {"commits": 8}},
            "coupling": {"a.py": {"b.py": 8}, "b.py": {"a.py": 8}},
        }
        suspects = gitrisk.missing_cochange(mined, ["a.py"])
        self.assertTrue(any(s["path"] == "b.py" for s in suspects))


class TestFusionDedupe(unittest.TestCase):
    def test_dedupe_keeps_highest_severity(self):
        F = bughunt.Finding
        items = [
            F("x.py", 5, "ruff:E1", "low", "t", "", "", ""),
            F("x.py", 5, "bandit:B1", "high", "t", "", "", ""),
        ]
        out = fusion.dedupe(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity, "high")


class TestFusionJsonExtraction(unittest.TestCase):
    """The biome/golangci adapters must dig their JSON object out of output that
    also carries human-readable notice/summary lines."""

    def test_biome_json_past_unstable_notice(self):
        raw = (
            "The --json option is unstable/experimental.\n"
            '{"summary":{},"diagnostics":[{"severity":"error",'
            '"message":"debugger","category":"lint/suspicious/noDebugger",'
            '"location":{"path":"a.js","start":{"line":4}}}]}\n'
        )
        data = fusion._first_json_line(raw, '"diagnostics"')
        self.assertIsNotNone(data)
        self.assertEqual(data["diagnostics"][0]["location"]["start"]["line"], 4)

    def test_golangci_json_before_summary_tail(self):
        raw = (
            '{"Issues":[{"FromLinter":"typecheck","Text":"declared and not used: x",'
            '"Pos":{"Filename":"main.go","Line":4}}],"Report":{}}\n'
            "1 issues:\n* typecheck: 1\n"
        )
        data = fusion._first_json_line(raw, '"Issues"')
        self.assertIsNotNone(data)
        self.assertEqual(data["Issues"][0]["Pos"]["Line"], 4)

    def test_non_json_returns_none(self):
        raw = "This oxlint wrapper is for IDE extension use only (--lsp mode).\n"
        self.assertIsNone(fusion._first_json_line(raw, '"diagnostics"'))


class TestReach(unittest.TestCase):
    def test_import_fan_in(self):
        tmp = Path(tempfile.mkdtemp())
        _write(tmp, "core.py", "X = 1\n")
        _write(tmp, "u1.py", "from core import X\n")
        _write(tmp, "u2.py", "import core\n")
        fi = reach.import_fan_in(tmp, ["core.py", "u1.py"])
        self.assertGreaterEqual(fi["core.py"], 2)

    def test_test_gap(self):
        tmp = Path(tempfile.mkdtemp())
        _write(tmp, "payments.py", "def charge():\n    return 1\n")
        gaps = reach.test_gaps(tmp, ["payments.py"])
        self.assertTrue(any(g.rule_id == "test-gap" for g in gaps))


class TestBizlogic(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_idor_flagged_but_guarded_handler_is_not(self):
        _write(
            self.tmp,
            "api.py",
            "@app.route('/o/<oid>')\n"
            "def get_order(oid):\n    return Order.objects.get(id=oid)\n\n"
            "@app.route('/p/<uid>')\n"
            "def prof(uid, current_user):\n"
            "    o = User.objects.get(id=uid)\n"
            "    if o.owner != current_user.id:\n        abort(403)\n    return o\n",
        )
        ids = [(f.rule_id, f.line) for f in bizlogic.scan_repo(self.tmp)]
        idor = [ln for rid, ln in ids if rid == "biz-idor-missing-ownership"]
        self.assertIn(2, idor, "unguarded handler should be flagged")
        self.assertNotIn(6, idor, "handler with ownership check must NOT be flagged")

    def test_float_money(self):
        _write(
            self.tmp,
            "pay.py",
            "def t(items):\n    total = 0.0\n    for i in items:\n"
            "        total += float(i.price)\n    return total / len(items)\n",
        )
        ids = {f.rule_id for f in bizlogic.scan_repo(self.tmp)}
        self.assertIn("biz-float-money", ids)

    def test_clean_business_code_no_false_positive(self):
        _write(
            self.tmp,
            "calc.py",
            "from decimal import Decimal\n\n"
            "def add(a, b):\n    return Decimal(a) + Decimal(b)\n\n"
            "def greet(name):\n    return 'hi ' + name\n",
        )
        hi = [
            f
            for f in bizlogic.scan_repo(self.tmp)
            if f.severity in ("high", "critical")
        ]
        self.assertEqual(hi, [], f"unexpected: {[f.rule_id for f in hi]}")

    def test_oversell_race_flagged_but_locked_is_not(self):
        _write(
            self.tmp,
            "buy.py",
            "def buy(product, qty):\n"
            "    if product.stock >= qty:\n"
            "        product.stock = product.stock - qty\n        product.save()\n",
        )
        self.assertIn(
            "biz-oversell-race", {f.rule_id for f in bizlogic.scan_repo(self.tmp)}
        )
        tmp2 = Path(tempfile.mkdtemp())
        _write(
            tmp2,
            "buy.py",
            "def buy(product, qty):\n    with product.lock():\n"
            "        if product.stock >= qty:\n            product.stock -= qty\n",
        )
        self.assertNotIn(
            "biz-oversell-race", {f.rule_id for f in bizlogic.scan_repo(tmp2)}
        )

    def test_idempotency_needs_real_side_effect(self):
        _write(
            self.tmp,
            "pay.py",
            "def charge_card(request, amount):\n    return stripe.charge(amount)\n",
        )
        self.assertIn(
            "biz-idempotency-missing", {f.rule_id for f in bizlogic.scan_repo(self.tmp)}
        )
        tmp2 = Path(tempfile.mkdtemp())
        _write(
            tmp2, "calc.py", "def calculate_refund(amount):\n    return amount * 0.9\n"
        )
        self.assertNotIn(
            "biz-idempotency-missing", {f.rule_id for f in bizlogic.scan_repo(tmp2)}
        )


class TestFlows(unittest.TestCase):
    def test_explain_localizes_traceback(self):
        from lib import flows

        tmp = Path(tempfile.mkdtemp())
        _write(tmp, "svc.py", "def run():\n    return 1 / 0\n")
        trace = f'Traceback:\n  File "{tmp}/svc.py", line 2, in run\n    return 1 / 0\nZeroDivisionError: division by zero\n'
        res = flows.explain(tmp, trace)
        self.assertTrue(res["deepest_repo_frame"])
        self.assertEqual(res["deepest_repo_frame"]["file"], "svc.py")
        self.assertIn("ZeroDivisionError", res["error"])

    def test_bisect_finds_bad_commit(self):
        import subprocess

        from lib import flows

        tmp = Path(tempfile.mkdtemp())

        def git(*a):
            subprocess.run(
                ["git", "-C", str(tmp), *a], capture_output=True, check=False
            )

        git("init")
        git("config", "user.email", "t@t.de")
        git("config", "user.name", "t")
        _write(tmp, "v.txt", "ok\n")
        git("add", "-A")
        git("commit", "-m", "good")
        good = subprocess.run(
            ["git", "-C", str(tmp), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        _write(tmp, "v.txt", "bad\n")
        git("add", "-A")
        git("commit", "-m", "bug")
        bad = subprocess.run(
            ["git", "-C", str(tmp), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        res = flows.bisect(tmp, good, bad, "grep -q ok v.txt")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertIn(bad[:7], res["first_bad_commit"])


class TestDoctor(unittest.TestCase):
    def test_audit_always_reports_static_engine(self):
        a = doctor.audit()
        self.assertTrue(a["layers"]["static_engine"])
        self.assertIn("depth", a)


class TestBizlogicV3(unittest.TestCase):
    """mass-assignment + auth-no-ratelimit: high-value bugs, FP-controlled."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _ids(self, name, body):
        _write(self.tmp, name, body)
        return {f.rule_id for f in bizlogic.scan_repo(self.tmp)}

    def test_mass_assignment_python(self):
        ids = self._ids(
            "u.py",
            "def upd(request):\n    return User.objects.update(**request.json)\n",
        )
        self.assertIn("biz-mass-assignment", ids)

    def test_mass_assignment_not_on_explicit_fields(self):
        ids = self._ids(
            "u.py",
            "def upd(request):\n    return User.objects.update(name=request.json['name'])\n",
        )
        self.assertNotIn("biz-mass-assignment", ids)

    def test_mass_assignment_js_but_not_picked(self):
        bad = self._ids("a.js", "app.post('/u',(req,res)=>{User.create(req.body)})\n")
        self.assertIn("biz-mass-assignment", bad)
        tmp2 = Path(tempfile.mkdtemp())
        _write(
            tmp2,
            "b.js",
            "app.post('/u',(req,res)=>{User.create(pick(req.body,['x']))})\n",
        )
        self.assertNotIn(
            "biz-mass-assignment", {f.rule_id for f in bizlogic.scan_repo(tmp2)}
        )

    def test_auth_no_ratelimit_flagged_but_throttled_is_not(self):
        bad = self._ids(
            "l.py",
            "def login(request, user, password):\n"
            "    if user.check_password(password):\n        return ok()\n",
        )
        self.assertIn("biz-auth-no-ratelimit", bad)
        tmp2 = Path(tempfile.mkdtemp())
        _write(
            tmp2,
            "l.py",
            "@limiter.limit('5/min')\n"
            "def login(request, user, password):\n"
            "    if user.check_password(password):\n        return ok()\n",
        )
        self.assertNotIn(
            "biz-auth-no-ratelimit", {f.rule_id for f in bizlogic.scan_repo(tmp2)}
        )

    def test_auth_ratelimit_not_on_non_auth_function(self):
        ids = self._ids(
            "c.py", "def score(password_strength):\n    return password_strength == 5\n"
        )
        self.assertNotIn("biz-auth-no-ratelimit", ids)


class TestSuppress(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _finding(self, file, line, rule_id):
        return bughunt.Finding(file, line, rule_id, "high", "t", "", "m", "f")

    def test_rule_glob_and_inline_markers(self):
        _write(self.tmp, "x.py", "a = 1\nb = 2  # debugmaster: ignore[py-eq-none]\n")
        _write(
            self.tmp, ".debugmaster-ignore", "py-shell-true\nlegacy/**:py-bare-except\n"
        )
        findings = [
            self._finding("a.py", 1, "py-shell-true"),  # rule muted everywhere
            self._finding("legacy/old.py", 3, "py-bare-except"),  # path-glob muted
            self._finding("legacy/old.py", 3, "py-eq-none"),  # different rule -> kept
            self._finding("x.py", 2, "py-eq-none"),  # inline marker -> muted
            self._finding("x.py", 1, "py-eq-none"),  # no marker -> kept
        ]
        kept, n = suppress.filter_findings(self.tmp, findings)
        kept_ids = {(f.file, f.line) for f in kept}
        self.assertEqual(n, 3)
        self.assertIn(
            ("legacy/old.py", 3), kept_ids
        )  # py-eq-none survives the bare-except glob
        self.assertIn(("x.py", 1), kept_ids)
        self.assertEqual(len(kept), 2)

    def test_no_ignore_file_keeps_everything(self):
        findings = [self._finding("a.py", 1, "py-shell-true")]
        kept, n = suppress.filter_findings(self.tmp, findings)
        self.assertEqual((len(kept), n), (1, 0))


class TestSuperAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_grade_dimensions_and_readiness(self):
        # a real high-severity bug -> security/reliability hit, readiness != SHIP
        _write(
            self.tmp,
            "app.py",
            "import subprocess\ndef run(cmd):\n    subprocess.run(cmd, shell=True)\n",
        )
        a = audit.audit(self.tmp, fuse=False)
        self.assertIn(a["grade"], list("ABCDF"))
        self.assertIn("security", a["dimensions"])
        self.assertIn(a["release_readiness"], ("SHIP", "FIX-FIRST", "BLOCK"))
        self.assertIn("suppressed", a["coverage"])
        # markdown renders without error
        self.assertIn("Super-Audit", audit.markdown(a))

    def test_clean_repo_ships_with_A(self):
        _write(self.tmp, "ok.py", "def add(a, b):\n    return a + b\n")
        a = audit.audit(self.tmp, fuse=False)
        self.assertEqual(a["release_readiness"], "SHIP")
        self.assertEqual(a["grade"], "A")

    def test_trend_after_baseline(self):
        _write(self.tmp, "ok.py", "def add(a, b):\n    return a + b\n")
        first = audit.audit(self.tmp, fuse=False, save_baseline=True)
        self.assertTrue(first.get("baseline_saved"))
        second = audit.audit(self.tmp, fuse=False)
        self.assertIsNotNone(second["trend"])
        self.assertEqual(second["trend"]["regressions"], 0)


class TestBizlogicSecurity(unittest.TestCase):
    """SSRF + open-redirect: outbound/redirect to a user-controlled URL."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _ids(self, name, body):
        _write(self.tmp, name, body)
        return {f.rule_id for f in bizlogic.scan_repo(self.tmp)}

    def test_ssrf_user_url_but_not_allowlisted_or_static(self):
        self.assertIn(
            "biz-ssrf-user-url",
            self._ids(
                "a.py",
                "def f(request):\n    return requests.get(request.args['url'])\n",
            ),
        )
        t2 = Path(tempfile.mkdtemp())
        _write(
            t2, "b.py", "def f():\n    return requests.get('https://api.example.com')\n"
        )
        self.assertNotIn(
            "biz-ssrf-user-url", {f.rule_id for f in bizlogic.scan_repo(t2)}
        )
        t3 = Path(tempfile.mkdtemp())
        _write(
            t3,
            "c.py",
            "def f(request):\n    u = request.args['url']\n"
            "    if urlparse(u).netloc in ALLOWED:\n        return requests.get(u)\n",
        )
        self.assertNotIn(
            "biz-ssrf-user-url", {f.rule_id for f in bizlogic.scan_repo(t3)}
        )

    def test_open_redirect_but_not_view_name(self):
        self.assertIn(
            "biz-open-redirect",
            self._ids(
                "d.py",
                "def f(request):\n    return redirect(request.args.get('next'))\n",
            ),
        )
        t2 = Path(tempfile.mkdtemp())
        _write(t2, "e.py", "def f(request):\n    return redirect('home')\n")
        self.assertNotIn(
            "biz-open-redirect", {f.rule_id for f in bizlogic.scan_repo(t2)}
        )

    def test_ssrf_and_redirect_js(self):
        self.assertIn(
            "biz-ssrf-user-url",
            self._ids("f.js", "app.get('/x',(req,res)=>{ fetch(req.query.url) })\n"),
        )
        self.assertIn(
            "biz-open-redirect",
            self._ids(
                "g.js", "app.get('/y',(req,res)=>{ res.redirect(req.query.next) })\n"
            ),
        )


class TestCombinedStaticScan(unittest.TestCase):
    """The single-pass combined scan must equal running both engines separately."""

    def test_combined_equals_separate(self):
        tmp = Path(tempfile.mkdtemp())
        _write(
            tmp,
            "a.py",
            "import subprocess\n"
            "def login(request, pw):\n"
            "    if check_password(pw):\n        return True\n"
            "def run(c):\n    subprocess.run(c, shell=True)\n",
        )
        _write(tmp, "b.js", "app.post('/u',(req,res)=>{User.create(req.body)})\n")
        sep = bughunt.scan_repo(tmp) + bizlogic.scan_repo(tmp)
        comb = hunt._combined_static(tmp, None, 6000)
        key = lambda f: (f.file, f.line, f.rule_id)  # noqa: E731
        self.assertEqual(sorted(map(key, sep)), sorted(map(key, comb)))
        self.assertTrue(comb, "expected findings in the fixture")


class TestParallelism(unittest.TestCase):
    def test_worker_count_default_is_a_fraction_of_cores(self):
        import os as _os

        n = _os.cpu_count() or 1
        w = common.worker_count()
        self.assertGreaterEqual(w, 1)
        self.assertLessEqual(w, n)
        if n >= 4:
            self.assertLess(w, n, "default must leave cores free (not pin the box)")

    def test_worker_count_env_overrides(self):
        import os as _os

        old = _os.environ.get("DEBUGMASTER_WORKERS")
        try:
            _os.environ["DEBUGMASTER_WORKERS"] = "3"
            self.assertEqual(common.worker_count(), min(3, _os.cpu_count() or 1))
        finally:
            if old is None:
                _os.environ.pop("DEBUGMASTER_WORKERS", None)
            else:
                _os.environ["DEBUGMASTER_WORKERS"] = old

    def test_thread_cap_env_sets_known_vars(self):
        env = common.thread_cap_env(2)
        self.assertEqual(env["RAYON_NUM_THREADS"], "2")
        self.assertIn("OMP_NUM_THREADS", env)

    def test_parallel_scan_matches_serial(self):
        tmp = Path(tempfile.mkdtemp())
        for i in range(12):
            _write(
                tmp,
                f"m{i}.py",
                f"def f{i}(request):\n    return User.objects.update(**request.json)\n",
            )
        files = [
            (common.rel(tmp, p), lang) for p, lang in common.iter_source_files(tmp)
        ]
        serial = []
        for relp, lang in files:
            serial += hunt._scan_one(tmp, relp, lang)
        parallel = hunt._scan_parallel(tmp, files, 4)
        key = lambda f: (f.file, f.line, f.rule_id)  # noqa: E731
        self.assertEqual(sorted(map(key, serial)), sorted(map(key, parallel)))
        self.assertTrue(parallel)


class TestBizlogicBilling(unittest.TestCase):
    """webhook-no-signature + client-controlled-price (revenue failure surfaces)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _ids(self, name, body, *, fresh=False):
        d = Path(tempfile.mkdtemp()) if fresh else self.tmp
        _write(d, name, body)
        return {f.rule_id for f in bizlogic.scan_repo(d)}

    def test_webhook_without_signature_flagged(self):
        ids = self._ids(
            "wh.py",
            "@app.route('/webhook', methods=['POST'])\n"
            "def stripe_webhook(request):\n    event = request.json\n    return handle(event)\n",
        )
        self.assertIn("biz-webhook-no-signature", ids)

    def test_webhook_with_signature_not_flagged(self):
        ids = self._ids(
            "wh.py",
            "@app.route('/webhook', methods=['POST'])\n"
            "def stripe_webhook(request):\n"
            "    event = stripe.Webhook.construct_event(request.data, sig, secret)\n"
            "    return handle(event)\n",
            fresh=True,
        )
        self.assertNotIn("biz-webhook-no-signature", ids)

    def test_client_controlled_price_flagged_but_server_lookup_is_not(self):
        bad = self._ids(
            "p.py",
            "def pay(request):\n    return stripe.charge(amount=request.json['amount'])\n",
        )
        self.assertIn("biz-client-controlled-price", bad)
        good = self._ids(
            "q.py",
            "def pay(request, oid):\n    o = Order.objects.get(id=oid)\n"
            "    return stripe.charge(amount=o.total)\n",
            fresh=True,
        )
        self.assertNotIn("biz-client-controlled-price", good)


class TestReliabilityAndRefund(unittest.TestCase):
    def _ids(self, mod, name, body):
        d = Path(tempfile.mkdtemp())
        _write(d, name, body)
        return {f.rule_id for f in mod.scan_repo(d)}

    def test_request_without_timeout_flagged(self):
        self.assertIn(
            "py-request-no-timeout",
            self._ids(
                bughunt,
                "n.py",
                "import requests\ndef f(u):\n    return requests.get(u)\n",
            ),
        )

    def test_request_with_timeout_not_flagged(self):
        self.assertNotIn(
            "py-request-no-timeout",
            self._ids(
                bughunt,
                "n.py",
                "import requests\ndef f(u):\n    return requests.get(u, timeout=5)\n",
            ),
        )

    def test_refund_client_amount_flagged_but_server_not(self):
        self.assertIn(
            "biz-refund-client-amount",
            self._ids(
                bizlogic,
                "r.py",
                "def r(request):\n    return stripe.Refund.create(amount=request.json['amount'])\n",
            ),
        )
        d = Path(tempfile.mkdtemp())
        _write(
            d,
            "s.py",
            "def r(request, pid):\n    p = Payment.objects.get(id=pid)\n    return stripe.Refund.create(amount=p.captured)\n",
        )
        self.assertNotIn(
            "biz-refund-client-amount", {f.rule_id for f in bizlogic.scan_repo(d)}
        )


class TestBizCatalog(unittest.TestCase):
    def test_two_hundred_entries_split_evenly(self):
        s = bizcatalog.stats()
        self.assertEqual(s["total"], 200)
        self.assertEqual((s["product"], s["primitive"]), (100, 100))
        self.assertGreaterEqual(s["auto_detected"], 5)

    def test_every_detected_entry_maps_to_a_real_rule(self):
        # detector must be a real, registered rule id (bughunt RULES, bizlogic regex,
        # or a biz- AST detector). No dangling mappings.
        real = {r.id for r in bughunt.RULES} | {r[0] for r in bizlogic.REGEX_RULES}
        for r in bizcatalog.entries():
            det = r["detector"]
            if det:
                self.assertTrue(
                    det in real or det.startswith("biz-"),
                    f"{r['name']} -> {det} is not a registered rule",
                )

    def test_query_filters_by_domain_and_kind(self):
        pay = bizcatalog.query(domain="payments")
        self.assertTrue(pay and all(r["domain"] == "payments" for r in pay))
        prims = bizcatalog.query(kind="primitive")
        self.assertTrue(all(r["kind"] == "primitive" for r in prims))

    def test_undetected_entries_have_a_runnable_search(self):
        for r in bizcatalog.entries():
            if not r["detector"]:
                self.assertIn("ghgrep", r["search"])


class TestWatchAndRegress(unittest.TestCase):
    def setUp(self):
        from lib import flows

        self.flows = flows
        self.tmp = Path(tempfile.mkdtemp())
        _write(
            self.tmp,
            "app.py",
            "import subprocess\ndef run(c):\n    subprocess.run(c, shell=True)\n",
        )

    def test_fingerprint_and_scan_files(self):
        fp = self.flows.source_fingerprint(self.tmp)
        self.assertIn("app.py", fp)
        ids = {f.rule_id for f in self.flows.scan_files(self.tmp, ["app.py"])}
        self.assertIn("py-shell-true", ids)

    def test_regress_writes_compiling_test_and_is_idempotent(self):
        import py_compile

        res = self.flows.regress(self.tmp, "app.py", "py-shell-true")
        self.assertTrue(res["ok"])
        gen = Path(res["path"])
        self.assertTrue(gen.exists())
        py_compile.compile(str(gen), doraise=True)  # generated test must parse
        again = self.flows.regress(self.tmp, "app.py", "py-shell-true")
        self.assertEqual(again.get("note"), "already present")

    def test_regress_no_match_is_reported(self):
        res = self.flows.regress(self.tmp, "app.py", "py-mutable-default")
        self.assertFalse(res["ok"])


class TestReviewComment(unittest.TestCase):
    def _res(self, decision):
        return {
            "decision": decision,
            "base": "main",
            "changed_files": 1,
            "verdict": "FAIL",
            "findings_on_change": [
                {
                    "severity": "high",
                    "file": "a.py",
                    "line": 5,
                    "rule_id": "biz-idor-missing-ownership",
                    "message": "loads by id w/o owner check",
                    "fix": "scope by user",
                }
            ],
            "forgotten_edit_suspects": [
                {"path": "t.py", "partner": "a.py", "confidence": 0.7}
            ],
        }

    def test_comment_markdown_has_verdict_and_finding(self):
        from lib import flows

        md = flows.review_comment_markdown(self._res("REQUEST-CHANGES"))
        self.assertIn("REQUEST-CHANGES", md)
        self.assertIn("a.py:5", md)
        self.assertIn("Forgotten-edit", md)

    def test_post_returns_dict_never_raises(self):
        from lib import flows

        out = flows.post_pr_comment(Path(tempfile.mkdtemp()), "body")
        self.assertIn("posted", out)
        self.assertIsInstance(out["posted"], bool)


class TestTriage(unittest.TestCase):
    def test_parse_real_fake_garbage(self):
        r = triage._parse("REAL 0.9 token expiry uses < not <=")
        self.assertTrue(r["real"])
        self.assertEqual(r["confidence"], 0.9)
        f = triage._parse("FAKE 0.3 intentional best-effort swallow")
        self.assertFalse(f["real"])
        self.assertIsNone(triage._parse("I am not sure about this"))
        self.assertIsNone(triage._parse(""))

    def test_available_returns_tuple(self):
        up, model = triage.available()
        self.assertIsInstance(up, bool)
        self.assertTrue(model is None or isinstance(model, str))

    def test_triage_noop_when_unavailable(self):
        # point at a dead host so it cannot reach a daemon -> graceful no-op
        old = triage.OLLAMA
        try:
            triage.OLLAMA = "http://127.0.0.1:1"
            out = triage.triage(
                Path("."),
                [
                    {
                        "file": "x.py",
                        "line": 1,
                        "rule_id": "r",
                        "severity": "high",
                        "message": "m",
                    }
                ],
            )
            self.assertFalse(out["ok"])
        finally:
            triage.OLLAMA = old


class TestProfile(unittest.TestCase):
    """Runtime diagnostician — verdicts driven through analyze() (deterministic)."""

    def _samples(self, rss_list, *, cpu=10, threads=2, fds=5):
        return [
            {
                "t": i * 0.5,
                "rss": r,
                "cpu": cpu,
                "max_proc_cpu": cpu,
                "threads": threads,
                "fds": fds,
                "nproc": 1,
                "zombies": 0,
            }
            for i, r in enumerate(rss_list)
        ]

    def _types(self, r):
        return [f["type"] for f in r["findings"]]

    def test_memory_leak_from_rising_rss(self):
        rss = [(50 + 8 * i) * 1e6 for i in range(20)]  # +8MB/sample, still climbing
        r = profile.analyze(self._samples(rss), [], 0, wall=10)
        self.assertEqual(r["verdict"], "PROBLEM")
        self.assertIn("memory-leak", self._types(r))

    def test_flat_rss_is_clean(self):
        rss = [100e6 + (i % 2) * 1e5 for i in range(20)]  # noisy-flat, no trend
        r = profile.analyze(self._samples(rss), [], 0, wall=10)
        self.assertNotIn("memory-leak", self._types(r))

    def test_single_core_bottleneck(self):
        r = profile.analyze(self._samples([100e6] * 12, cpu=98), [], 0, wall=10)
        self.assertIn("cpu-single-core-bottleneck", self._types(r))

    def test_fd_leak_detected(self):
        s = self._samples([100e6] * 20)
        for i, smp in enumerate(s):
            smp["fds"] = 5 + 4 * i  # descriptors climbing
        r = profile.analyze(s, [], 0, wall=10)
        self.assertIn("fd-leak", self._types(r))

    def test_orphans_make_it_a_problem(self):
        r = profile.analyze(
            self._samples([100e6] * 8),
            [{"pid": 999, "name": "sleep", "cmdline": "sleep 99"}],
            0,
            wall=5,
        )
        self.assertEqual(r["verdict"], "PROBLEM")
        self.assertIn("orphan-processes", self._types(r))

    def test_markdown_renders(self):
        r = profile.analyze(self._samples([100e6] * 6), [], 0, wall=3)
        self.assertIn("Debugmaster Profile", profile.markdown(r))

    @unittest.skipIf(profile.psutil is None, "psutil required for live profiling")
    def test_live_leak_integration(self):
        import sys as _sys
        import tempfile as _tf

        d = Path(_tf.mkdtemp())
        (d / "lk.py").write_text(
            "import time\nb=[]\n"
            "for i in range(24):\n    b.append(bytearray(4_000_000)); time.sleep(0.08)\n"
        )
        r = profile.profile_command([_sys.executable, str(d / "lk.py")], interval=0.2)
        self.assertEqual(r["verdict"], "PROBLEM")
        self.assertIn("memory-leak", self._types(r))


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _write(self.tmp, "ok.py", "def add(a, b):\n    return a + b\n")

    def test_initialize_echoes_protocol_and_serverinfo(self):
        r = mcp_server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["serverInfo"]["name"], "debugmaster")

    def test_notification_gets_no_reply(self):
        self.assertIsNone(
            mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def test_tools_list(self):
        r = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in r["result"]["tools"]}
        self.assertIn("debugmaster_hunt", names)
        self.assertIn("debugmaster_profile", names)
        self.assertEqual(len(names), 5)

    def test_tools_call_audit_returns_content(self):
        r = mcp_server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "debugmaster_audit",
                    "arguments": {"repo": str(self.tmp), "fuse": False},
                },
            }
        )
        self.assertFalse(r["result"]["isError"])
        self.assertIn("Audit", r["result"]["content"][0]["text"])

    def test_unknown_tool_is_in_band_error(self):
        r = mcp_server.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            }
        )
        self.assertTrue(r["result"]["isError"])

    def test_unknown_method_jsonrpc_error(self):
        r = mcp_server.handle({"jsonrpc": "2.0", "id": 5, "method": "frobnicate"})
        self.assertEqual(r["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main(verbosity=2)
