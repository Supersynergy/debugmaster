//! Business-logic detectors — the moat. The bugs static linters can't see, because
//! they are about *intent*: an endpoint that loads a record without checking who
//! owns it, a charge whose amount comes from the client, a webhook with no signature
//! check. tree-sitter gives exact function/call node spans; the guard regexes
//! (ported 1:1 from the Python engine) decide intent within each span.

use crate::finding::Finding;
use regex::Regex;
use std::sync::LazyLock;
use tree_sitter::{Node, Parser};

macro_rules! rx {
    ($name:ident, $p:expr) => {
        static $name: LazyLock<Regex> = LazyLock::new(|| match Regex::new($p) {
            Ok(re) => re,
            Err(err) => panic!("invalid bizlogic regex `{}`: {}", $p, err),
        });
    };
}

rx!(
    MONEY,
    r"(?i)\b(price|amount|total|subtotal|cost|balance|salary|wage|fee|tax|vat|discount|charge|payment|refund|cents|dollars?|usd|eur|gbp|money|wallet|credit|debit|invoice|payout|fund|deposit|withdraw|interest|principal)\b"
);
rx!(
    AUTHZ,
    r"(?i)(current_user|request\.user|\.user\.id|g\.user|@login_required|requires?_auth|login_required|permission_classes|@roles?|has_perm|has_access|is_owner|check_owner|ensure_owner|\.owner\s*==|owner_id\s*==|user_id\s*==|tenant_id\s*==|filter\([^)]*(user|owner|tenant|account|current)|abort\(40[13]\)|raise\s+\w*(Permission|Forbidden|NotAuthorized|Unauthorized)|PermissionDenied|HTTP_40[13]|Depends\(|authorize\()"
);
rx!(
    ID_FETCH,
    r"(?i)(\.get\(\s*[\w_]*(id|pk|slug|uuid)\b|\.objects\.get\(\s*[\w_]*(id|pk)|\.objects\.filter\(\s*[\w_]*(id|pk)|\.filter_by\(\s*id|get_object_or_404\(|\.query\.get\(|\.findById\(|FROM\s+\w+\s+WHERE\s+[\w.]*id\s*=)"
);
rx!(
    ROUTE_DECO,
    r"(?i)\b\w+\.(route|websocket|get|post|put|patch|delete|view)\b|\b(api_view|require_http_methods|route|endpoint|app|router|blueprint)\b"
);
rx!(
    HANDLER_PARAM,
    r"(?i)\b(request|req|ctx|event|params|path_params)\b"
);
rx!(
    INTERNAL_HANDLER,
    r"(?i)(webhook|^_|_handle|handle_|on_|process_|consume|worker|task|cron|migrat|seed|backfill|internal|callback|listener|subscriber|dispatch)"
);
rx!(
    REQ_DATA,
    r"(?i)\b(request|req)\b\.(json|form|data|body|POST|values|args|cleaned_data)\b|\.get_json\(\)|request\.get_json"
);
rx!(
    MASS_SINK,
    r"(?i)\.(create|update|insert|save|update_or_create|get_or_create|bulk_create|create_user|insert_one|update_one|modify)$|(^|\.)[A-Z]\w*$"
);
rx!(SPLAT, r"\*\*");
rx!(
    SIDEFX_NAME,
    r"(?i)(charge|capture|payout|transfer|refund|create_order|place_order|checkout)"
);
rx!(
    SIDEFX_CALL,
    r"(?i)(stripe|paypal|braintree|gateway|\.charge\(|\.capture\(|\.transfer\(|\.create\(|\.send\(|\.execute\(|INSERT\s+INTO|\.save\(\)|\.commit\()"
);
rx!(
    IDEMPOTENCY_GUARD,
    r"(?i)(idempoten|dedup|already_|\bexists\(|unique|\block\b|if\s+\w*(processed|seen|handled)|request_id|nonce)"
);
rx!(
    WEBHOOK_NAME,
    r"(?i)webhook|stripe.*event|payment.*event|on_(stripe|paypal|payment|charge)|handle_(webhook|event|callback)|(stripe|paypal|svix|github)_?(webhook|hook|callback)"
);
rx!(
    SIG_VERIFY,
    r"(?i)(construct_?event|verify_?signature|verify_?header|webhooks?\.(construct|verify)|\bhmac\b|compare_digest|x[-_]?hub[-_]?signature|stripe[-_]?signature|svix|webhook_secret|signing_secret|verify_webhook|check_signature|\.verify\()"
);
rx!(
    PAYMENT_SINK,
    r"(?i)(\.charge\b|\.capture\b|payment_?intent|create_?(charge|payment|order)|stripe\.|paypal\.|\.pay\b|checkout\.session|create_session)"
);
rx!(
    REFUND_SINK,
    r"(?i)(\.refund\b|create_?refund|refunds?\.create|issue_?refund|\.credit\b|credit_?note|reverse_?(charge|payment)|stripe\.Refund)"
);
rx!(
    AMOUNT_TOKEN,
    r"(?i)\b(amount|price|total|subtotal|sum|cost|fee)\b"
);

