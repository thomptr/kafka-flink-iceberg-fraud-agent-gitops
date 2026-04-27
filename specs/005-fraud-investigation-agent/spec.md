# Feature Specification: Fraud Investigation Agent

**Feature Branch**: `005-fraud-investigation-agent`  
**Created**: 2026-04-26  
**Status**: Draft  
**Input**: User description: "Create a fraud investigation agent that allows human-in-the-loop investigation on why a transaction was flagged as fraudulent"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Open Investigation and Get Initial Explanation (Priority: P1)

A fraud analyst receives a fraud alert and needs to understand why a specific transaction was flagged. They open an investigation session for that transaction and the agent immediately provides a plain-language explanation: which risk signals were strongest, how the transaction compares to the user's normal behaviour, and what the ML model weighed most heavily. The analyst leaves the session knowing the key reasons for the flag without having to manually query multiple data sources.

**Why this priority**: Explaining the fraud flag is the core value of this feature. Every other capability (drilling down, asking follow-ups, recording conclusions) depends on this initial explanation existing and being accessible to the analyst.

**Independent Test**: Can be fully tested by opening an investigation session for a known flagged transaction ID and verifying that the agent returns a structured explanation containing at least: a plain-language summary, the top contributing risk factors ranked by importance, and the transaction's fraud probability score.

**Acceptance Scenarios**:

1. **Given** a fraud alert exists for a transaction, **When** an analyst opens an investigation session for that transaction ID, **Then** within 30 seconds the agent returns a summary that includes: a plain-language explanation of why the transaction was flagged, the top 3 or more contributing risk signals, and the fraud probability score.
2. **Given** an analyst opens an investigation session, **When** the agent's explanation references a risk signal, **Then** each signal is accompanied by the supporting data value (e.g., "transaction amount is 4× the user's 30-day average of $42") rather than a bare label.
3. **Given** an analyst opens an investigation session for a transaction where context data is partially unavailable, **When** the agent generates its explanation, **Then** the explanation clearly notes which signals could not be evaluated and why, rather than omitting them silently.

---

### User Story 2 - Ask Follow-Up Questions in Plain Language (Priority: P2)

During an investigation, an analyst wants to explore a specific angle — for example, "Has this merchant been associated with fraud before?" or "Show me the user's last 10 transactions." They type their question in natural language and receive a direct, evidence-grounded answer from the agent without leaving the investigation session or switching tools.

**Why this priority**: The initial explanation covers the most salient signals but analysts frequently need to follow threads the automated summary does not anticipate. Conversational follow-up is what makes this an investigation tool rather than a static report viewer.

**Independent Test**: Can be tested independently by starting an investigation session and submitting a series of pre-defined natural-language questions; verifying that each answer references real underlying data (not fabricated) and directly addresses the question asked.

**Acceptance Scenarios**:

1. **Given** an active investigation session, **When** the analyst asks a question about the transaction, the user, or the merchant in natural language, **Then** the agent responds with a factual, data-grounded answer within 15 seconds.
2. **Given** an analyst asks a question the agent cannot answer because the required data is unavailable, **When** the agent responds, **Then** it explicitly states what data is missing and suggests what alternative information might be relevant.
3. **Given** an analyst asks a question outside the scope of fraud investigation for this transaction (e.g., requests unrelated account changes), **When** the agent responds, **Then** it politely declines and redirects the conversation to investigation-relevant topics.
4. **Given** a multi-turn conversation within a session, **When** the analyst refers to a previously discussed entity (e.g., "that merchant"), **Then** the agent correctly resolves the reference to the entity mentioned earlier in the session.

---

### User Story 3 - Explore Underlying Evidence and Data (Priority: P3)

An analyst is not satisfied with a summary and wants to see the raw data behind the agent's claims. They ask the agent to show them the transaction history used, the merchant's fraud rate, or the specific ML feature values. The agent surfaces the actual data in a readable format, letting the analyst independently verify the evidence.

**Why this priority**: Trust in agent decisions requires access to underlying evidence. Analysts in regulated environments need to verify conclusions before acting on them. This builds on the explanation (P1) and Q&A (P2) stories.

**Independent Test**: Can be tested by requesting specific data items (transaction history, ML feature values, merchant risk profile) within a session and verifying the returned data matches the source records available in the system.

