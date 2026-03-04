---
name: sourcemap-guide
description: "Use when the user asks about SourceMap itself — available tools, how to query the knowledge graph, MCP resources, graph schema, or workflow reference. Examples: \"What SourceMap tools are available?\", \"How do I use SourceMap?\""
---

# SourceMap Guide

Quick reference for all SourceMap MCP tools, resources, and the knowledge graph schema.

## Always Start Here

For any task involving code understanding, debugging, impact analysis, or refactoring:

1. **Read `sourcemap://repo/{name}/context`** — codebase overview + check index freshness
2. **Match your task to a skill below** and **read that skill file**
3. **Follow the skill's workflow and checklist**

> If step 1 warns the index is stale, run `npx sourcemap analyze` in the terminal first.

## Skills

| Task                                         | Skill to read       |
| -------------------------------------------- | ------------------- |
| Understand architecture / "How does X work?" | `sourcemap-exploring`         |
| Blast radius / "What breaks if I change X?"  | `sourcemap-impact-analysis`   |
| Trace bugs / "Why is X failing?"             | `sourcemap-debugging`         |
| Rename / extract / split / refactor          | `sourcemap-refactoring`       |
| Tools, resources, schema reference           | `sourcemap-guide` (this file) |
| Index, status, clean, wiki CLI commands      | `sourcemap-cli`               |

## Tools Reference

| Tool             | What it gives you                                                        |
| ---------------- | ------------------------------------------------------------------------ |
| `query`          | Process-grouped code intelligence — execution flows related to a concept |
| `context`        | 360-degree symbol view — categorized refs, processes it participates in  |
| `impact`         | Symbol blast radius — what breaks at depth 1/2/3 with confidence         |
| `detect_changes` | Git-diff impact — what do your current changes affect                    |
| `rename`         | Multi-file coordinated rename with confidence-tagged edits               |
| `cypher`         | Raw graph queries (read `sourcemap://repo/{name}/schema` first)           |
| `list_repos`     | Discover indexed repos                                                   |

## Resources Reference

Lightweight reads (~100-500 tokens) for navigation:

| Resource                                       | Content                                   |
| ---------------------------------------------- | ----------------------------------------- |
| `sourcemap://repo/{name}/context`               | Stats, staleness check                    |
| `sourcemap://repo/{name}/clusters`              | All functional areas with cohesion scores |
| `sourcemap://repo/{name}/cluster/{clusterName}` | Area members                              |
| `sourcemap://repo/{name}/processes`             | All execution flows                       |
| `sourcemap://repo/{name}/process/{processName}` | Step-by-step trace                        |
| `sourcemap://repo/{name}/schema`                | Graph schema for Cypher                   |

## Graph Schema

**Nodes:** File, Function, Class, Interface, Method, Community, Process
**Edges (via CodeRelation.type):** CALLS, IMPORTS, EXTENDS, IMPLEMENTS, DEFINES, MEMBER_OF, STEP_IN_PROCESS

```cypher
MATCH (caller)-[:CodeRelation {type: 'CALLS'}]->(f:Function {name: "myFunc"})
RETURN caller.name, caller.filePath
```
