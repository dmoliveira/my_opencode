#!/usr/bin/env python3

from __future__ import annotations

# Shared flow-level reason codes.

DIFF_FILE_NOT_FOUND = "diff_file_not_found"
GIT_DIFF_FAILED = "git_diff_failed"

REVIEW_REPORT_INVALID = "review_report_invalid"
REVIEW_CHECKLIST_GENERATED = "review_checklist_generated"

SHIP_READY = "ship_ready"
SHIP_PREPARE_BLOCKED = "ship_prepare_blocked"
REVIEWER_POLICY_OK = "reviewer_policy_ok"
REVIEWER_POLICY_CONFLICT = "reviewer_policy_conflict"

HOTFIX_NOT_ACTIVE = "hotfix_not_active"
HOTFIX_ROLLBACK_CHECKPOINT_MISSING = "rollback_checkpoint_missing"
HOTFIX_TIMELINE_EVENT_MISSING = "timeline_event_missing"
HOTFIX_VALIDATE_FAILED = "validate_failed"
HOTFIX_FOLLOWUP_REQUIRED = "followup_issue_required"
HOTFIX_DEFERRED_VALIDATION_REQUIRED = "deferred_validation_plan_required"
HOTFIX_POSTMORTEM_REQUIRED = "postmortem_id_required"
HOTFIX_RISK_ACK_REQUIRED = "risk_ack_required"
