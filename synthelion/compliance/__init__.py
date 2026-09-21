# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""AI Compliance Engine — the governance gate in front of Synthelion's guards.

This package is deliberately an *aggregation* layer. The detection it relies
on already exists elsewhere in Synthelion (PrivacyGuard, EnterpriseGuard, the
prompt-injection guard, the agent-policy engine, the safety and sensitive
screens). What is new here is everything a compliance function needs and no
individual guard can provide on its own:

* one rule registry expressed in policy vocabulary — risk level, remediation
  action, input/output scope, on/off — bound to the guard that implements it;
* the traceability matrix from each control to the article of law it satisfies,
  generated from the live configuration so a disabled control shows up as an
  uncovered obligation instead of silently still looking compliant;
* a hash-chained audit trail that stores fingerprints, never payload text;
* generation of the technical file, DPIA, FRIA and executive report, as JSON
  and as PDF.
"""
from synthelion.compliance.audit import (
    conformity_receipt, read_entries, statistics, verify_chain,
)
from synthelion.compliance.documents import generate, to_pdf
from synthelion.compliance.engine import (
    ACTIVE, FAIL_CLOSED, FAIL_OPEN, INACTIVE, STAGING,
    ComplianceEngine, ComplianceResult, Finding,
)
from synthelion.compliance.rules import (
    Action, Category, ComplianceRule, RiskLevel, Scope,
    coverage_gaps, default_rules, traceability_matrix,
)

__all__ = [
    "ACTIVE", "STAGING", "INACTIVE", "FAIL_CLOSED", "FAIL_OPEN",
    "ComplianceEngine", "ComplianceResult", "Finding",
    "ComplianceRule", "Category", "RiskLevel", "Action", "Scope",
    "default_rules", "traceability_matrix", "coverage_gaps",
    "read_entries", "verify_chain", "statistics", "conformity_receipt",
    "generate", "to_pdf",
]