**Acceptance Scenarios**:

1. **Given** an active investigation session, **When** the analyst requests to see the user's recent transaction history, **Then** the agent returns the transaction records in chronological order with key fields visible (date, amount, merchant, location).
2. **Given** an active investigation session, **When** the analyst requests the ML model's feature values for the flagged transaction, **Then** the agent returns each feature name, its value for this transaction, and the user's historical baseline for that feature where available.
3. **Given** an analyst requests evidence data that the agent already surfaced earlier in the session, **When** the agent responds, **Then** it returns the same data without re-fetching from source (consistent within a session).

---

### User Story 4 - Record Investigation Conclusion (Priority: P4)

At the end of an investigation session, the analyst records their conclusion: whether the transaction is confirmed fraud, a false positive, or requires escalation. They can add free-text notes. The conclusion is linked to the originating fraud alert, becomes part of the audit trail, and is surfaced on the alert dashboard.

**Why this priority**: Recording outcomes closes the investigation loop, provides accountability, and feeds data back for model and agent improvement. This depends on the investigation interaction stories above being functional first.

**Independent Test**: Can be tested by completing a mock investigation session, submitting a conclusion with notes, and verifying the conclusion record is correctly linked to the alert, persisted with analyst identity and timestamp, and visible on the alert record.

**Acceptance Scenarios**:

1. **Given** an active investigation session, **When** the analyst submits a conclusion (Confirmed Fraud / False Positive / Escalate) with optional notes, **Then** the conclusion is persisted with analyst identity, timestamp, and session ID, linked to the originating alert.
2. **Given** an analyst submits a conclusion, **When** the submission is accepted, **Then** the originating fraud alert's status is updated to reflect the conclusion and no further investigation sessions can overwrite it without explicit analyst intent.
3. **Given** a concluded investigation, **When** a supervisor reviews the fraud alert, **Then** the full investigation transcript (all agent responses and analyst questions) is accessible alongside the recorded conclusion.

---

### Edge Cases

- What happens when an investigation session is opened for a transaction that has no associated fraud alert (e.g., transaction ID typo or alert deleted)?
- How does the agent behave when all context data sources (transaction history, merchant data, ML features) are simultaneously unavailable?
- What happens if an analyst closes their browser mid-session — can they resume the session or is it lost?
- How does the system handle concurrent investigation sessions opened by two different analysts for the same transaction?
- What happens when the agent's response takes longer than expected — does the session time out or queue the response?
- How does the system behave when the ML model's feature values are present but the feature meanings are not registered in the system?
- What happens when an analyst tries to submit a conclusion for a transaction that was already concluded by another analyst?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow an authorised analyst to open an investigation session for any existing fraud alert by providing the transaction or alert identifier.
- **FR-002**: When a session opens, the agent MUST automatically generate and return an initial explanation of why the transaction was flagged, including: the top contributing risk signals (minimum 3 when available), supporting data values for each signal, and the fraud probability score.
- **FR-003**: The agent MUST respond to analyst questions in natural language within an active session, grounding every answer in retrievable data rather than general knowledge.
- **FR-004**: The agent MUST be able to surface, on request, the following evidence sources: the user's recent transaction history, the flagged transaction's ML feature values and baselines, and the merchant's historical fraud rate.
- **FR-005**: The agent MUST clearly communicate when a requested data source is unavailable, stating what is missing rather than omitting it silently or substituting fabricated values.
- **FR-006**: The agent MUST maintain conversational context within a session, correctly resolving references to entities discussed earlier in the same session.
- **FR-007**: Analysts MUST be able to submit a conclusion (Confirmed Fraud / False Positive / Escalate for Review) with optional free-text notes from within the investigation session.
- **FR-008**: A submitted conclusion MUST be persisted with the analyst's identity, timestamp, and session ID, and linked to the originating fraud alert record.
- **FR-009**: Submitting a conclusion MUST update the status of the originating fraud alert to reflect the outcome.
- **FR-010**: The full transcript of each investigation session (all analyst inputs and agent responses) MUST be stored as part of the alert's audit trail and be retrievable by authorised reviewers.
- **FR-011**: The system MUST prevent two conclusions from overwriting each other silently when two analysts investigate the same alert concurrently; a conflict MUST be surfaced to the second submitter.
- **FR-012**: Investigation sessions for alerts that already have a recorded conclusion MUST be accessible in read-only mode, displaying the prior transcript and conclusion.

