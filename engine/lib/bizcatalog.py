"""Business-debug catalog — 200 revenue/billing failure surfaces as an actionable
checklist, not 200 fake functions.

Two families (from the ghmax/ghgrep business-debug taxonomy):
  * PRODUCT (ghmax-style)   — high-level surfaces: debug_/inspect_/audit_/trace_/
                              monitor_/reconcile_/explain_ a revenue area.
  * PRIMITIVE (ghgrep-style)— concrete code checks: verify_/check_/validate_/... a
                              specific billing invariant.

Each entry is turned into something you can RUN: a ready `ghgrep`/`ghmax` search to
locate the relevant code, the debugmaster detector that already auto-finds it (when
one exists — only the genuinely static-detectable ones are mapped, no inflation), and
a one-line verify hint. Surfaced by `debugmaster checks`.
"""

from __future__ import annotations

import re

PRODUCT = [
    "debug_revenue_leakage",
    "debug_checkout_dropoff",
    "debug_payment_conversion",
    "debug_subscription_churn",
    "debug_trial_to_paid_conversion",
    "debug_pricing_mismatch",
    "debug_invoice_dispute",
    "debug_refund_spike",
    "debug_failed_renewals",
    "debug_entitlement_drift",
    "debug_usage_metering",
    "debug_plan_limits",
    "debug_upgrade_path",
    "debug_downgrade_path",
    "debug_coupon_abuse",
    "debug_tax_miscalculation",
    "debug_vat_validation",
    "debug_fx_margin_loss",
    "debug_payout_delay",
    "debug_settlement_gap",
    "debug_customer_lifetime_value",
    "debug_customer_health_score",
    "debug_lead_quality",
    "debug_sales_pipeline_stall",
    "debug_crm_sync_drift",
    "debug_attribution_loss",
    "debug_campaign_roi",
    "debug_paid_ads_waste",
    "debug_email_deliverability",
    "debug_onboarding_activation",
    "debug_order_fulfillment",
    "debug_inventory_stockout",
    "debug_cart_abandonment",
    "debug_shipping_delay",
    "debug_return_rate",
    "debug_fraud_risk",
    "debug_chargeback_rate",
    "debug_kyc_dropoff",
    "debug_account_lockout",
    "debug_support_escalation",
    "inspect_revenue_funnel",
    "inspect_payment_provider_health",
    "inspect_subscription_cohorts",
    "inspect_invoice_aging",
    "inspect_refund_reasons",
    "inspect_customer_segments",
    "inspect_lead_sources",
    "inspect_pipeline_velocity",
    "inspect_inventory_exposure",
    "inspect_fulfillment_sla",
    "audit_billing_integrity",
    "audit_payment_reconciliation",
    "audit_subscription_entitlements",
    "audit_invoice_sequence",
    "audit_tax_rules",
    "audit_coupon_rules",
    "audit_pricing_rules",
    "audit_revenue_recognition",
    "audit_ledger_consistency",
    "audit_customer_data_quality",
    "trace_checkout_session",
    "trace_payment_attempt",
    "trace_webhook_delivery",
    "trace_subscription_lifecycle",
    "trace_invoice_generation",
    "trace_refund_flow",
    "trace_order_lifecycle",
    "trace_crm_sync",
    "trace_lead_routing",
    "trace_support_handoff",
    "monitor_revenue_anomalies",
    "monitor_payment_failures",
    "monitor_billing_errors",
    "monitor_trial_expirations",
    "monitor_failed_webhooks",
    "monitor_invoice_overdues",
    "monitor_refund_anomalies",
    "monitor_chargeback_anomalies",
    "monitor_inventory_risk",
    "monitor_customer_health",
    "reconcile_gateway_transactions",
    "reconcile_bank_settlements",
    "reconcile_invoice_payments",
    "reconcile_subscription_state",
    "reconcile_usage_charges",
    "reconcile_tax_liability",
    "reconcile_refunds",
    "reconcile_payouts",
    "reconcile_wallet_balances",
    "reconcile_accounting_exports",
    "explain_revenue_delta",
    "explain_conversion_drop",
    "explain_churn_spike",
    "explain_failed_payment_cluster",
    "explain_invoice_variance",
    "explain_pricing_override",
    "explain_customer_health_change",
    "explain_pipeline_slippage",
    "explain_support_load_spike",
    "explain_margin_compression",
]

