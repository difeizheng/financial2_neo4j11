# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Financial model knowledge graph system. Parses Excel financial models (e.g., pumped-storage hydroelectric project models) into a three-layer knowledge graph (Cell → Indicator → Table), stores in Neo4j, supports incremental recalculation, snapshot comparison, and LLM-powered Q&A. Built with Streamlit as the UI frontend.

## Tech Stack

- **Python 3.10+** with type annotations
- **Streamlit** — web UI
- **NetworkX** — in-memory cell dependency graph (DiGraph)
- **Neo4j 5.x** — persistent graph storage (Community Edition compatible)
- **OpenAI-compatible LLM API** — Q&A Cypher generation and answer synthesis
- **openpyxl** — Excel parsing
- **formulas** — formula evaluation
- **SQLite** — task history tracking (`tasks.db`)
- **pyvis/vis-network** — graph visualization

## Directory Structure

```
main.py                          # Streamlit entry point
parse_excel.py                   # CLI: parse Excel → JSON (3-layer graph)
pages/
  01_upload.py                   # Upload, parse, import to Neo4j
  02_explorer.py                 # Interactive graph explorer
  03_recalc.py                   # Parameter recalculation UI
  04_compare.py                  # Snapshot comparison
  05_qa.py                       # LLM-powered Q&A
financial_kg/
  config.py                      # Env loading, path config, save_config()
  models/
    cell.py                      # Cell, CellData dataclasses
    indicator.py                 # Indicator dataclass
    table.py                     # Table dataclass
    graph.py                     # FinancialGraph — container for all 3 layers
  parser/
    excel_reader.py              # Read Excel → raw cell list per sheet
    cell_extractor.py            # Build cell graph from raw cells
    formula_parser.py            # Parse Excel formula strings → dependency edges
    indicator_builder.py         # Detect indicators from header patterns
    table_detector.py            # Detect logical tables in sheets
    relationship_builder.py      # Infer FEEDS_INTO relationships between tables
    reference_resolver.py        # Resolve cross-sheet cell references
  engine/
    dependency.py                # Topological sort, downstream BFS
    evaluator.py                 # Evaluate cell formulas via `formulas` lib
    recalculator.py              # Incremental recalculation engine
    snapshot.py                  # Snapshot create/load/diff
  storage/
    json_store.py                # Save/load graph to JSON files
    neo4j_store.py               # Neo4j import/query with task_id scoping
    task_db.py                   # SQLite task history (TaskDB)
  llm/
    qa_engine.py                 # Q&A orchestration: retrieval → Cypher → LLM
    retriever.py                 # Indicator retrieval (keyword + graph traversal)
    prompt_builder.py            # System prompt construction
    cypher_gen.py                # LLM Cypher query generation
  viz/
    graph_viz.py                 # Pyvis graph visualization
output/                          # Parsed JSON files (cells, indicators, tables)
financial_kg/data/snapshots/     # Saved value snapshots for diffing
lib/                             # Vendored JS assets (vis-network, tom-select)
```

## Three-Layer Architecture

### Layer 1: Cell Graph
- Each Excel cell becomes a `Cell` node with `{sheet}_{row}_{col}` ID
- `DEPENDS_ON` edges derived from parsed formulas (direction: A depends on B means A → B)
- Stored as `networkx.DiGraph` in memory, `Cell` nodes in Neo4j

### Layer 2: Indicators
- Business-level line items (e.g., "营业收入", "净利润") detected from row headers
- Each indicator maps to one or more cells, carries `time_series` dict, `summary_value`, `category`
- `CALCULATES_FROM` edges show indicator-level dependencies

### Layer 3: Tables
- Logical tables detected from sheet structure (income statement, balance sheet, etc.)
- `FEEDS_INTO` edges show cross-table data flow
- `BELONGS_TO` edges: Cell → Indicator, Indicator → Table

## Key Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run Streamlit app
streamlit run main.py

# Parse Excel to JSON (CLI)
python parse_excel.py <excel_file> [--output-dir output] [--task-id v15]

# Load a specific model for exploration (in Python)
from financial_kg.storage.json_store import load_graph
graph = load_graph("output/v15_cells.json")
print(graph.stats())
```

## Configuration

Environment variables in `.env` (copy from `.env.example`):
- `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` — OpenAI-compatible API
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` — Neo4j connection

Config can also be set via the Streamlit upload page (saves to `.env`).

## Important Conventions

- **Task ID scoping**: All Neo4j nodes are prefixed with `{task_id}_` to isolate multiple models in one database. Always include `task_id` in queries.
- **Edge direction**: `A → B` means "A depends on B". To find what depends on B, traverse predecessors (not successors). See `engine/dependency.py:43-45`.
- **Immutable data preferred**: Models use `@dataclass` with explicit field defaults. Recalculation returns a `RecalcResult` rather than mutating silently.
- **No `__init__.py` in `financial_kg/` root**: The package uses implicit namespace. Sub-packages (`models/`, `parser/`, etc.) each have `__init__.py`.
- **Python path manipulation**: Streamlit pages and `parse_excel.py` insert project root into `sys.path` — this is required for `financial_kg.*` imports to resolve.
- **Formulas library**: Uses the `formulas` Python package for Excel formula evaluation, not a custom evaluator.
- **Data directory**: `financial_kg/config.py` defines `DATA_DIR = financial_kg/data/` as the base for `tasks.db` and snapshots. The root-level `snapshots/` and `tasks.db` are legacy; active files live under `financial_kg/data/`.
- **Python version**: Requires Python 3.10+ (uses `str | None` union type syntax).

## Neo4j Schema

Nodes: `Cell`, `Indicator`, `Table` (all with `id` UNIQUE constraint, `task_id` indexed)
Relationships: `DEPENDS_ON` (Cell→Cell), `CALCULATES_FROM` (Indicator→Indicator), `FEEDS_INTO` (Table→Table), `BELONGS_TO` (Cell→Indicator, Indicator→Table)

Community Edition compatible — uses UNIQUE constraints, not NODE KEY.

## Testing

Project uses `pytest`. No test files currently exist. When adding tests:

```bash
pip install pytest
pytest --cov=financial_kg --cov-report=term-missing
```