### Security & Access Considerations *(mandatory)*

- **SA-001**: Investigation sessions MUST require authenticated analyst credentials; unauthenticated or session-expired requests MUST be rejected.
- **SA-002**: Access to investigation sessions and alert data MUST be restricted to authorised fraud operations roles; cross-analyst access to another analyst's in-progress session MUST require elevated permission.
- **SA-003**: Credentials for all data sources accessed by the agent (transaction history, ML feature store, merchant data) MUST be sourced from secrets management and never embedded in session data or logs.
- **SA-004**: Investigation transcripts contain sensitive transaction and user data; they MUST be stored and transmitted in a manner that complies with applicable financial data handling requirements and retained for a minimum of 7 years.
- **SA-005**: The agent MUST NOT expose raw personally identifiable information (e.g., full card numbers, SSNs) in session responses; such values MUST be masked to the minimum necessary for investigation.

### Documentation Impact *(mandatory)*

- **DI-001**: A new operational guide MUST be created covering: how analysts start and navigate an investigation session, what data sources the agent can access, and how to interpret agent confidence indicators.
- **DI-002**: `README.md` MUST be updated to include the fraud investigation agent in the system architecture overview alongside the existing alert orchestration system.
- **DI-003**: The `004-fraud-alert-agent` runbook MUST be updated to reference the investigation agent as the tool analysts use to drill into alerts produced by the alert orchestration system.

### Key Entities *(include if feature involves data)*

- **InvestigationSession**: A single interactive session between an analyst and the agent for a specific fraud alert. Key attributes: session ID, alert ID, analyst identity, start time, status (Active / Concluded / Abandoned), transcript of exchanges.
- **SessionTurn**: A single exchange within a session — the analyst's input and the agent's response, with a timestamp. Forms the retrievable session transcript.
- **InvestigationConclusion**: The analyst's recorded outcome for a session. Attributes: session ID, alert ID, outcome (Confirmed Fraud / False Positive / Escalate), analyst notes, analyst identity, timestamp.
- **EvidenceItem**: A data point surfaced by the agent during investigation — source (transaction history / ML features / merchant data), key, value, baseline value (where applicable), and retrieved timestamp.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Analysts can open an investigation session and receive an initial explanation for a flagged transaction within 30 seconds, for 95% of sessions under normal load.
- **SC-002**: 90% of analyst follow-up questions receive a data-grounded response within 15 seconds.
- **SC-003**: Analysts rate the agent's initial explanation as "useful" or "very useful" in post-session feedback for at least 80% of completed investigations.
- **SC-004**: Average analyst time-to-conclusion drops by at least 50% compared to unassisted manual investigation of the same alert type.
- **SC-005**: 100% of concluded investigation sessions have a complete, retrievable transcript with no missing turns.
- **SC-006**: False fabrication rate — agent responses that reference data not present in any connected data source — is zero, validated by automated spot-check audits.
- **SC-007**: Concurrent session conflicts (two analysts concluding the same alert simultaneously) are surfaced and prevented for 100% of detected collisions.

## Assumptions

- The fraud investigation agent operates on alerts already created by the fraud alert orchestration system (004); it is not responsible for independently detecting fraud or scoring transactions.
- The agent has read-only access to the same data sources the automated triage agent uses: user transaction history, ML feature values, and merchant data; no new data integration is required beyond what 004 established.
- Analyst authentication reuses the existing platform identity provider; no new auth system is introduced.
- For v1, the investigation interface is a text-based conversational UI accessible via a web browser; voice or mobile interfaces are out of scope.
- The agent does not take any autonomous actions (e.g., blocking a card, freezing an account) — it is advisory only; all actions remain with the human analyst.
- Session persistence across browser refreshes is supported; analysts can resume an in-progress session after a disconnect within a configurable inactivity timeout (default 60 minutes).
- Financial data retention of 7 years is assumed, consistent with the fraud alert orchestration system.
- The system does not execute the block, review, or monitor decision itself; it records the analyst's conclusion and the originating fraud alert system handles downstream execution.