PRIMITIVE = [
    "verify_payment_webhook_signature",
    "verify_payment_idempotency_key",
    "verify_payment_amount_matches_order",
    "verify_payment_currency_matches_order",
    "verify_payment_status_transition",
    "verify_payment_capture_state",
    "verify_payment_provider_mapping",
    "verify_payment_retry_policy",
    "verify_payment_error_classification",
    "verify_payment_metadata_integrity",
    "trace_checkout_state_machine",
    "trace_checkout_step_latency",
    "trace_checkout_validation_errors",
    "trace_checkout_session_restore",
    "trace_checkout_payment_attach",
    "trace_checkout_inventory_reserve",
    "trace_checkout_tax_quote",
    "trace_checkout_discount_apply",
    "trace_checkout_address_validation",
    "trace_checkout_order_create",
    "check_invoice_number_sequence",
    "check_invoice_total_consistency",
    "check_invoice_tax_breakdown",
    "check_invoice_line_item_rounding",
    "check_invoice_due_date_rules",
    "check_invoice_credit_note_link",
    "check_invoice_payment_link",
    "check_invoice_customer_snapshot",
    "check_invoice_pdf_generation",
    "check_invoice_email_delivery",
    "validate_subscription_plan",
    "validate_subscription_entitlement",
    "validate_subscription_period",
    "validate_subscription_trial_state",
    "validate_subscription_renewal_date",
    "validate_subscription_cancel_at",
    "validate_subscription_pause_resume",
    "validate_subscription_quantity",
    "validate_subscription_metered_usage",
    "validate_subscription_proration",
    "reconcile_order_payment_status",
    "reconcile_order_fulfillment_status",
    "reconcile_order_refund_status",
    "reconcile_order_inventory_reservation",
    "reconcile_order_shipping_label",
    "reconcile_order_tax_snapshot",
    "reconcile_order_customer_snapshot",
    "reconcile_order_discount_snapshot",
    "reconcile_order_ledger_entries",
    "reconcile_order_external_ids",
    "audit_refund_reason_codes",
    "audit_refund_approval_chain",
    "audit_refund_amount_limits",
    "audit_refund_tax_adjustment",
    "audit_refund_inventory_return",
    "audit_refund_gateway_state",
    "audit_refund_duplicate_risk",
    "audit_refund_policy_exception",
    "audit_refund_customer_credit",
    "audit_refund_ledger_entries",
    "inspect_customer_identity_merge",
    "inspect_customer_email_state",
    "inspect_customer_billing_profile",
    "inspect_customer_payment_methods",
    "inspect_customer_entitlements",
    "inspect_customer_segment_rules",
    "inspect_customer_support_history",
    "inspect_customer_fraud_flags",
    "inspect_customer_lifecycle_stage",
    "inspect_customer_data_freshness",
    "check_pricing_rule_precedence",
    "check_pricing_currency_matrix",
    "check_pricing_plan_visibility",
    "check_pricing_discount_stack",
    "check_pricing_tax_inclusion",
    "check_pricing_feature_gate",
    "check_pricing_legacy_override",
    "check_pricing_experiment_bucket",
    "check_pricing_rounding_policy",
    "check_pricing_margin_floor",
    "monitor_webhook_backlog",
    "monitor_webhook_dead_letters",
    "monitor_webhook_retry_exhaustion",
    "monitor_webhook_signature_failures",
    "monitor_webhook_event_lag",
    "monitor_webhook_duplicate_events",
    "monitor_webhook_missing_events",
    "monitor_webhook_schema_drift",
    "monitor_webhook_provider_outage",
    "monitor_webhook_handler_errors",
    "debug_ledger_double_entry",
    "debug_ledger_unbalanced_journal",
    "debug_ledger_missing_counterparty",
    "debug_ledger_revenue_recognition",
    "debug_ledger_deferred_revenue",
    "debug_ledger_fx_gain_loss",
    "debug_ledger_tax_liability",
    "debug_ledger_payout_clearing",
    "debug_ledger_refund_reversal",
    "debug_ledger_audit_trail",
]

