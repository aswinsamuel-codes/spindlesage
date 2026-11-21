# Maintenance knowledge base

The documents in `maintenance/` are **illustrative**. They were written for the SpindleSage simulated CNC cell to give the agent something realistic to retrieve and cite. They are not taken from any machine manufacturer, they are not validated maintenance procedures, and they must not be used to maintain real equipment.

For a real deployment, replace them with the plant's own approved manuals, work instructions and safety procedures.

## Format

Each file is Markdown with a small front-matter block:

```
---
id: spindle-thermal
title: Spindle thermal problems
applies_to: cnc-sim-*
---
```

Each `## ` section becomes one retrievable chunk, cited as `<id>#<section-slug>`.
