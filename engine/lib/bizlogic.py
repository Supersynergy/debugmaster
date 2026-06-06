"""Business-logic bug engine — the bugs that "look correct but are wrong".

Static analyzers, type checkers and security scanners are blind to *intent*: a
price stored as float, an endpoint that fetches a record by id without checking
who owns it, pagination that skips a row. These are the bugs that reach
production because every linter says the code is fine.

This engine uses domain-aware AST + regex heuristics. Business-logic detection is
inherently false-positive-prone, so every finding is framed as a SUSPECT with a
confidence and an explicit "verify with X" — never a confident accusation. High
precision is bought with narrow, domain-specific patterns and guards.

Detectors (python = AST-exact, others = regex):
  float-money            money handled as float (rounding/precision loss)
  money-equality         == / != on a money value (float compare)
  idor-missing-ownership endpoint fetches a record by id with no owner/authz check
  oversell-race          check-then-act on stock/balance/quota with no lock
  mass-assignment        raw request body splatted into a model (over-posting)
  auth-no-ratelimit      credential check with no rate-limit / lockout (brute-force)
  ssrf-user-url          outbound request to a request-controlled URL, no allowlist
  open-redirect          redirect target taken from the request, no allowlist
  idempotency-missing    charge/create side-effect with no idempotency guard
  pagination-offset      page→offset math that is off-by-one
  unit-mismatch          cents/dollars or ms/s mixing near money/time
  tenant-allobjects      unscoped fetch-all in a multi-tenant context
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

try:
    from . import common
    from .bughunt import Finding
except ImportError:
    import common
    from bughunt import Finding

MONEY = re.compile(
    r"(?i)\b(price|amount|total|subtotal|cost|balance|salary|wage|fee|tax|vat|"
    r"discount|charge|payment|refund|cents|dollars?|usd|eur|gbp|money|wallet|"
    r"credit|debit|invoice|payout|fund|deposit|withdraw|interest|principal)\b"
)
# An actual ACCESS GUARD, not just any mention of "owner": a caller-scoped filter,
# an explicit deny, an ownership comparison, or an auth decorator/dependency.
# Broad words like bare "owner"/"require" are excluded so they cannot mask a real IDOR.
AUTHZ = re.compile(
    r"(?i)(current_user|request\.user|\.user\.id|g\.user|@login_required|"
    r"requires?_auth|login_required|permission_classes|@roles?|has_perm|has_access|"
    r"is_owner|check_owner|ensure_owner|\.owner\s*==|owner_id\s*==|user_id\s*==|"
    r"tenant_id\s*==|filter\([^)]*(user|owner|tenant|account|current)|"
    r"abort\(40[13]\)|raise\s+\w*(Permission|Forbidden|NotAuthorized|Unauthorized)|"
    r"PermissionDenied|HTTP_40[13]|Depends\(|authorize\()"
)
# A fetch keyed by an IDENTITY (id/pk/slug/uuid), i.e. the IDOR shape — not any query.
ID_FETCH = re.compile(
    r"(?i)(\.get\(\s*[\w_]*(id|pk|slug|uuid)\b|\.objects\.get\(\s*[\w_]*(id|pk)|"
    r"\.objects\.filter\(\s*[\w_]*(id|pk)|\.filter_by\(\s*id|get_object_or_404\(|"
    r"\.query\.get\(|\.query\.filter_by\(\s*id|\.findById\(|"
    r"\.find_one\(\s*\{?\s*['\"]?_?id|\.find\(\s*[\w_]*id|"
    r"FROM\s+\w+\s+WHERE\s+[\w.]*id\s*=)"
)
# decorators are matched on their ast.unparse() form (no leading '@'), e.g.
# "app.route('/x')", "router.get('/x')", "api_view(['GET'])", "login_required".
ROUTE_DECO = re.compile(
    r"(?i)\b\w+\.(route|websocket|get|post|put|patch|delete|view)\b|"
    r"\b(api_view|require_http_methods|route|endpoint|app|router|blueprint)\b"
)
HANDLER_PARAM = re.compile(r"(?i)\b(request|req|ctx|event|params|path_params)\b")
# fields that encode a depletable business invariant (oversell/overdraw targets)
INVARIANT_FIELD = re.compile(
    r"(?i)\b(stock|balance|quantity|qty|available|availability|quota|inventory|"
    r"credits?|remaining|seats?|capacity|count|allowance|funds?)\b"
)
# evidence the section is serialized -> not a check-then-act race
LOCK_GUARD = re.compile(
    r"(?i)(select_for_update|with_for_update|\.lock\(|Lock\(|acquire\(|atomic|"
    r"transaction\.|F\(|begin_nested|SERIALIZABLE|advisory_lock|mutex|with\s+\w*lock)"
)
# idempotency: name signals a payment/order side-effect; needs a REAL external call
SIDEFX_NAME = re.compile(
    r"(?i)(charge|capture|payout|transfer|refund|create_order|place_order|checkout)"
)
SIDEFX_CALL = re.compile(
    r"(?i)(stripe|paypal|braintree|gateway|\.charge\(|\.capture\(|\.transfer\(|"
    r"\.create\(|\.send\(|\.execute\(|INSERT\s+INTO|\.save\(\)|\.commit\()"
)
IDEMPOTENCY_GUARD = re.compile(
    r"(?i)(idempoten|dedup|already_|\bexists\(|unique|\block\b|if\s+\w*(processed|seen|handled)|request_id|nonce)"
)
# names that are NOT user-facing endpoints (server-trusted) -> not IDOR candidates
INTERNAL_HANDLER = re.compile(
    r"(?i)(webhook|^_|_handle|handle_|on_|process_|consume|worker|task|cron|"
    r"migrat|seed|backfill|internal|callback|listener|subscriber|dispatch)"
)
# mass-assignment: the raw request body splatted into a model -> over-posting.
REQ_DATA = re.compile(
    r"(?i)\b(request|req)\b\.(json|form|data|body|POST|values|args|cleaned_data)\b|"
    r"\.get_json\(\)|request\.get_json"
)
MASS_SINK_ATTR = {
    "create",
    "update",
    "insert",
    "save",
    "update_or_create",
    "get_or_create",
    "bulk_create",
    "create_user",
    "insert_one",
    "update_one",
    "modify",
}
# auth brute-force: a credential-check path with no throttle/lockout.
AUTH_FN = re.compile(
    r"(?i)^(login|log_in|signin|sign_in|authenticate|auth|verify_otp|verify_code|"
    r"verify_2fa|verify_token|check_password|reset_password|forgot_password|"
    r"confirm_code|validate_otp)$|_login$|_signin$|_authenticate$"
)
PWCHECK = re.compile(
    r"(?i)(check_password|verify_password|compare_password|password\s*==|"
    r"==\s*\w*password|bcrypt|argon2|scrypt|pbkdf2|\.verify\(|otp|one[_-]?time|"
    r"\b2fa\b|totp|hmac\.compare|secrets\.compare_digest|constant_time)"
)
RATELIMIT = re.compile(
    r"(?i)(ratelimit|rate[_-]?limit|throttle|@limiter|limiter\.|too[_-]?many|"
    r"attempts?|lockout|locked[_-]?out|backoff|retry[_-]?after|brute|captcha|"
    r"cooldown|max[_-]?tries|fail(ed)?[_-]?count|delay\(|sleep\()"
)
# SSRF: an outbound HTTP fetch whose URL comes from the inbound request.
SSRF_SINK = re.compile(
    r"(?i)\b(requests\.(get|post|put|delete|patch|head|request)|httpx\.|urlopen|"
    r"urlretrieve|aiohttp|session\.(get|post|request)|http\.client|urllib)"
)
# open redirect: a redirect target taken from the request.
REDIRECT_SINK = re.compile(
    r"(?i)(redirect|HttpResponseRedirect|RedirectResponse|sendRedirect)"
)
# the argument traces to the inbound request (url/next/return/callback params).
REQ_URL = re.compile(
    r"(?i)\b(request|req)\b\.(args|json|GET|POST|params|query|data|values|form|body)"
    r"|\b(request|req)\b.{0,30}\b(url|uri|target|dest|host|endpoint|callback|next|"
    r"redirect|return_?url|continue)\b"
)
# evidence the URL is validated/allowlisted before use -> not exploitable.
URL_GUARD = re.compile(
    r"(?i)(allow[_-]?list|allowed_hosts?|whitelist|urlparse|netloc|is_safe_url|"
    r"validate_?url|same[_-]?origin|url_has_allowed|//\s*ok|startswith\(|in\s+ALLOWED)"
)
# webhook handler: a payment/event receiver that MUST verify the sender's signature.
WEBHOOK_NAME = re.compile(
    r"(?i)webhook|stripe.*event|payment.*event|on_(stripe|paypal|payment|charge)|"
    r"handle_(webhook|event|callback)|(stripe|paypal|svix|github)_?(webhook|hook|callback)"
)
SIG_VERIFY = re.compile(
    r"(?i)(construct_?event|verify_?signature|verify_?header|webhooks?\.(construct|verify)|"
    r"\bhmac\b|compare_digest|x[-_]?hub[-_]?signature|stripe[-_]?signature|svix|"
    r"webhook_secret|signing_secret|verify_webhook|check_signature|\.verify\()"
)
# a charge/payment call whose amount is taken straight from the client = price tampering.
PAYMENT_SINK = re.compile(
    r"(?i)(\.charge\(|\.capture\(|payment_?intent|create_?(charge|payment|order)|"
    r"stripe\.|paypal\.|\.pay\(|checkout\.session|create_session)"
)
AMOUNT_TOKEN = re.compile(r"(?i)\b(amount|price|total|subtotal|sum|cost|fee)\b")
# a refund/credit whose amount is client-supplied = refund fraud (refund > paid).
REFUND_SINK = re.compile(
    r"(?i)(\.refund\(|create_?refund|refunds?\.create|issue_?refund|\.credit\(|"
    r"credit_?note|reverse_?(charge|payment)|stripe\.Refund|paypal.*refund)"
)


# ── Python AST detectors ───────────────────────────────────────────────────────
class _BizVisitor(ast.NodeVisitor):
    def __init__(self, repo, path, lines):
        self.repo, self.path, self.lines = repo, path, lines
        self.findings: list[Finding] = []

    def _add(self, node, rid, sev, title, msg, fix, cwe="", conf="medium"):
        ln = getattr(node, "lineno", 1)
        snip = self.lines[ln - 1].strip()[:200] if 0 < ln <= len(self.lines) else ""
        self.findings.append(
            Finding(
                common.rel(self.repo, self.path),
                ln,
                rid,
                sev,
                f"{title} (confidence: {conf})",
                snip,
                msg,
                fix,
                cwe,
            )
        )

    # money handled as float
    def visit_BinOp(self, node):
        if isinstance(node.op, ast.Div) and self._touches_money(node):
            self._add(
                node,
                "biz-float-money",
                "medium",
                "Money divided as float",
                "A money value is divided in floating point — fractional cents accumulate rounding error.",
                "Use integer minor units (cents) or Decimal; round explicitly at the boundary.",
                "CWE-682",
                conf="medium",
            )
        self.generic_visit(node)

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "float"
            and node.args
            and self._name_is_money(node.args[0])
        ):
            self._add(
                node,
                "biz-float-money",
                "medium",
                "Money cast to float",
                "float() on a monetary value loses exact precision (0.1+0.2 != 0.3).",
                "Parse money as Decimal or integer cents, never float.",
                "CWE-682",
                conf="high",
            )
        self._check_mass_assignment(node)
        self._check_ssrf(node)
        self._check_open_redirect(node)
        self._check_client_price(node)
        self._check_client_refund(node)
        self.generic_visit(node)

    def visit_Compare(self, node):
        if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            if self._name_is_money(node.left) or any(
                self._name_is_money(c) for c in node.comparators
            ):
                # only when a float literal or division is involved -> real float-equality risk
                involved = [node.left, *node.comparators]
                if any(
                    isinstance(n, ast.Constant) and isinstance(n.value, float)
                    for n in involved
                ):
                    self._add(
                        node,
                        "biz-money-equality",
                        "medium",
                        "Equality compare on money",
                        "Comparing money with == against a float is unreliable (binary float rounding).",
                        "Compare integer cents / Decimal, or use a tolerance for derived values.",
                        "CWE-697",
                        conf="medium",
                    )
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._check_handler_authz(node)
        self._check_oversell(node)
        self._check_idempotency(node)
        self._check_ratelimit(node)
        self._check_webhook_signature(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_mass_assignment(self, node):
        """`Model(**request.json)` / `.update(**req.body)` lets a client set fields
        you never exposed (is_admin, balance, role) — over-posting. Precise: needs a
        ** splat AND its value traced to the request body AND a model-ish sink."""
        star = next((kw for kw in node.keywords if kw.arg is None), None)
        if star is None or not REQ_DATA.search(_seg(star.value)):
            return
        f = node.func
        sink = (isinstance(f, ast.Name) and f.id[:1].isupper()) or (
            isinstance(f, ast.Attribute) and f.attr in MASS_SINK_ATTR
        )
        if not sink:
            return
        self._add(
            node,
            "biz-mass-assignment",
            "high",
            "Mass assignment from request body (over-posting)",
            "The raw request body is splatted into a model create/update — a client can set fields "
            "you never meant to expose (is_admin, role, balance). Classic over-posting bug.",
            "Whitelist allowed fields explicitly; never **request-data into a model.",
            "CWE-915",
            conf="medium",
        )

    def _call_args_src(self, node) -> str:
        return (
            " ".join(_seg(a) for a in node.args)
            + " "
            + " ".join(_seg(k.value) for k in node.keywords)
        )

    def _near(self, node, rx, before: int = 10) -> bool:
        """Does `rx` match within a window of source lines around this call?
        Used to spot a validation/allowlist guard placed just before the sink."""
        ln = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", ln)
        lo, hi = max(0, ln - 1 - before), min(len(self.lines), end + 1)
        return bool(rx.search("\n".join(self.lines[lo:hi])))

    def _check_ssrf(self, node):
        """An outbound HTTP request whose URL is taken from the inbound request,
        with no host allowlist/validation, is an SSRF pivot into internal services."""
        if not SSRF_SINK.search(_seg(node.func)):
            return
        args = self._call_args_src(node)
        if not REQ_URL.search(args):
            return
        if URL_GUARD.search(args) or self._near(node, URL_GUARD):
            return
        self._add(
            node,
            "biz-ssrf-user-url",
            "high",
            "Outbound request to a user-controlled URL (SSRF)",
            "An outbound HTTP request uses a URL from the incoming request with no host "
            "allowlist or validation — an attacker can reach internal services (SSRF).",
            "Validate the URL host/scheme against an allowlist before fetching.",
            "CWE-918",
            conf="medium",
        )

    def _check_open_redirect(self, node):
        """A redirect whose target comes straight from the request, with no allowlist,
        lets an attacker bounce a phishing link through your trusted domain."""
        if not REDIRECT_SINK.search(_seg(node.func)):
            return
        args = self._call_args_src(node)
        if not REQ_URL.search(args):
            return
        if URL_GUARD.search(args) or self._near(node, URL_GUARD):
            return
        self._add(
            node,
            "biz-open-redirect",
            "medium",
            "Redirect to a user-controlled URL (open redirect)",
            "A redirect target comes straight from the request with no allowlist/validation "
            "— an attacker can craft a phishing link that bounces through your trusted domain.",
            "Allowlist redirect targets or use is_safe_url() before redirecting.",
            "CWE-601",
            conf="medium",
        )

    def _check_webhook_signature(self, node):
        """A payment/event webhook handler that reads the request body but never
        verifies the sender's signature — anyone can POST a forged event (fake
        'payment succeeded', etc.). One of the highest-impact billing bugs."""
        deco = " ".join(_seg(d) for d in node.decorator_list)
        is_hook = bool(WEBHOOK_NAME.search(node.name)) or "webhook" in deco.lower()
        if not is_hook:
            return
        seg = _func_source(self.lines, node) + "\n" + deco
        if not REQ_DATA.search(seg) and not HANDLER_PARAM.search(seg):
            return  # doesn't actually consume the request -> not a live handler
        if SIG_VERIFY.search(seg):
            return  # signature is verified -> safe
        self._add(
            node,
            "biz-webhook-no-signature",
            "high",
            "Webhook handler does not verify the sender's signature",
            "This webhook/event handler reads the request body but never verifies a signature "
            "(Stripe-Signature / HMAC / constructEvent) — anyone can forge events (fake "
            "'payment.succeeded', entitlement grants, etc.).",
            "Verify the provider signature before trusting the payload "
            "(e.g. stripe.Webhook.construct_event with the signing secret).",
            "CWE-345",
            conf="medium",
        )

    def _check_client_price(self, node):
        """A charge/payment call whose amount comes straight from the request body
        is price tampering — the client picks what to pay. The server must look the
        price up, never trust a client-supplied amount."""
        callee = _seg(node.func)
        if not PAYMENT_SINK.search(callee):
            return
        argsrc = (
            " ".join(_seg(a) for a in node.args)
            + " "
            + " ".join(_seg(k.value) + " " + (k.arg or "") for k in node.keywords)
        )
        if REQ_DATA.search(argsrc) and AMOUNT_TOKEN.search(argsrc):
            self._add(
                node,
                "biz-client-controlled-price",
                "high",
                "Charge amount taken from the client request (price tampering)",
                "A payment/charge is created with an amount/price read straight from the request — "
                "the client can choose what to pay. The amount must be looked up server-side.",
                "Compute the charge amount from a server-side record (order/price id); never trust "
                "a client-supplied amount.",
                "CWE-602",
                conf="medium",
            )

    def _check_client_refund(self, node):
        """A refund/credit whose amount is taken from the request lets a caller refund
        more than they paid — refund fraud. The amount must be derived server-side."""
        if not REFUND_SINK.search(_seg(node.func)):
            return
        argsrc = (
            " ".join(_seg(a) for a in node.args)
            + " "
            + " ".join(_seg(k.value) + " " + (k.arg or "") for k in node.keywords)
        )
        if REQ_DATA.search(argsrc) and AMOUNT_TOKEN.search(argsrc):
            self._add(
                node,
                "biz-refund-client-amount",
                "high",
                "Refund amount taken from the client request (refund fraud)",
                "A refund/credit is issued with an amount read straight from the request — a caller "
                "can refund more than was paid. The refund amount must be derived server-side.",
                "Cap the refund at the captured amount from the server-side payment record; never "
                "trust a client-supplied refund amount.",
                "CWE-602",
                conf="medium",
            )

    def _check_ratelimit(self, node):
        """An auth/credential-check path with no rate-limit, attempt counter, or
        lockout is open to brute-force / OTP guessing. Conservative: needs an
        auth-ish name AND a credential check AND no visible throttle."""
        if not AUTH_FN.search(node.name):
            return
        seg = (
            _func_source(self.lines, node)
            + "\n"
            + " ".join(_seg(d) for d in node.decorator_list)
        )
        if not PWCHECK.search(seg) or RATELIMIT.search(seg):
            return
        self._add(
            node,
            "biz-auth-no-ratelimit",
            "medium",
            "Auth credential check with no rate-limit / lockout",
            "This authentication path verifies a credential with no visible rate-limit, attempt "
            "counter, or lockout — open to credential brute-force / OTP guessing.",
            "Add per-account + per-IP rate-limiting and lockout/backoff on repeated failures.",
            "CWE-307",
            conf="low",
        )

    def _check_idempotency(self, node):
        """A payment/order side-effect function with no idempotency guard double-
        charges on retry/double-click. Precise: needs the name AND a real side-effect
        call AND no dedup guard — so it does not fire on a function merely *named* refund."""
        if not SIDEFX_NAME.search(node.name):
            return
        seg = (
            _func_source(self.lines, node)
            + "\n"
            + " ".join(_seg(d) for d in node.decorator_list)
        )
        if not SIDEFX_CALL.search(seg):  # no actual external side-effect -> skip
            return
        if IDEMPOTENCY_GUARD.search(seg):  # already guarded -> skip
            return
        self._add(
            node,
            "biz-idempotency-missing",
            "medium",
            "Payment/order side-effect with no idempotency guard",
            "This function performs a charge/order side-effect with no idempotency key or replay check "
            "— a retry or double-click double-charges.",
            "Require an idempotency key and short-circuit on replay.",
            "CWE-674",
            conf="low",
        )

    def _check_oversell(self, node):
        """check-then-act on a business invariant (stock/balance/quota): the field
        is read in an `if` guard and then written, with no lock/atomic/select-for-
        update — two concurrent calls oversell / overdraw. The race no linter sees."""
        read_fields = {}  # field name -> lineno of the guard
        for sub in _iter_body(node):
            if isinstance(sub, ast.If):
                for cmp in ast.walk(sub.test):
                    if isinstance(cmp, ast.Attribute) and INVARIANT_FIELD.search(
                        cmp.attr
                    ):
                        read_fields.setdefault(cmp.attr, sub.lineno)
        if not read_fields:
            return
        seg = _func_source(self.lines, node)
        if LOCK_GUARD.search(seg):  # serialized -> not a race
            return
        for sub in _iter_body(node):
            target = None
            if isinstance(sub, ast.AugAssign):
                target = sub.target
            elif isinstance(sub, ast.Assign) and sub.targets:
                target = sub.targets[0]
            if isinstance(target, ast.Attribute) and target.attr in read_fields:
                self._add(
                    sub,
                    "biz-oversell-race",
                    "high",
                    "Check-then-act on a business invariant (oversell/overdraw race)",
                    f"`{target.attr}` is read in a guard and then written without a lock — two concurrent "
                    "requests both pass the check and oversell/overdraw. A linter cannot see this race.",
                    "Use an atomic update (UPDATE ... WHERE stock>=qty), select_for_update, or a DB constraint.",
                    "CWE-367",
                    conf="medium",
                )
                return

    def _check_handler_authz(self, node):
        # webhook/event/internal handlers fetch by id from a SERVER-TRUSTED payload,
        # not user input — not an IDOR. Skip them to kill that false-positive class.
        if INTERNAL_HANDLER.search(node.name):
            return
        # is this a request handler? (route decorator OR a request-ish param)
        deco_text = " ".join(_seg(d) for d in node.decorator_list)
        deco = bool(ROUTE_DECO.search(deco_text))
        params = [a.arg for a in node.args.args]
        looks_handler = deco or any(HANDLER_PARAM.search(p) for p in params)
        if not looks_handler:
            return
        # authz can live in the body OR in a decorator (@login_required, @requires_auth)
        seg = _func_source(self.lines, node) + "\n" + deco_text
        if ID_FETCH.search(seg) and not AUTHZ.search(seg):
            self._add(
                node,
                "biz-idor-missing-ownership",
                "high",
                "Endpoint fetches a record by id with no ownership/authz check",
                "This handler loads a resource by id but never checks the caller owns it or has permission "
                "— a classic IDOR / broken-access-control bug a linter cannot see.",
                "Filter by current_user/tenant or assert ownership before returning the record.",
                "CWE-639",
                conf="medium",
            )

    def _touches_money(self, node):
        return self._name_is_money(getattr(node, "left", None)) or self._name_is_money(
            getattr(node, "right", None)
        )

    def _name_is_money(self, node):
        if node is None:
            return False
        if isinstance(node, ast.Name):
            return bool(MONEY.search(node.id))
        if isinstance(node, ast.Attribute):
            return bool(MONEY.search(node.attr))
        # order["amount"] / order['price']
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            return isinstance(node.slice.value, str) and bool(
                MONEY.search(node.slice.value)
            )
        # data.get("price") / row.get('total')
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            return bool(MONEY.search(node.args[0].value))
        return False


def _seg(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _func_source(lines: list[str], node) -> str:
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    return "\n".join(lines[start:end])


def _iter_body(node):
    """Descendants of node, NOT crossing into nested function/class/lambda bodies."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def _scan_python(
    repo: Path, path: Path, text: str, lines: list[str], tree=None
) -> list[Finding]:
    if tree is None:
        tree = common.parse_python(text)  # standalone call; combined scan passes one
    if tree is None:
        return []
    v = _BizVisitor(repo, path, lines)
    v.visit(tree)
    return v.findings