fn ntext<'a>(n: Node, src: &'a [u8]) -> &'a str {
    n.utf8_text(src).unwrap_or("")
}

#[allow(clippy::too_many_arguments)]
fn add(
    out: &mut Vec<Finding>,
    rel: &str,
    node: Node,
    src: &[u8],
    id: &str,
    sev: &str,
    msg: &str,
    fix: &str,
    cwe: &str,
) {
    let line = node.start_position().row + 1;
    let snip = ntext(node, src).lines().next().unwrap_or("").trim();
    out.push(Finding::new(rel, line, id, sev, msg, fix, cwe, snip));
}

pub fn scan_python(rel: &str, src: &str) -> Vec<Finding> {
    let mut parser = Parser::new();
    if parser
        .set_language(&tree_sitter_python::LANGUAGE.into())
        .is_err()
    {
        return Vec::new();
    }
    let tree = match parser.parse(src, None) {
        Some(t) => t,
        None => return Vec::new(),
    };
    let bytes = src.as_bytes();
    let mut out = Vec::new();
    walk(tree.root_node(), bytes, rel, &mut out);
    out
}

fn walk(node: Node, src: &[u8], rel: &str, out: &mut Vec<Finding>) {
    match node.kind() {
        "function_definition" => check_function(node, src, rel, out),
        "call" => check_call(node, src, rel, out),
        _ => {}
    }
    let mut c = node.walk();
    for child in node.children(&mut c) {
        walk(child, src, rel, out);
    }
}

fn check_function(node: Node, src: &[u8], rel: &str, out: &mut Vec<Finding>) {
    let name = node
        .child_by_field_name("name")
        .map(|n| ntext(n, src))
        .unwrap_or("");
    let params = node
        .child_by_field_name("parameters")
        .map(|n| ntext(n, src))
        .unwrap_or("");
    // decorators live on the parent decorated_definition, if any
    let deco = match node.parent() {
        Some(p) if p.kind() == "decorated_definition" => ntext(p, src),
        _ => "",
    };
    let body = ntext(node, src);
    let seg = format!("{body}\n{deco}");

    // 1. IDOR — handler fetches a record by id with no ownership/authz check
    if !INTERNAL_HANDLER.is_match(name) {
        let is_handler = ROUTE_DECO.is_match(deco) || HANDLER_PARAM.is_match(params);
        if is_handler && ID_FETCH.is_match(&seg) && !AUTHZ.is_match(&seg) {
            add(
                out,
                rel,
                node,
                src,
                "biz-idor-missing-ownership",
                "high",
                "Endpoint fetches a record by id with no ownership/authz check (IDOR).",
                "Filter by current_user/tenant or assert ownership before returning the record.",
                "CWE-639",
            );
        }
    }

    // 2. webhook handler with no signature verification
    let is_hook = WEBHOOK_NAME.is_match(name) || deco.to_lowercase().contains("webhook");
    if is_hook
        && (REQ_DATA.is_match(&seg) || HANDLER_PARAM.is_match(params))
        && !SIG_VERIFY.is_match(&seg)
    {
        add(
            out,
            rel,
            node,
            src,
            "biz-webhook-no-signature",
            "high",
            "Webhook handler does not verify the sender's signature — events can be forged.",
            "Verify the provider signature (e.g. stripe.Webhook.construct_event) before trusting the payload.",
            "CWE-345",
        );
    }

    // 3. payment/order side-effect with no idempotency guard
    if SIDEFX_NAME.is_match(name) && SIDEFX_CALL.is_match(&seg) && !IDEMPOTENCY_GUARD.is_match(&seg)
    {
        add(
            out,
            rel,
            node,
            src,
            "biz-idempotency-missing",
            "medium",
            "Payment/order side-effect with no idempotency guard — a retry double-charges.",
            "Require an idempotency key and short-circuit on replay.",
            "CWE-674",
        );
    }
}