# domain keyword → label (first match wins, order matters)
_DOMAINS = [
    ("webhook", "webhook"),
    (
        "ledger|journal|double_entry|deferred|revenue_recognition|counterparty|audit_trail",
        "ledger",
    ),
    ("invoice", "invoice"),
    (
        "subscription|trial|renewal|entitlement|plan|proration|metered|usage_charge",
        "subscription",
    ),
    ("refund|chargeback", "refunds"),
    ("checkout|cart", "checkout"),
    ("payment|payout|settlement|gateway|capture|wallet|bank", "payments"),
    ("tax|vat|fx", "tax"),
    ("pricing|coupon|discount|margin|price", "pricing"),
    ("inventory|fulfillment|shipping|order|stockout|return", "fulfillment"),
    ("fraud|kyc|lockout", "fraud"),
    (
        "customer|lead|crm|pipeline|segment|onboarding|support|health|attribution|campaign|ads|email",
        "customer",
    ),
    ("revenue|conversion|churn|funnel|ltv|lifetime|margin", "revenue"),
]

# only the GENUINELY static-detectable checks map to a real debugmaster detector.
_DETECTOR = {
    "verify_payment_webhook_signature": "biz-webhook-no-signature",
    "monitor_webhook_signature_failures": "biz-webhook-no-signature",
    "monitor_webhook_handler_errors": "biz-webhook-no-signature",
    "verify_payment_amount_matches_order": "biz-client-controlled-price",
    "verify_payment_idempotency_key": "biz-idempotency-missing",
    "verify_payment_retry_policy": "retry-no-backoff",
    "audit_refund_amount_limits": "biz-refund-client-amount",
    "audit_refund_approval_chain": "biz-refund-client-amount",
    "inspect_payment_provider_health": "py-request-no-timeout",
    "check_invoice_line_item_rounding": "biz-float-money",
    "check_pricing_rounding_policy": "biz-float-money",
    "debug_ledger_fx_gain_loss": "biz-float-money",
    "inspect_customer_payment_methods": "biz-idor-missing-ownership",
    "inspect_customer_entitlements": "biz-idor-missing-ownership",
    "check_pricing_currency_matrix": "biz-unit-mismatch",
    "verify_payment_currency_matches_order": "biz-unit-mismatch",
}

_STOP = {
    "debug",
    "inspect",
    "audit",
    "trace",
    "monitor",
    "reconcile",
    "explain",
    "verify",
    "check",
    "validate",
}


def _domain(name: str) -> str:
    for pat, label in _DOMAINS:
        if re.search(pat, name):
            return label
    return "business"


def _entry(name: str, kind: str) -> dict:
    parts = name.split("_")
    verb = parts[0]
    tokens = [p for p in parts[1:] if p not in _STOP]
    query = " ".join(tokens)
    det = _DETECTOR.get(name)
    return {
        "name": name,
        "kind": kind,
        "verb": verb,
        "domain": _domain(name),
        "detector": det,
        "search": f'ghgrep "{query}" --fast --sources grep'
        if not det
        else f"debugmaster hunt . --class biz   # auto-detected: {det}",
        "hint": (
            f"auto-detected by debugmaster (`{det}`) — run hunt/audit"
            if det
            else f"locate with the search, then {verb} the invariant by hand"
        ),
    }


def entries(kind: str | None = None) -> list[dict]:
    out = []
    if kind in (None, "product"):
        out += [_entry(n, "product") for n in PRODUCT]
    if kind in (None, "primitive"):
        out += [_entry(n, "primitive") for n in PRIMITIVE]
    return out


def query(
    q: str | None = None,
    *,
    domain: str | None = None,
    kind: str | None = None,
    detected: bool = False,
) -> list[dict]:
    rows = entries(kind)
    if domain:
        rows = [r for r in rows if r["domain"] == domain]
    if detected:
        rows = [r for r in rows if r["detector"]]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name"] or ql in r["domain"]]
    return rows


def stats() -> dict:
    rows = entries()
    by_domain: dict[str, int] = {}
    for r in rows:
        by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
    detected = sum(1 for r in rows if r["detector"])
    return {
        "total": len(rows),
        "product": len(PRODUCT),
        "primitive": len(PRIMITIVE),
        "auto_detected": detected,
        "by_domain": dict(sorted(by_domain.items(), key=lambda kv: -kv[1])),
        "detectors": sorted(set(_DETECTOR.values())),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(stats(), indent=2))
