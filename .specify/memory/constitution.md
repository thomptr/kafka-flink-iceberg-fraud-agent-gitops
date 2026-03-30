<!--
Sync Impact Report
Version change: unversioned template -> 1.0.0
Modified principles:
- Template Principle 1 -> I. Security by Default
- Template Principle 2 -> II. Production-Grade Engineering
- Template Principle 3 -> III. README-Driven Documentation
- Template Principle 4 -> IV. Performance Is a Feature
- Template Principle 5 -> V. Observable and Operable Systems
Added sections:
- Operational Requirements
- Delivery Workflow
Removed sections:
- None
Templates requiring updates:
- ✅ .specify/templates/plan-template.md
- ✅ .specify/templates/spec-template.md
- ✅ .specify/templates/tasks-template.md
- ✅ Runtime guidance review completed; no README.md, docs/, or AGENTS.md files were present to update
Follow-up TODOs:
- None
-->
# Kafka Flink Iceberg Fraud Agent GitOps Constitution

## Core Principles

### I. Security by Default
All code, infrastructure, and configuration changes MUST default to least privilege,
explicit trust boundaries, and approved secret handling before merge. Plaintext
credentials, hard-coded tokens, anonymous administrative access, and undocumented
external integrations are prohibited. Every feature spec and implementation plan MUST
describe authentication, authorization, data sensitivity, and exposure risks for the
components it changes. Rationale: this repository orchestrates data and fraud
platform workloads where insecure defaults can compromise pipelines, infrastructure,
and sensitive business data.

### II. Production-Grade Engineering
Changes MUST be small enough to review, reproducible in local or automated workflows,
and validated with linting, tests, and rollback-aware deployment steps appropriate to
their blast radius. Contributors MUST prefer established framework conventions,
explicit configuration, and maintainable designs over shortcuts or one-off patterns.
If a temporary workaround is unavoidable, the change MUST record a dated follow-up
task before release. Rationale: disciplined engineering lowers operational risk and
keeps a multi-platform GitOps repository maintainable.

### III. README-Driven Documentation
Every top-level application, service, job, and operationally significant directory
MUST contain a current README or clearly reference one that documents purpose,
ownership, prerequisites, local development steps, deployment touchpoints,
configuration, and troubleshooting guidance. Any change that alters setup,
interfaces, operations, or recovery steps MUST update the affected README in the same
change. Rationale: durable documentation is required for onboarding, incident
response, and safe handoffs across platform components.

### IV. Performance Is a Feature
Each feature specification and implementation plan MUST define measurable
performance expectations for the paths it affects, including relevant latency,
throughput, startup, cost, or resource-usage targets. Work that can affect Kafka,
Flink, Iceberg, ML workflows, or GitOps reconciliation MUST identify expected load,
scaling limits, back-pressure behavior, and validation method before implementation.
Changes that materially degrade agreed targets MUST not merge without explicit
approval and a mitigation plan. Rationale: unreliable performance undermines fraud
detection, data freshness, and cluster stability.

### V. Observable and Operable Systems
New or modified services, jobs, pipelines, and automation MUST emit structured logs,
expose health or readiness signals where applicable, and document the dashboards,
alerts, or manual checks needed to operate them. Failure modes MUST be diagnosable
from repository-documented telemetry and runbooks without relying on tribal
knowledge. Rationale: observability and operability are prerequisites for fast
recovery in a distributed platform.

## Operational Requirements

- Secrets MUST be stored in approved secret-management mechanisms or encrypted
  manifests; sample values may appear only as clearly fake examples.
- Dependency additions MUST come from maintained sources and include a brief reason
  for adoption in the relevant plan, spec, or README update.
- Interfaces between Kafka producers, Flink jobs, Iceberg tables, ML pipelines, and
  services MUST document schema expectations, ownership, and failure handling.
- Performance-sensitive changes MUST capture a baseline or reference expectation
  before merge and record the validation command, dashboard, or benchmark source.

## Delivery Workflow

- Feature specifications MUST identify security impact, documentation impact, and
  measurable success criteria before planning begins.
- Implementation plans MUST pass a constitution check covering security, engineering
  quality, documentation, performance, and observability before design work is
  considered complete.
- Task lists MUST include the documentation, validation, security, and performance
  work required to satisfy this constitution; these items are not optional polish.
- Pull requests and reviews MUST reject changes that violate these principles or omit
  the evidence needed to assess compliance.

## Governance

This constitution supersedes conflicting local habits, branch conventions, or
undocumented team practices for this repository.

Amendments MUST be proposed in a pull request that includes the rationale, the
affected principles or sections, the required updates to dependent templates and
guidance files, and any migration or adoption notes.

Versioning policy follows semantic versioning for governance:
- MAJOR: removing or redefining a principle in a backward-incompatible way
- MINOR: adding a new principle or materially expanding governance requirements
- PATCH: clarifications, wording improvements, or non-semantic refinements

Compliance review is mandatory for every feature spec, implementation plan, task list,
and pull request. Reviewers MUST verify that required security analysis, README
updates, performance expectations, and observability evidence are present or
explicitly marked not applicable with justification.

**Version**: 1.0.0 | **Ratified**: 2026-03-29 | **Last Amended**: 2026-03-29