fn check_call(node: Node, src: &[u8], rel: &str, out: &mut Vec<Finding>) {
    let callee = node
        .child_by_field_name("function")
        .map(|n| ntext(n, src))
        .unwrap_or("");
    let args = node
        .child_by_field_name("arguments")
        .map(|n| ntext(n, src))
        .unwrap_or("");

    // 4. mass assignment / over-posting: **request-body into a model sink
    if SPLAT.is_match(args) && REQ_DATA.is_match(args) && MASS_SINK.is_match(callee) {
        add(
            out,
            rel,
            node,
            src,
            "biz-mass-assignment",
            "high",
            "Mass assignment from request body — a client can set fields you never exposed.",
            "Whitelist allowed fields explicitly; never **request-data into a model.",
            "CWE-915",
        );
    }

    // 5. charge amount taken straight from the client = price tampering
    if PAYMENT_SINK.is_match(callee) && REQ_DATA.is_match(args) && AMOUNT_TOKEN.is_match(args) {
        add(
            out,
            rel,
            node,
            src,
            "biz-client-controlled-price",
            "high",
            "Charge amount taken from the client request (price tampering).",
            "Compute the amount server-side from an order/price id; never trust client amounts.",
            "CWE-602",
        );
    }

    // 6. refund amount from the client = refund fraud
    if REFUND_SINK.is_match(callee) && REQ_DATA.is_match(args) && AMOUNT_TOKEN.is_match(args) {
        add(
            out,
            rel,
            node,
            src,
            "biz-refund-client-amount",
            "high",
            "Refund amount taken from the client request (refund fraud).",
            "Cap the refund at the server-side captured amount; never trust client refund amounts.",
            "CWE-602",
        );
    }

    // 7. money cast to float — precision loss
    if callee == "float" && MONEY.is_match(args) {
        add(
            out,
            rel,
            node,
            src,
            "biz-float-money",
            "medium",
            "Money cast to float loses exact precision (0.1+0.2 != 0.3).",
            "Use integer minor units (cents) or Decimal.",
            "CWE-682",
        );
    }
}

#[cfg(test)]
mod tests {
    use super::scan_python;

    fn ids(src: &str) -> Vec<String> {
        scan_python("t.py", src)
            .into_iter()
            .map(|f| f.rule_id)
            .collect()
    }

    #[test]
    fn idor_flagged_but_guarded_is_not() {
        assert!(ids("@app.route('/o/<oid>')\ndef get_order(request, oid):\n    return Order.objects.get(id=oid)\n")
            .contains(&"biz-idor-missing-ownership".to_string()));
        assert!(!ids("def get_order(request, oid):\n    o = Order.objects.get(id=oid)\n    if o.owner != request.user.id:\n        abort(403)\n    return o\n")
            .contains(&"biz-idor-missing-ownership".to_string()));
    }

    #[test]
    fn mass_assignment_but_not_explicit_kwargs() {
        assert!(
            ids("def u(request):\n    return User.objects.update(**request.json)\n")
                .contains(&"biz-mass-assignment".to_string())
        );
        assert!(
            !ids("def u(request):\n    return User.objects.update(name=request.json['name'])\n")
                .contains(&"biz-mass-assignment".to_string())
        );
    }

    #[test]
    fn webhook_without_signature_but_not_with() {
        assert!(ids("@app.route('/webhook', methods=['POST'])\ndef stripe_webhook(request):\n    return handle(request.json)\n")
            .contains(&"biz-webhook-no-signature".to_string()));
        assert!(!ids("@app.route('/webhook', methods=['POST'])\ndef stripe_webhook(request):\n    event = stripe.Webhook.construct_event(request.data, sig, secret)\n    return handle(event)\n")
            .contains(&"biz-webhook-no-signature".to_string()));
    }

    #[test]
    fn client_price_but_not_server_lookup() {
        assert!(
            ids("def pay(request):\n    return stripe.charge(amount=request.json['amount'])\n")
                .contains(&"biz-client-controlled-price".to_string())
        );
        assert!(!ids("def pay(request, oid):\n    o = Order.objects.get(id=oid)\n    return stripe.charge(amount=o.total)\n")
            .contains(&"biz-client-controlled-price".to_string()));
    }

    #[test]
    fn refund_client_amount_flagged() {
        assert!(
            ids(
                "def r(request):\n    return stripe.Refund.create(amount=request.json['amount'])\n"
            )
            .contains(&"biz-refund-client-amount".to_string())
        );
    }

    #[test]
    fn float_money_but_not_decimal() {
        assert!(
            ids("def t(p):\n    return float(p['price'])\n")
                .contains(&"biz-float-money".to_string())
        );
        assert!(
            scan_python(
                "t.py",
                "from decimal import Decimal\ndef a(x, y):\n    return Decimal(x) + Decimal(y)\n"
            )
            .is_empty()
        );
    }
}