# ── Regex detectors (all languages) ────────────────────────────────────────────
REGEX_RULES = [
    (
        "biz-pagination-offset",
        "medium",
        "Pagination offset is off-by-one",
        re.compile(r"(?i)offset\s*=\s*[\w.]*page\s*\*"),
        re.compile(r"(?i)\(\s*page\s*-\s*1|page0|zero.?based|//\s*ok"),
        "offset = page * size skips/repeats a row unless page is 0-based.",
        "Use (page - 1) * size for 1-based pages; confirm the page base.",
        "CWE-193",
    ),
    (
        "biz-unit-mismatch",
        "low",
        "Possible cents/dollars unit mismatch",
        re.compile(
            r"(?i)\b(amount|price|total|balance|cost|fee)\b[^\n]{0,40}(\*\s*100\b|/\s*100\b)"
        ),
        re.compile(r"(?i)percent|%|//\s*ok|basis"),
        "Multiplying/dividing money by 100 often signals an implicit cents<->dollars conversion done ad hoc.",
        "Centralize the minor-unit conversion; keep one canonical representation.",
        "CWE-1339",
    ),
    (
        "biz-tenant-allobjects",
        "medium",
        "Unscoped query in multi-tenant context",
        re.compile(
            r"(?i)\.objects\.all\(\)|SELECT\s+\*\s+FROM\s+\w+\s*(;|$)|\.find\(\s*\)|\.scan\(\)"
        ),
        re.compile(
            r"(?i)tenant|user_id|org|account|where|filter|//\s*ok|admin|migration|seed|test"
        ),
        "An unfiltered fetch-all can leak other tenants' rows if this path is multi-tenant.",
        "Scope the query by tenant/user; reserve unscoped reads for admin/batch jobs.",
        "CWE-639",
    ),
    (
        "biz-mass-assignment",
        "high",
        "Mass assignment from request body (over-posting)",
        re.compile(
            r"(?i)(new\s+\w+\(\s*req(uest)?\.body|"
            r"\.(create|update|insertOne|updateOne|save|findOneAndUpdate)\(\s*req(uest)?\.body|"
            r"Object\.assign\(\s*\w+\s*,\s*req(uest)?\.body)"
        ),
        re.compile(
            r"(?i)pick\(|whitelist|allowlist|allowed|//\s*ok|saniti[sz]e|validate|schema"
        ),
        "The raw request body is passed straight into a model create/update — a client can set "
        "fields you never exposed (isAdmin, role). Over-posting / mass-assignment bug.",
        "Whitelist the allowed fields (pick/zod schema) before persisting.",
        "CWE-915",
    ),
    (
        "biz-ssrf-user-url",
        "high",
        "Outbound request to a user-controlled URL (SSRF)",
        re.compile(
            r"(?i)(fetch|axios\.(get|post|put|request)|got|http\.get|https\.get|"
            r"request)\s*\(\s*(req(uest)?\.(query|body|params)|`[^`]*\$\{?\s*req)"
        ),
        re.compile(r"(?i)allowlist|whitelist|new URL\(|validate|isAllowed|//\s*ok"),
        "An outbound request uses a URL from the request with no allowlist — SSRF into "
        "internal services.",
        "Validate the URL host/scheme against an allowlist before fetching.",
        "CWE-918",
    ),
    (
        "biz-open-redirect",
        "medium",
        "Redirect to a user-controlled URL (open redirect)",
        re.compile(
            r"(?i)res(ponse)?\.redirect\s*\(\s*(req(uest)?\.(query|body|params)|`[^`]*\$\{?\s*req)"
        ),
        re.compile(r"(?i)allowlist|whitelist|isSafe|validate|startsWith|//\s*ok"),
        "A redirect target comes straight from the request with no allowlist — open redirect "
        "(phishing via your trusted domain).",
        "Allowlist redirect targets before redirecting.",
        "CWE-601",
    ),
    (
        "biz-client-controlled-price",
        "high",
        "Charge amount taken from the client request (price tampering)",
        re.compile(
            r"(?i)(charge|capture|createPaymentIntent|paymentIntents?\.create|"
            r"createCharge|\.pay)\s*\([^)]*req(uest)?\.(body|query|params)[^)]*"
            r"(amount|price|total|sum)"
        ),
        re.compile(r"(?i)//\s*ok|lookup|server|fromDb|priceId|catalog"),
        "A charge is created with an amount read from the request — the client picks the price.",
        "Look the amount up server-side from an order/price id; never trust client amounts.",
        "CWE-602",
    ),
]


