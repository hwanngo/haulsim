# Documentation

Architecture and design references plus technical specifications and algorithms
for the simulation files the backend generates from telemetry. Every doc uses the
same style: a single `# Title`, an `## Overview`, a numbered `## Table of Contents`,
and numbered `## N.` / `### N.M` sections. (Filenames use `snake_case`.)

| Document | Describes |
|----------|-----------|
| [application_architecture.md](application_architecture.md) | End-to-end **architecture and business logic** — system design, import/export flows, cycle/zone/road detection, loss analysis, API, and validations. |
| [design_system.md](design_system.md) | The **"CAT" design system** — tokens, colors, typography, layout, and components behind the frontend (`frontend/src/system.ts`). |
| [model_structure.md](model_structure.md) | Structure/schema of the generated road-network **model** file (nodes, roads, zones, routes, machines). |
| [model_generation_algorithm.md](model_generation_algorithm.md) | How the model is built from trajectories — road detection, node dedup, zone (load/dump) classification. |
| [des_inputs_specification.md](des_inputs_specification.md) | Structure of the **DES inputs** file (discrete-event simulation configuration). |
| [events_structure_specification.md](events_structure_specification.md) | Structure/schema of the **events ledger** file. |
| [event_generation_algorithm.md](event_generation_algorithm.md) | How events are generated from GPS telemetry (node matching, idle/load/dump events). |

For setup, running, and the API, see the [project README](../README.md).
