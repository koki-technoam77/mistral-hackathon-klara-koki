"""
Synthetic Training Data Generator for AI Agency
-----------------------------------------------
Generates realistic Natalie-AI conversations that end with workflow JSON.
Uses Mistral Large to create diverse training examples.

Output:
    training_data.jsonl   - for fine-tuning
    eval_data.jsonl       - held-out eval set (10%)
"""

import json
import os
import random

# Load .env file from project root (works wherever you run the script from)
try:
    from dotenv import load_dotenv
    # Walk up directories to find .env
    current = os.path.abspath(__file__)
    for _ in range(4):  # search up to 4 levels up
        current = os.path.dirname(current)
        env_path = os.path.join(current, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            print(f"✅ Loaded .env from {env_path}")
            break
except ImportError:
    print("⚠ python-dotenv not installed. Run: pip install python-dotenv")
import time
from tqdm import tqdm
from mistralai import Mistral
import wandb

# ── Config ────────────────────────────────────────────────────────────────────

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
WANDB_API_KEY   = os.environ.get("WANDB_API_KEY")

# Validate keys before doing anything
if not MISTRAL_API_KEY:
    raise EnvironmentError("❌ MISTRAL_API_KEY not found. Check your .env file.")
if not WANDB_API_KEY:
    raise EnvironmentError("❌ WANDB_API_KEY not found. Check your .env file.")
print(f"🔑 Mistral key loaded: {MISTRAL_API_KEY[:8]}...")
print(f"🔑 W&B key loaded:     {WANDB_API_KEY[:8]}...")
GENERATOR_MODEL = "mistral-large-latest"
NUM_EXAMPLES    = 120   # generates 120 → ~108 train / ~12 eval
OUTPUT_TRAIN    = "training_data.jsonl"
OUTPUT_EVAL     = "eval_data.jsonl"

client = Mistral(api_key=MISTRAL_API_KEY)

# ── Workflow JSON Schema (injected into every prompt so model stays consistent)

SCHEMA_REFERENCE = """
The workflow JSON must follow this EXACT schema:

{
  "workflow_id": "wf_<8-char-random-string>",
  "name": "<short human-readable name>",
  "description": "<one sentence describing what this does>",
  "created_from_transcript": true,

  "trigger": {
    "type": "<email_received | manual>",
    "config": {
      // for email_received:
      "from_filter": "<email or domain, or null>",
      "subject_filter": "<keyword, or null>",
      "match": "<contains | exact | null>"
      // for manual: config can be {}
    }
  },

  "steps": [
    {
      "id": "step_<N>",
      "name": "<human-readable step name>",
      "action": "<one of the 7 allowed actions below>",
      "config": { ... },           // action-specific config
      "output_variable": "<name>"  // optional, only when step produces data
    }
  ],

  "meta": {
    "estimated_time_saved_minutes": <integer>,
    "runs": 0,
    "last_run": null,
    "status": "active"
  }
}

ALLOWED ACTIONS (only these 7, no others):
1. gmail.read_email     → config: { extract_fields: [...] }
2. gmail.send_email     → config: { to, subject, body }
3. gmail.search_emails  → config: { query, max_results }
4. sheets.read_rows     → config: { spreadsheet_id, sheet_name, range }
5. sheets.append_row    → config: { spreadsheet_id, sheet_name, row_data: [...] }
6. sheets.update_cell   → config: { spreadsheet_id, sheet_name, cell, value }
7. condition            → config: { if: "{{var}} <operator> <value>", then: "step_N", else: "step_N" }

VARIABLE SYNTAX: Use {{variable_name}} to reference outputs from previous steps.
Special variables always available: {{workflow.run_timestamp}}, {{user.email}}, {{user.spreadsheet_id}}
"""

# ── Scenario Seeds ─────────────────────────────────────────────────────────────
# Each seed has a topic + variations to ensure diversity across 120 examples

SCENARIO_SEEDS = [

    # SCENARIO A — Email → Extract → Log to Sheet
    {
        "scenario_id": "A",
        "topic": "email_to_sheet",
        "persona_variants": [
            "Natalie works in accounting and receives supplier invoices",
            "Natalie is an office manager tracking client enquiries",
            "Natalie is in HR and receives job applications by email",
            "Natalie manages a small team and gets expense reports by email",
            "Natalie is in sales ops and receives order confirmations",
        ],
        "pain_variants": [
            "she manually copies sender, subject and amount into a spreadsheet every time",
            "she opens each email, highlights key info, and types it into a tracker sheet",
            "she spends 30 minutes each morning logging emails into a Google Sheet",
            "she has to remember to check her inbox and update the sheet before end of day",
        ],
    },

    # SCENARIO B — Spreadsheet Updated → Email Summary to Manager
    {
        "scenario_id": "B",
        "topic": "sheet_to_email",
        "persona_variants": [
            "Natalie compiles a weekly sales summary from a shared spreadsheet",
            "Natalie sends a monthly budget report to her director",
            "Natalie emails the team a recap of new entries added that week",
            "Natalie sends Friday end-of-week stats to her manager",
            "Natalie compiles overdue invoices from a sheet and emails the finance team",
        ],
        "pain_variants": [
            "she manually reads the spreadsheet, copies the numbers, and writes the email herself",
            "she spends an hour every Friday formatting a summary to send to management",
            "she always forgets to send the report on time",
            "she finds it tedious to format the same email template with new numbers each week",
        ],
    },

    # SCENARIO C — Email Trigger → Condition → Auto-Reply or Forward
    {
        "scenario_id": "C",
        "topic": "email_triage",
        "persona_variants": [
            "Natalie handles customer support emails and routes them based on urgency",
            "Natalie receives supplier emails and needs to auto-confirm receipt",
            "Natalie gets contractor invoices and routes them to the right person",
            "Natalie manages an info@ inbox and forwards emails to the right department",
            "Natalie receives client feedback emails and auto-acknowledges them",
        ],
        "pain_variants": [
            "she manually reads each email and decides whether to reply or forward it",
            "she copies and pastes the same acknowledgement reply dozens of times a week",
            "important emails sometimes sit unread for hours because she's in meetings",
            "she has to check her inbox constantly to make sure nothing urgent is missed",
        ],
    },
]

# ── Prompt Builder ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are generating synthetic training data for an AI fine-tuning project.

Your task: generate a realistic voice conversation transcript between Natalie (a non-technical office worker) 
and an AI assistant called Aria. Then output the workflow JSON that Aria would generate at the end.

CONVERSATION RULES:
- Natalie speaks naturally, uses everyday language, never says "trigger" or "node" or technical terms
- Aria asks between 3 and 5 follow-up questions to gather all necessary details before generating the workflow
- Questions should feel natural, conversational, empathetic — like a smart colleague, not a form
- Aria confirms understanding before generating ("Let me make sure I've got this right...")
- The conversation should feel complete — all info needed for the workflow is collected

OUTPUT FORMAT:
Return a JSON object with exactly two keys:
{{
  "conversation": [
    {{"role": "Natalie", "content": "..."}},
    {{"role": "aria",   "content": "..."}},
    ...
  ],
  "workflow": {{ ...workflow JSON following the schema below... }}
}}

Return ONLY valid JSON. No markdown, no backticks, no explanation outside the JSON.

{SCHEMA_REFERENCE}
"""

def build_user_prompt(seed: dict) -> str:
    persona = random.choice(seed["persona_variants"])
    pain    = random.choice(seed["pain_variants"])
    
    return f"""Generate a training example for scenario type: {seed['topic']}

Natalie's situation: {persona}
Her current pain: {pain}

Make the conversation feel unique — vary the tone, the number of follow-up questions (3-5), 
and the specific details Natalie mentions. The workflow JSON must accurately reflect 
exactly what was discussed in the conversation.
"""

# ── Generator ──────────────────────────────────────────────────────────────────

def generate_example(seed: dict, attempt: int = 0) -> dict | None:
    """Call Mistral Large to generate one training example."""
    if attempt > 2:
        return None
    
    try:
        response = client.chat.complete(
            model=GENERATOR_MODEL,
            messages=[
                {"role": "system",  "content": SYSTEM_PROMPT},
                {"role": "user",    "content": build_user_prompt(seed)},
            ],
            temperature=0.9,       # high diversity across examples
            max_tokens=2500,
            response_format={"type": "json_object"},
        )
        
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        
        # Basic validation
        assert "conversation" in parsed, "Missing 'conversation' key"
        assert "workflow"     in parsed, "Missing 'workflow' key"
        assert len(parsed["conversation"]) >= 6, "Conversation too short (need ≥3 exchanges)"
        assert "steps"   in parsed["workflow"], "Workflow missing 'steps'"
        assert "trigger" in parsed["workflow"], "Workflow missing 'trigger'"
        
        return parsed
    
    except (json.JSONDecodeError, AssertionError, KeyError) as e:
        print(f"  ⚠ Validation failed ({e}), retrying...")
        time.sleep(1)
        return generate_example(seed, attempt + 1)
    except Exception as e:
        print(f"  ✗ API error: {e}")
        time.sleep(3)
        return generate_example(seed, attempt + 1)


def to_jsonl_row(example: dict) -> str:
    """
    Convert a generated example into the JSONL format Mistral fine-tuning expects.
    
    The fine-tuning task: given a conversation transcript, output the workflow JSON.
    Input  = full conversation as a single formatted string
    Output = workflow JSON string
    """
    # Format the conversation transcript as a readable string
    transcript_lines = []
    for turn in example["conversation"]:
        speaker = "Natalie" if turn["role"] == "Natalie" else "Aria (AI)"
        transcript_lines.append(f"{speaker}: {turn['content']}")
    transcript = "\n".join(transcript_lines)
    
    workflow_str = json.dumps(example["workflow"], indent=2)
    
    row = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert workflow automation builder. "
                    "Given a conversation transcript between a user and an AI assistant, "
                    "output a valid workflow JSON that automates the task described. "
                    "Output only valid JSON, nothing else."
                )
            },
            {
                "role": "user",
                "content": f"Here is the conversation transcript:\n\n{transcript}\n\nGenerate the workflow JSON."
            },
            {
                "role": "assistant",
                "content": workflow_str
            }
        ]
    }
    return json.dumps(row)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("🚀 AI Agency — Synthetic Training Data Generator")
    print(f"   Generating {NUM_EXAMPLES} examples using {GENERATOR_MODEL}\n")

    # Init W&B run to track data generation
    wandb.init(
        project="ai-agency-finetune",
        name="data-generation",
        config={
            "generator_model": GENERATOR_MODEL,
            "num_examples": NUM_EXAMPLES,
            "scenarios": ["email_to_sheet", "sheet_to_email", "email_triage"],
        }
    )

    examples = []
    failed   = 0

    # Distribute evenly across 3 scenarios
    scenario_pool = SCENARIO_SEEDS * (NUM_EXAMPLES // len(SCENARIO_SEEDS) + 1)
    random.shuffle(scenario_pool)
    scenario_pool = scenario_pool[:NUM_EXAMPLES]

    for i, seed in enumerate(tqdm(scenario_pool, desc="Generating")):
        result = generate_example(seed)
        
        if result:
            result["_scenario"] = seed["scenario_id"]
            examples.append(result)
            
            # Log progress to W&B
            wandb.log({
                "examples_generated": len(examples),
                "failed": failed,
                "scenario_A": sum(1 for e in examples if e["_scenario"] == "A"),
                "scenario_B": sum(1 for e in examples if e["_scenario"] == "B"),
                "scenario_C": sum(1 for e in examples if e["_scenario"] == "C"),
            })
        else:
            failed += 1
            print(f"  ✗ Failed example {i+1}, skipping")

        # Gentle rate limiting
        time.sleep(0.5)

    print(f"\n✅ Generated {len(examples)} examples ({failed} failed)\n")

    # Split 90/10 train/eval
    random.shuffle(examples)
    split       = int(len(examples) * 0.9)
    train_set   = examples[:split]
    eval_set    = examples[split:]

    # Write JSONL files
    with open(OUTPUT_TRAIN, "w") as f:
        for ex in train_set:
            f.write(to_jsonl_row(ex) + "\n")

    with open(OUTPUT_EVAL, "w") as f:
        for ex in eval_set:
            f.write(to_jsonl_row(ex) + "\n")

    print(f"📁 training_data.jsonl → {len(train_set)} examples")
    print(f"📁 eval_data.jsonl     → {len(eval_set)} examples")

    # Log final dataset stats to W&B
    wandb.log({
        "total_generated":  len(examples),
        "train_size":       len(train_set),
        "eval_size":        len(eval_set),
        "failure_rate":     failed / NUM_EXAMPLES,
    })

    # Save raw examples as W&B artifact for reproducibility
    artifact = wandb.Artifact("training-dataset", type="dataset")
    artifact.add_file(OUTPUT_TRAIN)
    artifact.add_file(OUTPUT_EVAL)
    wandb.log_artifact(artifact)

    print("\n📊 Dataset logged to W&B as artifact 'training-dataset'")
    print("   View at: https://wandb.ai/your-project/ai-agency-finetune\n")

    wandb.finish()
    print("✨ Done! Next step: run finetune_job.py to kick off training.")


if __name__ == "__main__":
    main()