"""ECharts-based interactive graph visualization."""
from __future__ import annotations

import json
from collections import deque
from typing import Optional

from financial_kg.models.graph import FinancialGraph


# ── ECharts HTML template ───────────────────────────────────────────────────
_ECHARTS_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
html, body {{ margin: 0; padding: 0; width: 100%%; height: 100%%; overflow: hidden; background: #0f172a; }}
#chart {{ width: 100%%; height: 100%%; }}
</style>
</head>
<body>
<div id="chart"></div>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>
(function() {{
  var chartDom = document.getElementById('chart');
  var myChart = echarts.init(chartDom, null, {{ renderer: 'canvas' }});
  var option = {option_json};
  myChart.setOption(option);
  window.addEventListener('resize', function() {{ myChart.resize(); }});
  {extra_js}
}})();
</script>
</body>
</html>"""


# ── Color constants ─────────────────────────────────────────────────────────
_COLORS = {
    "cell_formula": "#9E9E9E",
    "cell_value": "#BDBDBD",
    "indicator": "#42A5F5",
    "table": "#FFA726",
    "seed": "#EF5350",
    "hop1": "#FFA726",
    "hop2": "#FFD54F",
    "hop3": "#FFF9C4",
}


def _render_html(option: dict, extra_js: str = "") -> str:
    """Generate a complete ECharts HTML string."""
    option_json = json.dumps(option, ensure_ascii=False)
    return _ECHARTS_TEMPLATE.format(option_json=option_json, extra_js=extra_js)


def _hop_color(hop: int) -> str:
    if hop == 0:
        return _COLORS["seed"]
    elif hop == 1:
        return _COLORS["hop1"]
    elif hop == 2:
        return _COLORS["hop2"]
    else:
        return _COLORS["hop3"]


def _hop_size(hop: int) -> int:
    if hop == 0:
        return 22
    elif hop == 1:
        return 18
    elif hop == 2:
        return 15
    else:
        return 12


def _base_graph_option(
    nodes: list[dict],
    edges: list[dict],
    categories: list[dict] | None = None,
    large: bool = False,
) -> dict:
    """Build a standard ECharts graph series option."""
    return {
        "tooltip": {
            "show": True,
            "trigger": "item",
            "formatter": "{b}",
            "textStyle": {"color": "#e2e8f0", "fontSize": 12},
            "backgroundColor": "rgba(15,23,42,0.95)",
            "borderColor": "#334155",
            "borderWidth": 1,
        },
        "legend": {
            "show": bool(categories),
            "data": [c["name"] for c in categories] if categories else [],
            "top": 10,
            "right": 10,
            "textStyle": {"color": "#e2e8f0", "fontSize": 12},
        },
        "series": [{
            "type": "graph",
            "layout": "force",
            "roam": True,
            "draggable": True,
            "focusNodeAdjacency": True,
            "large": large,
            "largeThreshold": 200 if large else None,
            "categories": categories or [],
            "data": nodes,
            "links": edges,
            "force": {
                "repulsion": 500,
                "gravity": 0.15,
                "edgeLength": [80, 150],
                "layoutAnimation": True,
                "friction": 0.5,
            },
            "label": {
                "show": True,
                "position": "right",
                "formatter": "{b}",
                "fontSize": 10,
                "color": "#cbd5e1",
            },
            "lineStyle": {
                "color": "#475569",
                "width": 1.5,
                "curveness": 0.2,
            },
            "edgeLabel": {
                "show": False,
            },
            "emphasis": {
                "focus": "adjacency",
                "lineStyle": {"width": 3},
                "label": {"fontSize": 12, "color": "#fff"},
            },
            "edgeSymbol": ["none", "arrow"],
            "edgeSymbolSize": 8,
        }],
    }


# ── Public API ──────────────────────────────────────────────────────────────
def build_indicator_graph(
    graph: FinancialGraph,
    sheet_filter: Optional[str] = None,
    max_nodes: int = 300,
) -> str:
    """Generate ECharts HTML for Indicator + Table layer graph."""
    categories = [
        {"name": "Indicator", "itemStyle": {"color": _COLORS["indicator"]}},
        {"name": "Table", "itemStyle": {"color": _COLORS["table"]}},
    ]

    nodes: list[dict] = []
    edges: list[dict] = []
    node_count = 0
    added_tables: set[str] = set()
    added_inds: set[str] = set()

    for tbl_id, tbl in graph.tables.items():
        if sheet_filter and tbl.sheet != sheet_filter:
            continue
        if node_count >= max_nodes:
            break
        nodes.append({
            "id": tbl_id,
            "name": tbl.name[:20],
            "category": 1,
            "symbolSize": 25,
            "value": (
                f"[Table] {tbl.name}<br/>Sheet: {tbl.sheet}<br/>Type: {tbl.table_type}"
            ),
        })
        added_tables.add(tbl_id)
        node_count += 1

    for ind_id, ind in graph.indicators.items():
        if sheet_filter and ind.sheet != sheet_filter:
            continue
        if node_count >= max_nodes:
            break
        label = ind.name[:18] if ind.name else ind_id[-20:]
        val_str = f"{ind.summary_value:.2f}" if isinstance(ind.summary_value, (int, float)) else str(ind.summary_value or "")
        unit_str = f" {ind.unit}" if ind.unit else ""
        nodes.append({
            "id": ind_id,
            "name": label,
            "category": 0,
            "symbolSize": 15,
            "value": (
                f"[Indicator] {ind.name}<br/>Sheet: {ind.sheet}<br/>"
                f"Value: {val_str}{unit_str}<br/>Category: {ind.category or ''}"
            ),
        })
        added_inds.add(ind_id)
        node_count += 1

    for ind_id, ind in graph.indicators.items():
        if ind_id not in added_inds:
            continue
        for dep_id in ind.depends_on_indicators:
            if dep_id in added_inds:
                edges.append({"source": ind_id, "target": dep_id})

    for tbl_id, tbl in graph.tables.items():
        if tbl_id not in added_tables:
            continue
        for target_id in tbl.feeds_into:
            if target_id in added_tables:
                edges.append({"source": tbl_id, "target": target_id})

    option = _base_graph_option(nodes, edges, categories)
    return _render_html(option)


def build_cell_subgraph(
    graph: FinancialGraph,
    root_cell_id: str,
    depth: int = 3,
) -> str:
    """Generate ECharts HTML for cell dependency subgraph around a single cell."""
    g = graph.cell_graph
    if root_cell_id not in g:
        raise ValueError(f"Cell {root_cell_id!r} not in graph")

    neighbors: set[str] = {root_cell_id}
    frontier = {root_cell_id}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for n in frontier:
            next_frontier.update(g.predecessors(n))
            next_frontier.update(g.successors(n))
        next_frontier -= neighbors
        neighbors |= next_frontier
        frontier = next_frontier

    subg = g.subgraph(neighbors)

    nodes: list[dict] = []
    edges: list[dict] = []

    for node in subg.nodes:
        cell = graph.cells.get(node)
        is_root = node == root_cell_id
        if is_root:
            color = _COLORS["seed"]
            size = 22
        elif cell and cell.formula_raw:
            color = _COLORS["cell_formula"]
            size = 12
        else:
            color = _COLORS["cell_value"]
            size = 10

        label = node.split("_", 1)[-1] if "_" in node else node
        val = cell.value if cell else "?"
        formula = cell.formula_raw or "—" if cell else ""
        nodes.append({
            "id": node,
            "name": label,
            "symbolSize": size,
            "itemStyle": {"color": color},
            "value": f"{node}<br/>Value: {val}<br/>Formula: {formula}",
        })

    for src, dst in subg.edges:
        edges.append({"source": src, "target": dst})

    option = _base_graph_option(nodes, edges)

    extra_js = """
  myChart.on('click', function(params) {
    if (params.componentType === 'series' && params.data && params.data.id) {
      var url = new URL(window.location);
      url.searchParams.set('cell', params.data.id);
      window.location.href = url.toString();
    }
  });
"""
    return _render_html(option, extra_js=extra_js)


def build_diff_propagation_graph(
    graph: FinancialGraph,
    root_cell_id: str,
    max_hops: int = 5,
    max_nodes: int = 300,
    speed: float = 1.0,
) -> str:
    """Generate ECharts HTML with propagation animation from a single root cell.

    BFS from root_cell_id through predecessors (downstream dependents).
    Frontend depth slider filters visible nodes. Animation respects depth.
    """
    g = graph.cell_graph

    if root_cell_id not in g:
        raise ValueError(f"Root cell {root_cell_id!r} not in graph")

    COMPUTE_MAX_HOPS = max(10, max_hops)

    # BFS from single root
    visited: dict[str, int] = {root_cell_id: 0}
    queue: deque[str] = deque([root_cell_id])

    while queue:
        node = queue.popleft()
        hop = visited[node]
        if hop >= COMPUTE_MAX_HOPS:
            continue
        for pred in g.predecessors(node):
            if pred not in visited:
                cell = graph.cells.get(pred)
                if cell and cell.formula_raw:
                    visited[pred] = hop + 1
                    queue.append(pred)
        if len(visited) >= max_nodes:
            break

    subg = g.subgraph(visited)

    affected_indicators: set[str] = set()
    for cid in visited:
        cell = graph.cells.get(cid)
        if cell and cell.indicator_id:
            affected_indicators.add(cell.indicator_id)

    # ── Build nodes ─────────────────────────────────────────────────────────
    nodes: list[dict] = []

    for node in subg.nodes:
        cell = graph.cells.get(node)
        hop = visited.get(node, 0)
        ind = graph.indicators.get(cell.indicator_id) if cell and cell.indicator_id else None
        shape = "diamond" if ind else "circle"
        label = node.split("_", 1)[-1] if "_" in node else node
        title = (
            f"{'[ROOT] ' if hop == 0 else ''}{node}<br/>"
            f"Value: {cell.value if cell else '?'}<br/>"
            f"Hop: {hop}<br/>"
            f"{'Indicator: ' + ind.name + '<br/>' if ind else ''}"
            f"Formula: {cell.formula_raw or '—' if cell else ''}"
        )
        nodes.append({
            "id": node,
            "name": label,
            "symbolSize": _hop_size(hop),
            "itemStyle": {"color": _hop_color(hop)},
            "symbol": shape,
            "value": title,
            "hop": hop,
        })

    for ind_id in affected_indicators:
        ind = graph.indicators.get(ind_id)
        if ind is None:
            continue
        aff_count = sum(
            1 for cid in visited
            if graph.cells.get(cid) and graph.cells[cid].indicator_id == ind_id
        )
        nodes.append({
            "id": f"IND_{ind_id}",
            "name": ind.name[:20],
            "category": 4,
            "symbolSize": max(15, min(30, aff_count * 5)),
            "symbol": "rect",
            "itemStyle": {"color": _COLORS["indicator"]},
            "value": (
                f"[Indicator] {ind.name}<br/>Category: {ind.category or ''}<br/>"
                f"Affected cells: {aff_count}<br/>Value: {ind.summary_value}<br/>"
                f"Unit: {ind.unit or ''}"
            ),
            "hop": -1,
        })

    # ── Build edges ─────────────────────────────────────────────────────────
    edges: list[dict] = []

    for src, dst in subg.edges:
        hop_src = visited.get(src, 99)
        hop_dst = visited.get(dst, 99)
        edge_hop = max(hop_src, hop_dst)
        edges.append({
            "source": src,
            "target": dst,
            "lineStyle": {
                "color": _hop_color(edge_hop) if edge_hop <= 2 else _COLORS["hop3"],
                "width": 3 if edge_hop == 0 else 1.5,
            },
            "hop": edge_hop,
        })

    for cid in visited:
        cell = graph.cells.get(cid)
        if cell and cell.indicator_id:
            edges.append({
                "source": f"IND_{cell.indicator_id}",
                "target": cid,
                "lineStyle": {"type": "dashed", "color": _COLORS["indicator"], "width": 1},
                "hop": -1,
            })

    categories = [
        {"name": "变化源头 (Hop 0)", "itemStyle": {"color": _COLORS["seed"]}},
        {"name": "第1跳", "itemStyle": {"color": _COLORS["hop1"]}},
        {"name": "第2跳", "itemStyle": {"color": _COLORS["hop2"]}},
        {"name": "第3跳+", "itemStyle": {"color": _COLORS["hop3"]}},
        {"name": "Indicator", "itemStyle": {"color": _COLORS["indicator"]}},
    ]

    large = len(nodes) > 200
    option = _base_graph_option(nodes, edges, categories, large=large)

    # Pre-compute hop groupings — store full node/edge objects for O(1) filter
    nodes_by_hop: dict[int, list[dict]] = {}
    edges_by_hop: dict[int, list[dict]] = {}

    for n in nodes:
        hop = n.get("hop", 0)
        if hop < 0:
            continue
        nodes_by_hop.setdefault(hop, []).append(n)

    for e in edges:
        hop = e.get("hop", 0)
        if hop < 0:
            continue
        edges_by_hop.setdefault(hop, []).append(e)

    max_hop = max(nodes_by_hop.keys()) if nodes_by_hop else 0
    total_nodes = len(nodes)

    anim_data_json = json.dumps({
        "nodesByHop": nodes_by_hop,
        "edgesByHop": edges_by_hop,
        "maxHop": max_hop,
        "totalNodes": total_nodes,
    })

    extra_js = _build_animation_js(anim_data_json, speed)

    return _render_html(option, extra_js=extra_js)


def _build_animation_js(anim_data_json: str, speed: float) -> str:
    """Build the propagation animation JavaScript with depth + speed controls."""
    speed_safe = max(0.1, min(5.0, speed))
    return f"""
  var animData = {anim_data_json};
  var nodesByHop = animData.nodesByHop;
  var edgesByHop = animData.edgesByHop;
  var maxHop = animData.maxHop;
  var totalNodes = animData.totalNodes;

  // ── State ──────────────────────────────────────────────────────────
  var currentDepth = Math.min(5, maxHop);
  if (currentDepth < 1) currentDepth = 1;
  var speedMultiplier = {speed_safe};
  var animTimers = [];
  var animRunning = false;

  function clearTimers() {{
    animTimers.forEach(function(t) {{ clearTimeout(t); }});
    animTimers = [];
  }}

  // ── Depth filter: O(n) — collect from pre-grouped arrays ───────────
  function applyDepth(depth) {{
    currentDepth = depth;
    var showNodes = [];
    var showEdges = [];

    for (var hop = 0; hop <= depth; hop++) {{
      (nodesByHop[hop] || []).forEach(function(n) {{ showNodes.push(n); }});
      (edgesByHop[hop] || []).forEach(function(e) {{ showEdges.push(e); }});
    }}
    // Always show indicator summary nodes (hop=-1)
    if (nodesByHop[-1]) {{
      nodesByHop[-1].forEach(function(n) {{ showNodes.push(n); }});
    }}
    if (edgesByHop[-1]) {{
      edgesByHop[-1].forEach(function(e) {{ showEdges.push(e); }});
    }}

    myChart.setOption({{
      series: [{{ data: showNodes, links: showEdges }}],
    }});

    updateStatus();
  }}

  function updateStatus() {{
    var statusEl = document.getElementById('prop-status');
    var visibleNodes = 0;
    for (var h = 0; h <= currentDepth; h++) {{
      visibleNodes += (nodesByHop[h] || []).length;
    }}
    var indCount = (nodesByHop[-1] || []).length;
    var total = visibleNodes + indCount;
    if (statusEl) statusEl.textContent = '深度: ' + currentDepth + ' | 节点: ' + total;
  }}

  // ── Animation: highlight batch by batch ────────────────────────────
  function runAnimation() {{
    clearTimers();
    animRunning = true;

    if (currentDepth === 0 && (nodesByHop[0] || []).length > 0) {{
      if (document.getElementById('prop-status'))
        document.getElementById('prop-status').textContent = '仅源头变化';
      animRunning = false;
      return;
    }}

    var batches = [];
    for (var hop = 0; hop <= currentDepth; hop++) {{
      batches.push({{
        hop: hop,
        nodes: (nodesByHop[hop] || []).map(function(n) {{ return n.id; }}),
      }});
    }}

    var batchIdx = 0;
    function runNextBatch() {{
      if (!animRunning) return;
      if (batchIdx >= batches.length) {{
        animRunning = false;
        if (document.getElementById('prop-status'))
          document.getElementById('prop-status').textContent = '传播完成 (' + currentDepth + ' 跳)';
        return;
      }}

      var batch = batches[batchIdx];
      var pct = Math.round((batchIdx + 1) / batches.length * 100);
      var fillEl = document.getElementById('prop-progress-fill');
      var statusEl = document.getElementById('prop-status');
      if (fillEl) fillEl.style.width = pct + '%';
      if (statusEl) statusEl.textContent = '第 ' + (batch.hop) + '/' + currentDepth + ' 跳';

      batch.nodes.forEach(function(nid) {{
        myChart.dispatchAction({{ type: 'highlight', seriesIndex: 0, name: nid }});
      }});

      var hlTime = Math.max(100, 400 / speedMultiplier);
      animTimers.push(setTimeout(function() {{
        batch.nodes.forEach(function(nid) {{
          myChart.dispatchAction({{ type: 'downplay', seriesIndex: 0, name: nid }});
        }});
        batchIdx++;
        animTimers.push(setTimeout(runNextBatch, Math.max(50, 200 / speedMultiplier)));
      }}, hlTime));
    }}

    runNextBatch();
  }}

  // ── Controls UI ────────────────────────────────────────────────────
  function addControls() {{
    var existing = document.getElementById('prop-ctrl');
    if (existing) existing.remove();

    var panel = document.createElement('div');
    panel.id = 'prop-ctrl';
    panel.style.cssText = 'position:absolute;top:10px;right:10px;z-index:100;background:rgba(30,41,59,0.95);border-radius:10px;padding:10px 14px;box-shadow:0 2px 12px rgba(0,0,0,0.3);font-family:system-ui,sans-serif;font-size:13px;display:flex;gap:8px;align-items:flex-start;flex-direction:column;color:#e2e8f0;min-width:180px;';

    // Row 1: buttons
    var btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:6px;align-items:center;width:100%;';
    btnRow.innerHTML = '<button id="prop-replay" style="background:#22c55e;color:#fff;border:none;border-radius:6px;padding:5px 10px;cursor:pointer;font-weight:500;font-size:12px;flex:1;">▶ 播放</button><button id="prop-fs" style="background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px;">⛶</button>';
    panel.appendChild(btnRow);

    // Row 2: depth slider
    var depthRow = document.createElement('div');
    depthRow.style.cssText = 'display:flex;gap:6px;align-items:center;width:100%;font-size:12px;';
    depthRow.innerHTML = '<span style="white-space:nowrap;color:#94a3b8;">深度</span><input id="prop-depth" type="range" min="1" max="' + Math.max(maxHop, 1) + '" value="' + currentDepth + '" style="flex:1;accent-color:#22c55e;"><span id="prop-depth-val" style="color:#22c55e;font-weight:600;min-width:20px;text-align:center;">' + currentDepth + '</span>';
    panel.appendChild(depthRow);

    // Row 3: speed slider
    var speedRow = document.createElement('div');
    speedRow.style.cssText = 'display:flex;gap:6px;align-items:center;width:100%;font-size:12px;';
    speedRow.innerHTML = '<span style="white-space:nowrap;color:#94a3b8;">速度</span><input id="prop-speed" type="range" min="1" max="50" value="' + Math.round({speed_safe} * 10) + '" style="flex:1;accent-color:#f59e0b;"><span id="prop-speed-val" style="color:#f59e0b;font-weight:600;min-width:30px;text-align:center;">' + {speed_safe} + 'x</span>';
    panel.appendChild(speedRow);

    // Row 4: status + progress
    var infoEl = document.createElement('div');
    infoEl.id = 'prop-info';
    infoEl.style.cssText = 'text-align:center;color:#94a3b8;font-size:11px;';
    infoEl.textContent = '共 ' + totalNodes + ' 个节点';
    panel.appendChild(infoEl);

    var statusEl = document.createElement('div');
    statusEl.id = 'prop-status';
    statusEl.style.cssText = 'text-align:center;color:#94a3b8;font-size:12px;';
    statusEl.textContent = '稳定后开始...';
    panel.appendChild(statusEl);

    var progressBar = document.createElement('div');
    progressBar.style.cssText = 'width:100%;height:4px;background:#1e293b;border-radius:2px;overflow:hidden;';
    progressBar.innerHTML = '<div id="prop-progress-fill" style="width:0%;height:100%;background:#22c55e;transition:width 0.3s;"></div>';
    panel.appendChild(progressBar);

    document.getElementById('chart').parentElement.appendChild(panel);

    // ── Event bindings ─────────────────────────────────────────────
    document.getElementById('prop-replay').addEventListener('click', function() {{
      clearTimers();
      animRunning = false;
      document.getElementById('prop-progress-fill').style.width = '0%';
      runAnimation();
    }});

    document.getElementById('prop-fs').addEventListener('click', function() {{
      var el = document.documentElement;
      if (!document.fullscreenElement) {{ el.requestFullscreen().catch(function(){{}}); }}
      else {{ document.exitFullscreen().catch(function(){{}}); }}
    }});

    document.getElementById('prop-depth').addEventListener('input', function() {{
      var depth = parseInt(this.value);
      document.getElementById('prop-depth-val').textContent = depth;
      applyDepth(depth);
    }});

    document.getElementById('prop-speed').addEventListener('input', function() {{
      speedMultiplier = parseInt(this.value) / 10;
      document.getElementById('prop-speed-val').textContent = speedMultiplier.toFixed(1) + 'x';
    }});
  }}

  addControls();
  // Initial render at currentDepth
  applyDepth(currentDepth);
  setTimeout(function() {{ runAnimation(); }}, 1500);
"""
