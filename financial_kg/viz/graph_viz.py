"""pyvis-based interactive graph visualization."""
from __future__ import annotations
import os
import tempfile
from collections import deque
from typing import Optional

from financial_kg.models.graph import FinancialGraph

try:
    from pyvis.network import Network
    _PYVIS_AVAILABLE = True
except ImportError:
    _PYVIS_AVAILABLE = False


# Node/edge color palette
_COLORS = {
    "cell_formula": "#9E9E9E",
    "cell_value": "#BDBDBD",
    "indicator": "#42A5F5",
    "table": "#FFA726",
    "edge_depends": "#CFD8DC",
    "edge_calculates": "#42A5F5",
    "edge_feeds": "#FFA726",
}


def build_indicator_graph(
    graph: FinancialGraph,
    sheet_filter: Optional[str] = None,
    max_nodes: int = 300,
    output_path: Optional[str] = None,
) -> str:
    """Build a pyvis HTML showing Indicator + Table layers.

    Returns the path to the generated HTML file.
    """
    if not _PYVIS_AVAILABLE:
        raise ImportError("pyvis is not installed. Run: pip install pyvis")

    net = Network(height="700px", width="100%", directed=True, notebook=False)
    net.set_options("""
    {
      "physics": {"stabilization": {"iterations": 100}},
      "edges": {"arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}},
      "interaction": {"hover": true, "navigationButtons": true}
    }
    """)

    added_inds: set[str] = set()
    added_tables: set[str] = set()
    node_count = 0

    # Add Table nodes
    for tbl_id, tbl in graph.tables.items():
        if sheet_filter and tbl.sheet != sheet_filter:
            continue
        if node_count >= max_nodes:
            break
        net.add_node(
            tbl_id,
            label=tbl.name[:20],
            title=f"[Table] {tbl.name}\nSheet: {tbl.sheet}\nType: {tbl.table_type}",
            color=_COLORS["table"],
            shape="box",
            size=25,
        )
        added_tables.add(tbl_id)
        node_count += 1

    # Add Indicator nodes
    for ind_id, ind in graph.indicators.items():
        if sheet_filter and ind.sheet != sheet_filter:
            continue
        if node_count >= max_nodes:
            break
        label = ind.name[:18] if ind.name else ind_id[-20:]
        val_str = f"{ind.summary_value:.2f}" if isinstance(ind.summary_value, float) else str(ind.summary_value or "")
        unit_str = f" {ind.unit}" if ind.unit else ""
        net.add_node(
            ind_id,
            label=label,
            title=f"[Indicator] {ind.name}\nSheet: {ind.sheet}\nValue: {val_str}{unit_str}\nCategory: {ind.category or ''}",
            color=_COLORS["indicator"],
            shape="ellipse",
            size=15,
        )
        added_inds.add(ind_id)
        node_count += 1

    # CALCULATES_FROM edges (Indicator → Indicator)
    for ind_id, ind in graph.indicators.items():
        if ind_id not in added_inds:
            continue
        for dep_id in ind.depends_on_indicators:
            if dep_id in added_inds:
                net.add_edge(ind_id, dep_id, color=_COLORS["edge_calculates"], width=1.5)

    # FEEDS_INTO edges (Table → Table)
    for tbl_id, tbl in graph.tables.items():
        if tbl_id not in added_tables:
            continue
        for target_id in tbl.feeds_into:
            if target_id in added_tables:
                net.add_edge(tbl_id, target_id, color=_COLORS["edge_feeds"], width=2)

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".html", prefix="kg_viz_")
        os.close(fd)

    net.save_graph(output_path)
    return output_path


