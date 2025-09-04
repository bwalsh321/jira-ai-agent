# agents/planner.py
from typing import Literal, List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator

Intent = Literal[
    "create_custom_field",
    "provision_field_to_screen",
    "update_workflow",
    "create_jsm_form",
    "governance_preflight_only",
    "other"
]

class PlanStep(BaseModel):
    agent: Literal["admin_validator", "governance_bot", "pm_enhancer"]
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)

class Plan(BaseModel):
    intent: Intent
    confidence: float
    require_governance: bool = True
    artifacts: Dict[str, Any] = Field(default_factory=dict)  # e.g., {"screen_id": "...", "workflow": "..."}
    steps: List[PlanStep] = Field(default_factory=list)
    notes: Optional[str] = None

    @validator("confidence")
    def _conf_range(cls, v):  # guard against bad LLM output
        return max(0.0, min(1.0, float(v)))

def classify_with_rules(issue: dict) -> Optional[Plan]:
    summary = (issue.get("fields", {}).get("summary") or "").lower()
    desc = (issue.get("fields", {}).get("description") or "").lower()
    labels = [l.lower() for l in (issue.get("fields", {}).get("labels") or [])]

    # Hard overrides by label
    for lb in labels:
        if lb.startswith("mode:"):
            mode = lb.split(":",1)[1]
            if mode == "pm":  return Plan(intent="create_jsm_form", confidence=0.99, steps=[])
            if mode == "admin": return Plan(intent="create_custom_field", confidence=0.99, steps=[])
            if mode == "gov": return Plan(intent="governance_preflight_only", confidence=0.99, steps=[])

    # Quick heuristics
    if "custom field" in summary or "create field" in desc:
        return Plan(intent="create_custom_field", confidence=0.8, steps=[])
    if "workflow" in summary or "transition" in desc:
        return Plan(intent="update_workflow", confidence=0.75, steps=[])
    if "form" in summary or "request form" in desc or "jsm" in desc:
        return Plan(intent="create_jsm_form", confidence=0.8, steps=[])
    return None

def build_llm_plan(llm, issue: dict) -> Plan:
    """
    Ask your big model to produce a JSON Plan (Plan schema).
    Return Plan; on parse error, return Plan(intent="other", confidence=0, steps=[]).
    """
    prompt = f"""You are the Planner. Read this Jira issue and output ONE JSON object matching schema:
{Plan.schema_json(indent=2)}
Issue (compact): {{"summary": "{issue.get('fields',{}).get('summary','')}", "description": "...", "labels": {issue.get('fields',{}).get('labels',[])}}}
Rules:
- Choose the most likely intent.
- Confidence 0..1.
- If mutating Screens/Workflows/Field Configs, set require_governance=true and include a first step 'governance_bot' with action 'preflight'.
- Steps should be concrete and minimal. Example for create field + provision:
  [{{"agent":"admin_validator","action":"create_custom_field","params":{{"name":"...","type":"select"}}}},
   {{"agent":"governance_bot","action":"screen_preflight","params":{{"screen_id":"..."}}}},
   {{"agent":"admin_validator","action":"provision_field_to_screen","params":{{"field_id":"...","screen_id":"...","tab_id":"Main"}}}}]
Only output JSON."""
    text = llm.generate(prompt)  # your existing LLM call
    plan = None
    try:
        import json, re
        match = re.search(r"\{.*\}\s*$", text, flags=re.S)
        plan = Plan.parse_obj(json.loads(match.group(0)) if match else {})
    except Exception:
        plan = Plan(intent="other", confidence=0.0, steps=[], notes="Planner parse error")
    return plan

def plan(issue: dict, llm) -> Plan:
    p = classify_with_rules(issue)
    if p:  # fill default step for common intents
        if p.intent == "create_custom_field":
            p.steps = [PlanStep(agent="admin_validator", action="create_custom_field")]
        elif p.intent == "update_workflow":
            p.steps = [PlanStep(agent="governance_bot", action="workflow_preflight"),
                       PlanStep(agent="governance_bot", action="update_workflow")]
        elif p.intent == "create_jsm_form":
            p.steps = [PlanStep(agent="pm_enhancer", action="create_jsm_form")]
        return p
    # Ask the model for a richer plan
    return build_llm_plan(llm, issue)
