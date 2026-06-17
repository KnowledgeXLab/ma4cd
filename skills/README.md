# MA4CD Skills

Domain-agnostic **rule pack loader** + per-domain **YAML instances**.

## Architecture

```
skills/
  README.md                 ← this file (framework)
  _template/                ← copy to create a new skill (not loadable)
  protein-research/         ← example instance A
  genomics-research/        ← example instance B
```

- **Engine** (`utils/skill_loader.py`, `utils/*_skill.py`): reads rule *schemas*, no domain vocabulary.
- **Instance** (`skills/<id>/rules/*.yaml`): all domain knowledge (sites, keywords, taxonomies, prompts).

Activate:

```bash
export MA4CD_SKILL=<skill-id>
python main_workflow.py --skill <skill-id> "your task"
```

## Rule pack keys (stable schema)

| Key | Purpose |
|-----|---------|
| `commander_task` | Intent, rubric, scout config, seed queries |
| `scout_search` | Site prefs, tier mix, noise rewrite, prompt append |
| `search_discovery` | Authoritative sites, L3 query templates, `default_search_type` |
| `miner_signals` | Domain keywords, negative keywords, search templates |
| `miner_heuristics` | URL pruning, link noise, evolution gates |
| `miner_evolve_domains` | Trusted / noise domain patterns |
| `miner_prompts` | Miner node `*_append` prompt blocks |
| `inspector_quality_gates` | Noise hosts/paths, trusted domains, lexicon |
| `inspector_audit` | LLM audit protocol append, thresholds |
| `inspector_fallback_audit` | Rule-only audit when LLM unavailable |
| `rejection_buckets` | Rejection explainability buckets |
| `report_taxonomy` | Five-dimension codebook + host hints |
| `curator_chain_model` | Chain dimensions, fuse rules, portal seeds |
| `curator_supplement` | Curator→Scout gap query seeds |
| `runtime_profile` | Non-overriding env defaults |

Manifest may **omit** optional keys; loader returns `{}` for missing packs.

## Create a new skill

```bash
cp -r skills/_template skills/my-domain
# Edit skills/my-domain/manifest.yaml id + description
# Fill skills/my-domain/rules/*.yaml with domain content
python main_workflow.py --skill my-domain "task"
```

## Without a skill

Pipeline uses **domain-neutral builtins** (generic data-container signals, empty authoritative site list, general search). For production domain runs, always attach a skill instance.