def build_cell_subgraph(
    graph: FinancialGraph,
    root_cell_id: str,
    depth: int = 3,
    output_path: Optional[str] = None,
) -> str:
    """Build a pyvis HTML showing the dependency subgraph around a single cell."""
    if not _PYVIS_AVAILABLE:
        raise ImportError("pyvis is not installed.")

    import networkx as nx

    g = graph.cell_graph
    if root_cell_id not in g:
        raise ValueError(f"Cell {root_cell_id!r} not in graph")

    # BFS up to `depth` hops in both directions
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
    net = Network(height="600px", width="100%", directed=True, notebook=False)

    for node in subg.nodes:
        cell = graph.cells.get(node)
        is_root = node == root_cell_id
        color = "#EF5350" if is_root else (_COLORS["cell_formula"] if (cell and cell.formula_raw) else _COLORS["cell_value"])
        label = node.split("_", 1)[-1] if "_" in node else node
        title = f"{node}\nValue: {cell.value if cell else '?'}\nFormula: {cell.formula_raw or '' if cell else ''}"
        net.add_node(node, label=label, title=title, color=color, size=20 if is_root else 12)

    for src, dst in subg.edges:
        net.add_edge(src, dst, color=_COLORS["edge_depends"])

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".html", prefix="kg_cell_")
        os.close(fd)

    net.save_graph(output_path)
    return output_path


def build_diff_propagation_graph(
    graph: FinancialGraph,
    changed_cell_ids: set[str],
    max_hops: int = 5,
    max_nodes: int = 300,
    output_path: Optional[str] = None,
) -> str:
    """Build pyvis visualization of change propagation through the dependency graph.

    Edge direction: A -> B means "A depends on B". When B changes, A is affected.
    So we follow predecessors (cells that depend on the changed cell) to find propagation chain.

    Node coloring:
    - Seed changed cells: red (value decreased) / green (value increased)
    - Propagated cells: yellow/orange gradient by hop distance
    - Affected indicators: blue highlights

    Node size: proportional to change magnitude for seeds, hop distance for propagated.
    """
    if not _PYVIS_AVAILABLE:
        raise ImportError("pyvis is not installed. Run: pip install pyvis")

    from pyvis.network import Network

    g = graph.cell_graph
    visited: dict[str, int] = {}  # cell_id -> hop distance (0 = seed)
    queue: deque[str] = deque()

    # Seeds at hop 0
    for cid in changed_cell_ids:
        if cid in g:
            visited[cid] = 0
            queue.append(cid)

    # BFS through predecessors (cells that depend on the changed cell)
    while queue:
        node = queue.popleft()
        hop = visited[node]
        if hop >= max_hops:
            continue
        for pred in g.predecessors(node):
            if pred not in visited:
                cell = graph.cells.get(pred)
                if cell and cell.formula_raw:  # Only propagate through formula cells
                    visited[pred] = hop + 1
                    queue.append(pred)
        if len(visited) >= max_nodes:
            break

    if not visited:
        raise ValueError("No affected cells found in graph")

    subg = g.subgraph(visited)
    net = Network(height="700px", width="100%", directed=True, notebook=False)
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -4000,
          "centralGravity": 0.3,
          "springLength": 120,
          "springConstant": 0.04,
          "damping": 0.09,
          "avoidOverlap": 0.3
        },
        "stabilization": {
          "enabled": true,
          "iterations": 300,
          "fit": true
        },
        "minVelocity": 0.75
      },
      "edges": {"arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}},
      "interaction": {"hover": true, "navigationButtons": true}
    }
    """)

    # Collect affected indicator IDs
    affected_indicators: set[str] = set()
    for cid in visited:
        cell = graph.cells.get(cid)
        if cell and cell.indicator_id:
            affected_indicators.add(cell.indicator_id)

    for node in subg.nodes:
        cell = graph.cells.get(node)
        hop = visited.get(node, 0)
        ind = graph.indicators.get(cell.indicator_id) if cell and cell.indicator_id else None

        # Color by hop
        if hop == 0:
            color = "#EF5350"  # red = seed/source of change
            size = 22
        elif hop == 1:
            color = "#FFA726"  # orange = first hop
            size = 18
        elif hop == 2:
            color = "#FFD54F"  # yellow
            size = 15
        else:
            color = "#FFF9C4"  # light yellow
            size = 12

        if ind:
            shape = "diamond"
            title = (
                f"[CHANGED] {node}\n"
                f"Value: {cell.value if cell else '?'}\n"
                f"Hop: {hop}\n"
                f"Indicator: {ind.name}\n"
                f"Formula: {cell.formula_raw or '无' if cell else ''}"
            )
        else:
            shape = "ellipse"
            title = (
                f"{node}\n"
                f"Value: {cell.value if cell else '?'}\n"
                f"Hop: {hop}\n"
                f"Formula: {cell.formula_raw or '无' if cell else ''}"
            )

        net.add_node(node, label=node.split("_", 1)[-1] if "_" in node else node,
                     title=title, color=color, shape=shape, size=size, hop=hop)

    for src, dst in subg.edges:
        hop_src = visited.get(src, 99)
        hop_dst = visited.get(dst, 99)
        edge_hop = max(hop_src, hop_dst)
        if edge_hop == 0:
            edge_color = "#EF5350"
            edge_width = 3
            edge_hidden = False
        else:
            edge_color = "#CFD8DC"
            edge_width = 1.5
            edge_hidden = True  # Initially hidden, revealed by animation
        net.add_edge(src, dst, color=edge_color, width=edge_width, hop=edge_hop, hidden=edge_hidden)

    # Add indicator summary nodes
    for ind_id in affected_indicators:
        ind = graph.indicators.get(ind_id)
        if ind is None:
            continue
        aff_count = sum(
            1 for cid in visited
            if graph.cells.get(cid) and graph.cells[cid].indicator_id == ind_id
        )
        net.add_node(
            f"IND_{ind_id}",
            label=ind.name[:20],
            title=f"[Indicator] {ind.name}\nCategory: {ind.category or ''}\n"
                  f"Affected cells: {aff_count}\n"
                  f"Value: {ind.summary_value}\n"
                  f"Unit: {ind.unit or ''}",
            color="#42A5F5",
            shape="box",
            size=max(15, min(30, aff_count * 5)),
        )
        for cid in visited:
            cell = graph.cells.get(cid)
            if cell and cell.indicator_id == ind_id:
                net.add_edge(f"IND_{ind_id}", cid, color="#42A5F5", width=1.5, dashes=True, hop=-1)

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".html", prefix="kg_diff_")
        os.close(fd)

    net.save_graph(output_path)

    # Post-process: inject propagation animation
    with open(output_path, encoding="utf-8") as f:
        html_content = f.read()
    html_content = _inject_propagation_animation(html_content)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path


def _inject_propagation_animation(html: str) -> str:
    """Post-process pyvis HTML to inject propagation animation script."""
    animation_js = r"""
