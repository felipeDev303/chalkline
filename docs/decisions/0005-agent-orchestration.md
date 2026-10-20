# 0005 — Agent desk: MCP tools, AF workflow, attributed verification
Builds on 0004. Microsoft Agent Framework 1.22 (`Agent`, `WorkflowBuilder`), MCP 2.3.

- **Tools.** The 7 metric tools are served by an MCP server (`agents/mcp_server.py`,
  schemas from `metrics/registry.py`) and, in-process, as AF function tools. Both
  return `ToolResult` JSON; tool errors go back to the model so it can fix the call.
- **No look-ahead by construction.** The analyst's tools see the match cut at the
  turn's `as_of_seq`; asking for a later seq returns `as_of_out_of_range`. Results at
  any other seq are dropped (one turn = one `as_of_seq`).
- **Workflow.** analyst -> narrator -> verifier, with verifier -> narrator for the one
  retry. The verifier is deterministic code, not a model.
- **Attributed verification.** The narrator returns sentences with the evidence ids
  they use. A sentence passes only if each of its numbers matches a fact *it cites*;
  a true number attributed to the wrong fact fails. Sentences with no numbers and no
  citations are labelled interpretation; at least one sentence must cite evidence.
- **Names.** A capitalised name close to a roster name but not equal to it is a
  misspelling (gpt-4.1-mini wrote "Davenport Athletic", "Drapenport's" for
  "Dravenport Athletic" in early runs).
- **Retry feedback.** Says which numbers failed and that plain numbers must be copied,
  never counted or computed. It suggests ids only for minute marks and scorelines,
  whose value identifies the fact: suggesting a fact for a plain "2" would invite a
  citation that passes verification while meaning something else.
- **Not checked yet:** comparatives and qualitative claims ("more shots" without the
  rival's figure). That needs a claim-level (semantic) check.
- **Recovery.** Model chain (primary, optional fallback deployment) per step; no
  analyst results -> deterministic default evidence (match_summary + key_moments);
  verification fails twice or no model answers -> evidence only (CLAUDE.md rule).
  Every recovery is recorded in `Insight.notes`.
- **Offline.** `ScriptedChatClient` drives the same workflow in tests (no network).
- **Azure.** `infra/foundry.bicep`: one keyless AI Services account (local auth off),
  project `pitchside`, gpt-4.1-mini primary and gpt-5-mini fallback (Global Standard,
  50K TPM each, below quota as a cost cap), Foundry User role for the caller.
  `infra/budget.bicep`: monthly budget with alerts at 50%, 80% and forecast 100%.
  Azure for Students limits regions to northcentralus, westus, southafricanorth,
  chilecentral and newzealandnorth; only the first three have OpenAI quota.
