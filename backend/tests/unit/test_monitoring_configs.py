"""Unit tests for Stream 7 PR 3 -- E.2 monitoring configs.

These tests are the regression guard against quiet drift in the
``infra/monitoring/`` YAML files:

* ``alerts.yml`` MUST contain the four PRD-mandated alert rules
  with the exact metric series the application writes. If a
  developer renames ``aoe_extraction_runs_total`` without updating
  the alert expr, the alert silently never fires -- this test
  catches that.

* ``prometheus.yml`` MUST scrape the backend's metrics endpoint
  and load ``alerts.yml`` -- otherwise rules never evaluate.

* ``alertmanager.yml`` MUST split critical vs warning routing so
  pages don't get the same dedup window as warnings.

We validate STRUCTURE, not PromQL semantics -- a full promtool
check needs the Prometheus binary and an integration harness.
The structural assertions below catch the bugs that matter
(missing alerts, mistyped metric names, missing severity labels).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Repo root is three levels up from this test file:
# backend/tests/unit/test_monitoring_configs.py -> backend/ -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
MONITORING_DIR = REPO_ROOT / "infra" / "monitoring"


# PRD-mandated alerts. The keys MUST match the alert names in
# ``alerts.yml``; the values document the required minimum
# contract (severity + the metric series the expr must reference).
# When a new alert is added to the PRD, extend this dict -- the
# test below will then fail until the YAML is updated.
REQUIRED_ALERTS: dict[str, dict[str, object]] = {
    "ExtractionFailureRateHigh": {
        "severity": "critical",
        "expr_must_reference": "aoe_extraction_runs_total",
    },
    "APILatencyP95High": {
        "severity": "warning",
        "expr_must_reference": "aoe_http_request_duration_seconds_bucket",
    },
    "ExtractionQueueBacklog": {
        "severity": "warning",
        "expr_must_reference": "aoe_queue_depth",
    },
    "ArangoDBConnectionFailures": {
        "severity": "critical",
        "expr_must_reference": "aoe_db_connection_errors_total",
    },
}


@pytest.fixture(scope="module")
def alerts_yaml() -> dict:
    """Parse ``infra/monitoring/alerts.yml`` once per module run.

    A parse failure means the file is malformed YAML -- a real
    deployment break, since Prometheus refuses to start with a
    bad rules file. Hard-fail the test module if it doesn't load.
    """
    path = MONITORING_DIR / "alerts.yml"
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def prometheus_yaml() -> dict:
    """Parse ``infra/monitoring/prometheus.yml``."""
    path = MONITORING_DIR / "prometheus.yml"
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def alertmanager_yaml() -> dict:
    """Parse ``infra/monitoring/alertmanager.yml``."""
    path = MONITORING_DIR / "alertmanager.yml"
    return yaml.safe_load(path.read_text())


class TestAlertsYaml:
    """Contract: ``alerts.yml`` carries all four PRD-required alerts,
    each with the right severity label and a reference to a real
    application-written metric series.
    """

    def test_all_required_alerts_present(self, alerts_yaml: dict) -> None:
        """Every alert listed in ``REQUIRED_ALERTS`` must appear in
        the YAML. If this fails, an alert that the PRD requires has
        been deleted or renamed without updating the contract.
        """
        rules = _flatten_rules(alerts_yaml)
        names = {r["alert"] for r in rules if "alert" in r}
        missing = set(REQUIRED_ALERTS) - names
        assert not missing, f"Missing required alerts: {missing}"

    def test_each_alert_has_correct_severity(self, alerts_yaml: dict) -> None:
        """Severity drives Alertmanager routing -- a missing or
        mistyped severity sends a page to the warnings channel
        (or worse, the catch-all). Pin it.
        """
        rules = {r["alert"]: r for r in _flatten_rules(alerts_yaml) if "alert" in r}
        for name, contract in REQUIRED_ALERTS.items():
            labels = rules[name].get("labels", {})
            assert labels.get("severity") == contract["severity"], (
                f"{name}: expected severity={contract['severity']}, got {labels.get('severity')}"
            )

    def test_each_alert_expr_references_live_metric(self, alerts_yaml: dict) -> None:
        """The PromQL expr must reference the metric series the
        application actually writes. If someone typos
        ``aoe_extraction_run_total`` (singular), the alert is a
        no-op and we catch it here, not in production.
        """
        rules = {r["alert"]: r for r in _flatten_rules(alerts_yaml) if "alert" in r}
        for name, contract in REQUIRED_ALERTS.items():
            expr = rules[name].get("expr", "")
            needle = contract["expr_must_reference"]
            assert needle in expr, f"{name}: expr does not reference {needle!r}.\nExpr was:\n{expr}"

    def test_each_alert_has_annotations(self, alerts_yaml: dict) -> None:
        """Annotations (``summary``, ``description``) drive the
        rendered alert payload. An alert without these is useless
        to the on-call: the title is just the rule name and the
        body is empty.
        """
        rules = {r["alert"]: r for r in _flatten_rules(alerts_yaml) if "alert" in r}
        for name in REQUIRED_ALERTS:
            annotations = rules[name].get("annotations", {})
            assert annotations.get("summary"), f"{name}: missing summary annotation"
            assert annotations.get("description"), f"{name}: missing description annotation"

    def test_critical_alerts_have_runbook_url(self, alerts_yaml: dict) -> None:
        """Critical (paging) alerts must carry a ``runbook_url``
        annotation pointing at the matching section of the
        operations doc. Warnings are exempt -- they're not
        page-worthy, so a runbook is nice-to-have not must-have.
        """
        rules = {r["alert"]: r for r in _flatten_rules(alerts_yaml) if "alert" in r}
        for name, contract in REQUIRED_ALERTS.items():
            if contract["severity"] != "critical":
                continue
            annotations = rules[name].get("annotations", {})
            assert annotations.get("runbook_url"), f"{name}: critical alert missing runbook_url"


class TestPrometheusYaml:
    """Contract: ``prometheus.yml`` actually scrapes the backend
    and loads ``alerts.yml``. A perfectly-written rules file is
    silent if Prometheus doesn't load it.
    """

    def test_scrapes_backend_metrics_endpoint(self, prometheus_yaml: dict) -> None:
        """The backend service exposes metrics at
        ``/api/v1/metrics``. The scrape config must hit that
        path on the in-network ``backend:8000`` target.
        """
        jobs = {j["job_name"]: j for j in prometheus_yaml.get("scrape_configs", [])}
        assert "aoe-backend" in jobs, "no scrape job named 'aoe-backend'"
        job = jobs["aoe-backend"]
        assert job["metrics_path"] == "/api/v1/metrics"
        targets = job["static_configs"][0]["targets"]
        assert "backend:8000" in targets, (
            f"aoe-backend job does not target backend:8000 (got {targets})"
        )

    def test_loads_alerts_rule_file(self, prometheus_yaml: dict) -> None:
        """``rule_files`` must point at ``alerts.yml`` (mounted at
        ``/etc/prometheus/alerts.yml`` per the compose bind). If
        the path drifts, the alert rules never load.
        """
        rule_files = prometheus_yaml.get("rule_files", [])
        assert any("alerts.yml" in f for f in rule_files), (
            f"alerts.yml not loaded; rule_files={rule_files}"
        )

    def test_wires_alertmanager(self, prometheus_yaml: dict) -> None:
        """Firing alerts must be sent to Alertmanager -- otherwise
        the rules evaluate but nothing happens.
        """
        alerting = prometheus_yaml.get("alerting", {})
        managers = alerting.get("alertmanagers", [])
        assert managers, "no alertmanagers configured"
        targets = managers[0]["static_configs"][0]["targets"]
        assert any("alertmanager" in t for t in targets), f"alertmanager not in targets: {targets}"


class TestAlertmanagerYaml:
    """Contract: routing splits critical vs warning, and a
    default catch-all receiver exists so unmatched alerts don't
    drop on the floor.
    """

    def test_has_routes_for_critical_and_warning(self, alertmanager_yaml: dict) -> None:
        """Both severity levels need explicit routes -- relying on
        the default catch-all to handle critical alerts means they
        get the same group_interval as warnings (12h), so a real
        outage takes 12h to re-page.
        """
        routes = alertmanager_yaml.get("route", {}).get("routes", [])
        severities = {r.get("match", {}).get("severity") for r in routes}
        assert "critical" in severities, "no route for severity=critical"
        assert "warning" in severities, "no route for severity=warning"

    def test_has_default_receiver(self, alertmanager_yaml: dict) -> None:
        """A default receiver is required at the top of the route
        tree, even if it's a stdout-only stub. Without it,
        Alertmanager refuses to start.
        """
        default_receiver = alertmanager_yaml.get("route", {}).get("receiver")
        assert default_receiver, "no default receiver at root route"
        receivers = {r["name"] for r in alertmanager_yaml.get("receivers", [])}
        assert default_receiver in receivers, f"default receiver {default_receiver!r} not declared"

    def test_inhibits_warnings_while_critical_firing(self, alertmanager_yaml: dict) -> None:
        """When a critical alert is firing for an incident, the
        matching warning alert should be inhibited so the on-call
        doesn't get paged twice about the same thing.
        """
        rules = alertmanager_yaml.get("inhibit_rules", [])
        assert rules, "no inhibit_rules -- duplicate paging risk"
        rule = rules[0]
        assert rule.get("source_match", {}).get("severity") == "critical"
        assert rule.get("target_match", {}).get("severity") == "warning"


# -- helpers -----------------------------------------------------------


def _flatten_rules(alerts_doc: dict) -> list[dict]:
    """Pull every rule out of every group in the alerts file.

    Prometheus rule files nest ``rules`` under ``groups``; tests
    don't care about the grouping, just the flat list of rules.
    """
    rules: list[dict] = []
    for group in alerts_doc.get("groups", []):
        rules.extend(group.get("rules", []))
    return rules
