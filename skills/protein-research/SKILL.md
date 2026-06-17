# Protein Research Skill (instance)

MA4CD skill **instance** for protein data source discovery.  
Uses the generic rule-pack schema — see [skills/README.md](../README.md).

## Activate

```bash
python main_workflow.py --skill protein-research "寻找蛋白质研究数据"
```

Domain-specific content (UniProt, PDB, PRIDE, …) lives only under `rules/`, not in engine code.

## Rule packs

Same 15 keys as documented in `skills/README.md`; values in this directory are tuned for protein research.
