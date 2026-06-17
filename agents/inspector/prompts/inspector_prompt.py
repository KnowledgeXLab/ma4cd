import json
from typing import Dict, Any, Optional

from utils.inspector_audit import get_audit_protocol_append


class InspectorPrompt:
    SYSTEM_PROMPT = (
        "You are an Elite Mission-Centric Data Auditor for MA4CD. "
        "Your job is to classify links into L1/L2/L3/L4 with strict rule consistency. "
        "L1-L4 are equally important; never prioritize or down-rank a tier by default. "
        "You must distinguish page-level noise (SOFT_IGNORE) from truly toxic domains (HARD_BLACKLIST). "
        "Do not over-blacklist institutional domains."
    )

    @staticmethod
    def _normalize_mission_context(user_query: Any = "", mission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if isinstance(mission_context, dict):
            return mission_context
        if isinstance(user_query, dict):
            return user_query
        raw = str(user_query or "").strip()
        return {"human_request": raw} if raw else {}

    @staticmethod
    def _mission_text(ctx: Dict[str, Any]) -> str:
        if not ctx:
            return "General Scientific Research Acquisition"
        human = str(ctx.get("human_request", "")).strip()
        core = str(ctx.get("commander_core_intent", "")).strip()
        targets = ctx.get("specific_targets", [])
        targets_text = ", ".join([str(t) for t in targets]) if isinstance(targets, list) else str(targets or "").strip()
        parts = [
            f"Human Request: {human}" if human else "",
            f"Commander Core Intent: {core}" if core else "",
            f"Specific Targets: {targets_text}" if targets_text else ""
        ]
        return "\n".join([p for p in parts if p]).strip() or "General Scientific Research Acquisition"

    @staticmethod
    def get_audit_prompt(
        url: str,
        title: str,
        description: str,
        page_content: str = "",
        user_query: str = "",
        mission_context: Optional[Dict[str, Any]] = None,
        candidate_type: str = "",
        topology_score: float = 0.0
    ) -> str:
        mission_ctx = InspectorPrompt._normalize_mission_context(user_query=user_query, mission_context=mission_context)
        commander_mission = InspectorPrompt._mission_text(mission_ctx)
        candidate_type = (candidate_type or "unknown").strip()
        try:
            topology_score = float(topology_score)
        except Exception:
            topology_score = 0.0

        mission_context_json = ""
        if mission_ctx:
            # Keep only stable, compact fields to reduce token usage.
            compact_ctx = {
                "human_request": mission_ctx.get("human_request", ""),
                "commander_core_intent": mission_ctx.get("commander_core_intent", ""),
                "specific_targets": mission_ctx.get("specific_targets", []),
            }
            mission_context_json = f"""
### MISSION CONTEXT (STRUCTURED)
```json
{json.dumps(compact_ctx, ensure_ascii=False)}
```

---"""

        base_info = f"""**Target URL:** {url}
**Declared Title:** {title}
**Declared Description:** {description}
**Miner Candidate Type:** {candidate_type}
**Miner Topology Score:** {topology_score:.3f}"""

        content_context = ""
        if page_content:
            truncated_content = page_content[:3500]
            content_context = f"""
**Webpage Content Snapshot & Clues:**
```text
{truncated_content}
```"""

        prompt = f"""
### COMMANDER MISSION
"{commander_mission}"

---
{mission_context_json}

### AUDIT TARGET
{base_info}
{content_context}

---

### AUDIT PROTOCOL

#### PRIOR KNOWLEDGE (FROM MINER)
- Miner is optimized for high recall, not high precision.
- `candidate_type=asset_hint` means structure looks like a likely asset entry (weak positive prior).
- `candidate_type=exploration_target` means structure is good for deeper crawl but may be off-topic (weak negative prior for final keep decision).
- `candidate_type=entry` means root/seed page (neutral prior).
- `topology_score` indicates crawl potential only; it must NEVER override mission relevance.
- If mission relevance is weak, return SOFT_IGNORE/NOISE even when topology is excellent.

#### STEP 1: TRIAGE ACTION
Choose exactly one:

- **KEEP**: Valuable clue candidate (L1/L2/L3/L4).
- **SOFT_IGNORE**: This page is low value/noise, but domain may still be good.
- **HARD_BLACKLIST**: Domain is truly toxic/malicious/broken (e.g., spam farm, explicit scam, fake data seller, parked domain).

Rules:
1. Prefer **SOFT_IGNORE** over HARD_BLACKLIST for normal institutional domains (.gov, .edu, major org).
2. HARD_BLACKLIST requires strong evidence of domain-level toxicity, not just one bad page.

---

#### STEP 2: TIER CLASSIFICATION (STRICT)
If action is KEEP, assign exactly one of L1/L2/L3/L4.
If action is SOFT_IGNORE or HARD_BLACKLIST, level must be NOISE.

##### L1 (Hub)
- Top-level comprehensive aggregator platform.
- Must be root-level entry.
- **No virtual path as final classified URL** (root only).

##### L2 (Portal/Suite)
- Institutional portal/suite for same-origin datasets.
- Entry-level portal, not a specific sub-database.
- **No virtual path as final classified URL** (root only).

##### L3 (Sub-Database Link)
- A link to an independent sub-database entry/portal under a larger site.
- May have dedicated virtual path and independent naming/function.
- **L3 is the database link, NOT the dataset file/content itself**.
- Reject as NOISE if it is only: single article, single paper page, news post, issue list, ordinary visualization page, or file download page.

##### L4 (Physical-World Asset Clue)
- Online evidence that the actual data asset exists mainly in physical world / intranet / restricted offline workflow.
- Examples: museum/archive catalog record, collection index, finding aid, manuscript record, request-only access instruction.
- **Important**: online catalog/finding-aid links CAN be L4 if they point to physical-only or request-gated assets.
- If the page directly provides open digital datasets/download/API as main asset, do NOT classify as L4.

##### NOISE
- Single papers, blog/news posts, marketing pages, generic policy pages, search result pages, utility endpoints, pure file links, etc.

---

#### STEP 3: EVIDENCE REQUIREMENTS
When action=KEEP, provide concrete evidence:
- `has_virtual_path`: true/false (based on URL structure)
- `is_database_entry_link`: true/false
- `is_physical_asset_evidence`: true/false
- `physical_only_confidence`: 0.0-1.0

Hard constraints to obey:
1. If level is L1 or L2 -> `has_virtual_path` should be false.
2. If level is L3 -> `is_database_entry_link` must be true.
3. If level is L4 -> `is_physical_asset_evidence` must be true and confidence should be meaningful (>0.5 unless uncertain).

---

#### STEP 4: FOUR-DIMENSIONAL TAGGING
Use "N/A" for NOISE.
1. Domain
2. Data Morphology
3. Source Channel
4. Region

---

### OUTPUT (JSON ONLY)
Return ONLY one valid JSON object, no markdown wrapper.

{{
  "action": "KEEP" | "SOFT_IGNORE" | "HARD_BLACKLIST",
  "step1_kill_check": "No" | "Yes",
  "is_valid": true | false,
  "level": "L1" | "L2" | "L3" | "L4" | "NOISE",
  "score": 0.0,
  "reason": "Concrete justification with rule references.",
  "intent_analysis": "Short mission relevance analysis.",
  "content_type": "hub|portal|sub_database_link|physical_asset_clue|noise",
  "evidence_signals": {{
    "has_virtual_path": true,
    "is_database_entry_link": false,
    "is_physical_asset_evidence": false,
    "physical_only_confidence": 0.0,
    "key_phrases": ["...","..."]
  }},
  "four_dimensional_analysis": {{
    "domain": "Physics/History/Biology/Medicine/Economics/Social Science/N/A",
    "data_morphology": "Structured Database/Physical Archive Index/Raw Observation Data/Statistical Table/Map Atlas/API Hub/N/A",
    "source_channel": "Government/University/International Organization/Commercial/NGO/Private Collection/N/A",
    "region": "USA/China/Europe/Global/Australia/etc/N/A"
  }},
  "dna_patch": {{
    "add_banned_keywords": [],
    "reasoning": "Only provide when HARD_BLACKLIST evidence is strong; otherwise empty list."
  }}
}}
"""
        skill_append = get_audit_protocol_append()
        if skill_append:
            prompt = prompt.rstrip() + "\n\n---\n\n" + skill_append + "\n"
        return prompt