<script>
(function() {
  'use strict';

  var ANIM = {
    hopInterval: 1000,     // ms between hops
    edgeStagger: 60,       // ms between individual edge reveals within a hop
    nodePulseMs: 800,      // duration of node size pulse
    green: '#22c55e',
    greenLight: '#4ade80',
    seedColor: '#EF5350',
  };

  var animTimers = [];

  function clearTimers() {
    animTimers.forEach(function(t) { clearTimeout(t); });
    animTimers = [];
  }

  function addControls() {
    var existing = document.getElementById('prop-ctrl');
    if (existing) existing.remove();

    var panel = document.createElement('div');
    panel.id = 'prop-ctrl';
    panel.style.cssText = 'position:fixed;top:10px;right:10px;z-index:999999;background:rgba(255,255,255,0.95);border-radius:10px;padding:10px 14px;box-shadow:0 2px 12px rgba(0,0,0,0.18);font-family:system-ui,sans-serif;font-size:13px;display:flex;gap:8px;align-items:center;flex-direction:column;';

    var btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:8px;align-items:center;';
    btnRow.innerHTML = '<button id="prop-replay" style="background:#22c55e;color:#fff;border:none;border-radius:6px;padding:6px 14px;cursor:pointer;font-weight:500;">▶ 播放</button><button id="prop-fs" style="background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px;">⛶ 全屏</button>';

    var statusRow = document.createElement('div');
    statusRow.innerHTML = '<span id="prop-status" style="color:#64748b;font-size:12px;"></span>';
    statusRow.style.cssText = 'text-align:center;';

    var progressBar = document.createElement('div');
    progressBar.id = 'prop-progress-bar';
    progressBar.style.cssText = 'width:100%;height:4px;background:#e2e8f0;border-radius:2px;overflow:hidden;margin-top:4px;';
    progressBar.innerHTML = '<div id="prop-progress-fill" style="width:0%;height:100%;background:#22c55e;transition:width 0.3s;"></div>';

    panel.appendChild(btnRow);
    panel.appendChild(statusRow);
    panel.appendChild(progressBar);
    document.body.appendChild(panel);

    document.getElementById('prop-replay').addEventListener('click', function() {
      clearTimers();
      document.getElementById('prop-status').textContent = '准备中...';
      document.getElementById('prop-progress-fill').style.width = '0%';
      // Reset edges to initial hidden state
      network.setOptions({physics: {enabled: false}});
      var resetEdges = [];
      var allE = edges.get({returnType: 'Object'});
      for (var rid in allE) {
        var re = allE[rid];
        if (re.hop < 0) continue;
        resetEdges.push({id: rid, hidden: re.hop > 0});
      }
      edges.update(resetEdges);
      runAnimation();
    });

    document.getElementById('prop-fs').addEventListener('click', toggleFullscreen);
  }

  var fsOverlay = null;
  var fsNetwork = null;
  var origNodes = null;
  var origEdges = null;
  var origNetwork = null;

  function toggleFullscreen() {
    if (fsOverlay) {
      // Exit fullscreen mode
      fsOverlay.remove();
      fsOverlay = null;
      fsNetwork = null;
      // Restore original globals
      nodes = origNodes;
      edges = origEdges;
      network = origNetwork;
      var orig = document.getElementById('mynetwork');
      if (orig) orig.style.display = 'block';
      document.getElementById('prop-fs').textContent = '⛶ 全屏';
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(function(){});
      }
      return;
    }
    // Enter browser fullscreen first
    var el = document.documentElement;
    var rfs = el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
    if (rfs) {
      rfs.call(el);
    }

    // If in iframe, try to make parent elements expand
    if (window.frameElement) {
      window.frameElement.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:999999;border:none;';
    }
    // Also expand parent containers
    var body = document.body;
    body.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;overflow:hidden;margin:0;padding:0;z-index:99999;';
    // Find and expand any parent wrapper that might constrain size
    var p = body.parentElement;
    while (p && p !== document.documentElement) {
      p.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;overflow:hidden;margin:0;padding:0;';
      p = p.parentElement;
    }

    // Hide original network
    var orig = document.getElementById('mynetwork');
    if (orig) orig.style.display = 'none';

    // Save originals
    origNodes = nodes;
    origEdges = edges;
    origNetwork = network;

    // Build fullscreen overlay AFTER fullscreen change
    function buildOverlay() {
      fsOverlay = document.createElement('div');
      fsOverlay.id = 'fs-overlay';
      fsOverlay.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:10000;background:#1a1a2e;overflow:hidden;';

      // Control bar
      var ctrlBar = document.createElement('div');
      ctrlBar.style.cssText = 'position:absolute;top:0;left:0;right:0;z-index:10001;display:flex;justify-content:space-between;align-items:center;padding:8px 16px;background:rgba(0,0,0,0.5);';
      var exitBtn = document.createElement('button');
      exitBtn.textContent = '✕ 退出全屏 (ESC)';
      exitBtn.style.cssText = 'background:rgba(255,255,255,0.15);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:6px;padding:8px 16px;cursor:pointer;font-size:14px;';
      exitBtn.addEventListener('click', toggleFullscreen);
      var replayBtn = document.createElement('button');
      replayBtn.textContent = '▶ 重播动画';
      replayBtn.style.cssText = 'background:#22c55e;color:#fff;border:none;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:14px;font-weight:500;';
      replayBtn.addEventListener('click', function() { clearTimers(); runAnimation(); });
      var hint = document.createElement('span');
      hint.style.cssText = 'color:rgba(255,255,255,0.6);font-size:12px;';
      hint.textContent = '鼠标滚轮缩放 · 拖拽平移';
      ctrlBar.appendChild(exitBtn);
      ctrlBar.appendChild(replayBtn);
      ctrlBar.appendChild(hint);
      fsOverlay.appendChild(ctrlBar);

      // Network container — explicit pixel size
      var fsContainer = document.createElement('div');
      fsContainer.id = 'fs-network-container';
      var barH = 48;
      fsContainer.style.cssText = 'position:absolute;top:' + barH + 'px;left:0;right:0;bottom:0;width:100%;';
      fsOverlay.appendChild(fsContainer);
      document.body.appendChild(fsOverlay);

      // Clone nodes with proper color normalization
      var nodeArr = nodes.get();
      var edgeArr = edges.get();

      // Ensure node colors are hex strings, not objects
      var fsNodeArr = nodeArr.map(function(n) {
        var copy = {id: n.id, label: n.label, title: n.title, shape: n.shape, size: n.size || 12, hop: n.hop || 0};
        var c = n.color;
        if (c && typeof c === 'object') {
          copy.color = c.background || '#999';
        } else if (typeof c === 'string') {
          copy.color = c;
        } else {
          copy.color = '#999';
        }
        // Shadow
        if (n.shadow) {
          copy.shadow = {enabled: true, color: n.shadow.color || '#fff', size: n.shadow.size || 10};
        }
        return copy;
      });

      // Ensure edge colors are plain hex strings
      var fsEdgeArr = edgeArr.map(function(e) {
        var copy = {id: e.id, from: e.from, to: e.to, hop: e.hop || 0, width: e.width || 1.5, hidden: e.hidden === true, dashes: e.dashes || false, title: e.title || '', hop: e.hop};
        var c = e.color;
        if (c && typeof c === 'object') {
          copy.color = c.color || '#CFD8DC';
          copy.highlight = c.highlight || copy.color;
          copy.hover = c.hover || copy.color;
        } else if (typeof c === 'string') {
          copy.color = c;
          copy.highlight = c;
          copy.hover = c;
        } else {
          copy.color = '#CFD8DC';
          copy.highlight = '#CFD8DC';
          copy.hover = '#CFD8DC';
        }
        // Arrows
        if (e.arrows) {
          copy.arrows = e.arrows;
        } else {
          copy.arrows = {to: {enabled: true, scaleFactor: 0.5}};
        }
        return copy;
      });

      var fsData = {
        nodes: new vis.DataSet(fsNodeArr),
        edges: new vis.DataSet(fsEdgeArr)
      };

      var fsOptions = {
        physics: {enabled: false},
        edges: {arrows: {to: {enabled: true, scaleFactor: 0.5}}},
        interaction: {hover: true, navigationButtons: true}
      };

      fsNetwork = new vis.Network(fsContainer, fsData, fsOptions);

      // Reassign globals for animation
      nodes = fsData.nodes;
      edges = fsData.edges;
      network = fsNetwork;

      document.getElementById('prop-fs').textContent = '⛶ 退出全屏';

      setTimeout(function() { fsNetwork.fit(); }, 200);
    }

    // Small delay for fullscreen to activate
    setTimeout(buildOverlay, 300);

    // ESC to exit
    document.addEventListener('keydown', function escHandler(e) {
      if (e.key === 'Escape' && fsOverlay) {
        document.removeEventListener('keydown', escHandler);
        toggleFullscreen();
      }
    });
  }

  function runAnimation() {
    _runAnimation(network, nodes, edges);
  }

  function _runAnimation(net, nodes, edges) {
    if (!net || !edges || !nodes) return;
    clearTimers();

    // Disable physics during animation to prevent lag
    net.setOptions({physics: {enabled: false}});

    var allEdgesObj = edges.get({returnType: 'Object'});
    var allNodesObj = nodes.get({returnType: 'Object'});

    // Group edges by hop
    var edgesByHop = {};
    var nodesByHop = {};
    var maxHop = 0;

    for (var eid in allEdgesObj) {
      var e = allEdgesObj[eid];
      var h = (e.hop !== undefined) ? Math.floor(e.hop) : 0;
      if (h < 0) continue;
      if (!edgesByHop[h]) edgesByHop[h] = [];
      edgesByHop[h].push(eid);
      if (h > maxHop) maxHop = h;
    }

    for (var nid in allNodesObj) {
      var n = allNodesObj[nid];
      var h = (n.hop !== undefined) ? Math.floor(n.hop) : 0;
      if (!nodesByHop[h]) nodesByHop[h] = [];
      nodesByHop[h].push(nid);
    }

    var statusEl = document.getElementById('prop-status');
    var fillEl = document.getElementById('prop-progress-fill');

    // Edges are already hidden (hop>0) or visible (hop=0) from pyvis generation.
    // Just ensure seed edges are visible.
    var showSeedEdges = [];
    for (var eid in allEdgesObj) {
      var e = allEdgesObj[eid];
      if (e.hop === 0 && e.hidden) {
        showSeedEdges.push({id: eid, hidden: false, color: ANIM.seedColor, width: 3});
      }
    }
    if (showSeedEdges.length > 0) edges.update(showSeedEdges);

    // Step 2: Seed node pulse
    var seedNodes = nodesByHop[0] || [];
    seedNodes.forEach(function(id) {
      var sn = allNodesObj[id];
      nodes.update([{id: id, size: (sn.size || 15) + 6, shadow: {enabled: true, color: ANIM.seedColor, size: 30}}]);
    });

    animTimers.push(setTimeout(function() {
      // Shrink seeds
      seedNodes.forEach(function(id) {
        var sn = allNodesObj[id];
        nodes.update([{id: id, size: sn.size || 15, shadow: {enabled: false}}]);
      });

      // Step 3: Hop-by-hop reveal
      var totalHops = maxHop;
      var completedHops = 0;

      for (var hop = 0; hop <= maxHop; hop++) {
        (function(currentHop) {
          var delay = (currentHop + 1) * ANIM.hopInterval;
          animTimers.push(setTimeout(function() {
            var hEdges = edgesByHop[currentHop] || [];
            var hNodes = nodesByHop[currentHop] || [];

            // Reveal edges one by one with stagger
            hEdges.forEach(function(eid, idx) {
              var edgeDelay = idx * ANIM.edgeStagger;
              animTimers.push(setTimeout(function() {
                var orig = allEdgesObj[eid];
                edges.update([{
                  id: eid,
                  hidden: false,
                  color: {color: ANIM.green, highlight: ANIM.greenLight, hover: ANIM.greenLight},
                  width: 4,
                  shadow: {enabled: true, color: ANIM.green, size: 10}
                }]);

                // Restore edge style after pulse
                animTimers.push(setTimeout(function() {
                  edges.update([{
                    id: eid,
                    color: orig.color,
                    width: orig.width || 2,
                    shadow: {enabled: false}
                  }]);
                }, ANIM.nodePulseMs));
              }, edgeDelay));
            });

            // Pulse nodes when first reached
            hNodes.forEach(function(nid, idx) {
              var nodeDelay = idx * ANIM.edgeStagger;
              animTimers.push(setTimeout(function() {
                var origNode = allNodesObj[nid];
                nodes.update([{
                  id: nid,
                  size: (origNode.size || 12) + 4,
                  color: ANIM.green,
                  shadow: {enabled: true, color: ANIM.green, size: 18}
                }]);

                // Restore
                animTimers.push(setTimeout(function() {
                  nodes.update([{
                    id: nid,
                    size: origNode.size || 12,
                    color: origNode.color,
                    shadow: {enabled: false}
                  }]);
                }, ANIM.nodePulseMs));
              }, nodeDelay));
            });

            // Update progress
            completedHops++;
            var pct = Math.round(completedHops / (totalHops + 1) * 100);
            if (fillEl) fillEl.style.width = pct + '%';
            if (statusEl) statusEl.textContent = '第 ' + currentHop + '/' + maxHop + ' 跳';

            // Done
            if (currentHop === maxHop) {
              animTimers.push(setTimeout(function() {
                if (statusEl) statusEl.textContent = '✅ 传播完成 (' + maxHop + ' 跳)';
                if (fillEl) fillEl.style.width = '100%';
                net.setOptions({physics: {enabled: true}});
              }, ANIM.nodePulseMs + hEdges.length * ANIM.edgeStagger));
            }

          }, delay));
        })(hop);
      }
    }, 800));
  }

  // Wait for network
  if (typeof network !== 'undefined' && network) {
    addControls();
    var statusEl = document.getElementById('prop-status');
    if (statusEl) statusEl.textContent = '稳定后开始...';
    network.once('stabilizationIterationsDone', function() {
      setTimeout(function() { runAnimation(); }, 300);
    });
  } else {
    var checkInterval = setInterval(function() {
      if (typeof network !== 'undefined' && network) {
        clearInterval(checkInterval);
        addControls();
        network.once('stabilizationIterationsDone', function() {
          setTimeout(function() { runAnimation(); }, 300);
        });
      }
    }, 100);
  }
})();
</script>
"""

    inject = '<div style="position:relative;">' + animation_js + '</body>'
    return html.replace('</body>', inject)