def _scan_regex(repo: Path, path: Path, lang: str, lines: list[str]) -> list[Finding]:
    out = []
    for rid, sev, title, rx, guard, msg, fix, cwe in REGEX_RULES:
        for i, ln in enumerate(lines):
            if rx.search(ln) and not (guard and guard.search(ln)):
                out.append(
                    Finding(
                        common.rel(repo, path),
                        i + 1,
                        rid,
                        sev,
                        f"{title} (confidence: low — verify)",
                        ln.strip()[:200],
                        msg,
                        fix,
                        cwe,
                    )
                )
    return out


def scan_file(repo: Path, path: Path, lang: str) -> list[Finding]:
    text = common.read_text(path)
    if not text:
        return []
    lines = text.splitlines()
    out = _scan_regex(repo, path, lang, lines)
    if lang == "python":
        out += _scan_python(repo, path, text, lines)
    return out


def scan_repo(
    repo: Path, *, limit: int = 6000, only_files: set[str] | None = None
) -> list[Finding]:
    out = []
    for path, lang in common.iter_source_files(repo, limit=limit):
        if only_files is not None and common.rel(repo, path) not in only_files:
            continue
        out.extend(scan_file(repo, path, lang))
    out.sort(key=lambda f: (-common.SEVERITY_RANK.get(f.severity, 0), f.file, f.line))
    return out


if __name__ == "__main__":
    import json
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    fs = scan_repo(repo, limit=3000)
    print(
        json.dumps(
            {"total": len(fs), "findings": [f.as_dict() for f in fs[:25]]}, indent=2
        )
    )
