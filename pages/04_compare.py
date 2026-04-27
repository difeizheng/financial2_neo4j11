"""Page 4: Snapshot comparison."""
from __future__ import annotations
import os
import sys

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from financial_kg.storage.json_store import load_graph
from financial_kg.storage.task_db import TaskDB
from financial_kg.engine.snapshot import load_snapshot, diff_snapshots
from financial_kg.viz.graph_viz import build_diff_propagation_graph

st.set_page_config(page_title="快照对比", layout="wide")
st.title("📊 快照对比")

db = TaskDB()
tasks = [t for t in db.list_tasks() if t.status == "done"]

if not tasks:
    st.warning("暂无已解析的任务。")
    st.stop()

task_options = {f"{t.id} — {t.filename}": t for t in tasks}
selected_label = st.selectbox("选择任务", list(task_options.keys()))
task = task_options[selected_label]

@st.cache_resource(show_spinner="加载图谱...")
def _load(task_id: str, output_dir: str):
    cells_path = os.path.join(output_dir, f"{task_id}_cells.json")
    return load_graph(cells_path)

graph = _load(task.id, task.output_dir)

snaps = db.list_snapshots(task.id)
if len(snaps) < 2:
    st.info("该任务快照不足 2 个，请先在「参数重算」页面创建快照。")
    st.stop()

snap_options = {f"{s.name} ({s.created_at[:19]})": s for s in snaps}
col1, col2 = st.columns(2)
with col1:
    label_a = st.selectbox("快照 A（基准）", list(snap_options.keys()), index=len(snaps) - 1)
with col2:
    label_b = st.selectbox("快照 B（对比）", list(snap_options.keys()), index=0)

# ── Phase 1: Run comparison (stores result in session_state) ────────────────
if st.button("执行对比", type="primary"):
    rec_a = snap_options[label_a]
    rec_b = snap_options[label_b]

    if rec_a.id == rec_b.id:
        st.warning("请选择两个不同的快照")
        st.stop()

    with st.spinner("对比中..."):
        snap_a = load_snapshot(rec_a.filepath)
        snap_b = load_snapshot(rec_b.filepath)
        diff = diff_snapshots(snap_a, snap_b, graph)

    st.session_state["_compare_diff"] = {
        "changed_cells": diff.changed_cells,
        "affected_indicators": diff.affected_indicators,
        "summary": diff.summary,
    }
    st.session_state["_compare_graph_html"] = None
    st.rerun()

# ── Phase 2: Render results from session_state (runs every frame) ───────────
diff_data = st.session_state.get("_compare_diff")
if not diff_data:
    st.stop()

cells = diff_data["changed_cells"]
indicators = diff_data["affected_indicators"]
summary = diff_data["summary"]

st.subheader("汇总")
c1, c2, c3 = st.columns(3)
c1.metric("变化单元格数", summary["total_changed_cells"])
c2.metric("受影响 Indicator 数", summary["total_changed_indicators"])
c3.metric("涉及 Sheet 数", len(summary["sheets_affected"]))

if summary["sheets_affected"]:
    st.write("涉及 Sheet：", "、".join(summary["sheets_affected"]))

# ── Propagation graph ────────────────────────────────────────────────────
if cells:
    st.subheader("影响传播图谱")
    col_a, col_b = st.columns(2)
    max_hops = col_a.slider("传播深度（最大跳数）", 1, 10, 5, key="compare_hops")
    max_nodes_viz = col_b.slider("最大节点数", 50, 500, 200, 50, key="compare_nodes")

    if st.button("生成传播图谱", key="compare_viz_btn"):
        changed_ids = {c["id"] for c in cells}
        with st.spinner("渲染影响传播图谱..."):
            html = build_diff_propagation_graph(
                graph,
                changed_cell_ids=changed_ids,
                max_hops=max_hops,
                max_nodes=max_nodes_viz,
            )
        st.session_state["_compare_graph_html"] = html
        st.session_state["_compare_graph_stats"] = {
            "hops": max_hops,
            "nodes": max_nodes_viz,
        }

    # Render cached graph HTML (survives re-runs)
    graph_html = st.session_state.get("_compare_graph_html")
    if graph_html:
        st.caption("图谱预览（图谱内部控制面板可切换全屏）")
        components.html(graph_html, height=720, scrolling=False)

    stats = st.session_state.get("_compare_graph_stats", {})
    if stats or graph_html:
        st.caption(
            f"图例：红色 = 变化源头 | 橙色 = 第1跳影响 | 黄色 = 第2跳 | 浅黄 = 更远 | "
            f"蓝色方块 = 受影响的 Indicator "
            f"（传播深度={stats.get('hops', '?')}, 最大节点={stats.get('nodes', '?')}）"
        )

    st.divider()

if indicators:
    st.subheader("受影响 Indicator")
    rows = [
        {
            "Indicator": i["name"],
            "Sheet": i["sheet"],
            "旧汇总值": i["old_summary"],
            "新汇总值": i["new_summary"],
            "变化单元格数": i["changed_cell_count"],
        }
        for i in indicators
    ]
    st.dataframe(rows, use_container_width=True)

if cells:
    with st.expander(f"变化单元格明细（共 {len(cells)} 条，显示前 200）"):
        rows = [
            {
                "Cell ID": c["id"],
                "Sheet": c["sheet"],
                "旧值": c["old"],
                "新值": c["new"],
                "公式": c["formula"] or "",
            }
            for c in cells[:200]
        ]
        st.dataframe(rows, use_container_width=True)
