"""Dedicated PCA morphology review page for clusters and extreme shapes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_app.artifact_indexer import ArtifactIndex
from desktop_app.models import ArtifactRef, LayerName
from desktop_app.viewers.mesh_viewer import MeshViewer


class PcaMorphologyPage(QWidget):
    """Render optional post-PCA morphology artifacts without changing QC status."""

    def __init__(self, *, viewer: MeshViewer | QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("pcaMorphologyPage")
        self.index: ArtifactIndex | None = None
        self.viewer = viewer or MeshViewer()
        self._models: dict[str, ArtifactRef] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(16)

        sidebar = QFrame()
        sidebar.setObjectName("pcaMorphologySidebar")
        sidebar.setFixedWidth(400)
        left = QVBoxLayout(sidebar)
        title = QLabel("PCA 形态分析")
        title.setObjectName("pcaMorphologyTitle")
        left.addWidget(title)
        caption = QLabel("区分理论 PC 形态、真实方向极值、聚类平均耳与候选极端个体。")
        caption.setObjectName("pcaMorphologyCaption")
        caption.setWordWrap(True)
        left.addWidget(caption)
        self.status_label = QLabel("尚未加载运行结果")
        self.status_label.setObjectName("pcaMorphologyStatus")
        self.status_label.setWordWrap(True)
        left.addWidget(self.status_label)
        self.cluster_choice_label = QLabel("自动聚类：未生成")
        self.cluster_choice_label.setObjectName("pcaMorphologyChoice")
        left.addWidget(self.cluster_choice_label)

        left.addWidget(self._section_label("聚类摘要"))
        self.cluster_table = self._table(["类别", "样本数", "成员"])
        self.cluster_table.setFixedHeight(130)
        left.addWidget(self.cluster_table)
        left.addWidget(self._section_label("真实方向极值"))
        self.observed_extremes_table = self._table(["主成分", "方向", "样本", "Score", "类别"])
        self.observed_extremes_table.setFixedHeight(150)
        left.addWidget(self.observed_extremes_table)
        left.addWidget(self._section_label("候选极端形态个体"))
        self.multivariate_extremes_table = self._table(["样本", "距离排名", "距离", "类别"])
        self.multivariate_extremes_table.setFixedHeight(150)
        left.addWidget(self.multivariate_extremes_table)
        left.addStretch(1)
        layout.addWidget(sidebar)

        right = QSplitter(Qt.Orientation.Vertical)
        figure_panel = QFrame()
        figure_panel.setObjectName("pcaMorphologyFigurePanel")
        figure_layout = QVBoxLayout(figure_panel)
        figure_layout.setContentsMargins(16, 14, 16, 16)
        figure_title = QLabel("PC1–PC2 聚类散点图")
        figure_title.setObjectName("pcaMorphologyPanelTitle")
        figure_layout.addWidget(figure_title)
        self.figure_label = QLabel("本次运行未生成 PCA 形态分析图")
        self.figure_label.setObjectName("pcaMorphologyFigure")
        self.figure_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.figure_label.setMinimumHeight(230)
        self.figure_label.setWordWrap(True)
        figure_layout.addWidget(self.figure_label, 1)

        viewer_panel = QFrame()
        viewer_panel.setObjectName("pcaMorphologyViewerPanel")
        viewer_layout = QVBoxLayout(viewer_panel)
        viewer_layout.setContentsMargins(16, 14, 16, 16)
        viewer_title = QLabel("三维形态查看")
        viewer_title.setObjectName("pcaMorphologyPanelTitle")
        viewer_layout.addWidget(viewer_title)
        self.model_selector = QComboBox()
        self.model_selector.setObjectName("pcaMorphologyModelSelector")
        self.model_selector.setEnabled(False)
        self.model_selector.currentTextChanged.connect(self._load_selected_model)
        viewer_layout.addWidget(self.model_selector)
        viewer_layout.addWidget(self.viewer, 1)
        right.addWidget(figure_panel)
        right.addWidget(viewer_panel)
        right.setStretchFactor(0, 4)
        right.setStretchFactor(1, 6)
        right.setSizes([330, 410])
        layout.addWidget(right, 1)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("pcaMorphologySectionTitle")
        return label

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def set_attempt(self, index: ArtifactIndex) -> None:
        self.index = index
        if index.pca_morphology_dir is None or index.pca_morphology_summary.empty:
            self._show_unavailable()
            return
        self.status_label.setText("PCA 形态分析已生成")
        self._set_cluster_choice(index.pca_morphology_summary)
        self._set_table(
            self.cluster_table,
            index.cluster_summary,
            [("cluster_id", "类别"), ("sample_count", "样本数"), ("member_sample_tags", "成员")],
        )
        self._set_table(
            self.observed_extremes_table,
            index.observed_pc_extremes.loc[
                index.observed_pc_extremes.get("status", pd.Series(dtype=str)) == "available"
            ],
            [("component", "主成分"), ("direction", "方向"), ("sample_tag", "样本"),
             ("score", "Score"), ("cluster_id", "类别")],
        )
        candidate_column = index.multivariate_extremes.get(
            "is_extreme_candidate", pd.Series(dtype=bool)
        )
        self._set_table(
            self.multivariate_extremes_table,
            index.multivariate_extremes.loc[candidate_column.astype(bool)],
            [("sample_tag", "样本"), ("distance_rank", "距离排名"),
             ("distance_to_center", "距离"), ("cluster_id", "类别")],
        )
        self._set_figure(index.pc1_pc2_clusters_figure)
        self._set_models(index)

    def _show_unavailable(self) -> None:
        self.status_label.setText("本次运行未生成 PCA 形态分析（旧运行或 PCA 后处理未完成）")
        self.cluster_choice_label.setText("自动聚类：未生成")
        self._set_table(self.cluster_table, pd.DataFrame(), [])
        self._set_table(self.observed_extremes_table, pd.DataFrame(), [])
        self._set_table(self.multivariate_extremes_table, pd.DataFrame(), [])
        self.figure_label.setPixmap(QPixmap())
        self.figure_label.setText("本次运行未生成 PCA 形态分析图")
        self._models.clear()
        self.model_selector.blockSignals(True)
        self.model_selector.clear()
        self.model_selector.blockSignals(False)
        self.model_selector.setEnabled(False)

    def _set_cluster_choice(self, summary: pd.DataFrame) -> None:
        row = summary.iloc[0]
        status = str(row.get("cluster_status", "未生成"))
        count = row.get("selected_cluster_count", 0)
        if status == "PASS":
            self.cluster_choice_label.setText(f"自动聚类：K = {count}（轮廓系数自动选择）")
        else:
            self.cluster_choice_label.setText(f"自动聚类：{status}")

    def _set_table(
        self,
        table: QTableWidget,
        data: pd.DataFrame,
        fields: list[tuple[str, str]],
    ) -> None:
        table.clearContents()
        table.setRowCount(len(data))
        for row_index, row in data.reset_index(drop=True).iterrows():
            for column_index, (field, _label) in enumerate(fields):
                value = row.get(field, "")
                text = f"{value:.4g}" if isinstance(value, float) else str(value)
                table.setItem(row_index, column_index, QTableWidgetItem(text))

    def _set_figure(self, path: Path | None) -> None:
        self.figure_label.setPixmap(QPixmap())
        if path is None or not path.is_file():
            self.figure_label.setText("本次运行未生成 PCA 形态分析图")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.figure_label.setText("PCA 聚类图存在，但当前无法读取")
            return
        self.figure_label.setText("")
        self.figure_label.setPixmap(pixmap.scaled(
            self.figure_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _set_models(self, index: ArtifactIndex) -> None:
        self._models.clear()
        pca_dir = index.output_dirs.get("selected_pca_dir")
        aligned_dir = index.output_dirs.get("selected_alignment_dir")
        if pca_dir is not None:
            for row in index.pc_extreme_shapes.itertuples(index=False):
                if str(getattr(row, "status", "")) != "available":
                    continue
                relative = Path(str(getattr(row, "relative_ply_path", "")))
                path = self._safe_child(pca_dir, relative)
                if path is None or not path.is_file():
                    continue
                direction = "+" if str(row.direction) == "plus" else "-"
                label = f"理论形态｜{row.component} {direction}2SD"
                self._models[label] = ArtifactRef(label, path)
        if aligned_dir is not None:
            for row in index.observed_pc_extremes.itertuples(index=False):
                if str(getattr(row, "status", "")) != "available":
                    continue
                sample_tag = str(getattr(row, "sample_tag", ""))
                path = self._safe_child(aligned_dir, Path(f"{sample_tag}_aligned_whole_ear.ply"))
                if path is None or not path.is_file():
                    continue
                direction = "+" if str(row.direction) == "plus" else "-"
                label = f"真实被试｜{row.component}{direction}｜{sample_tag}"
                self._models[label] = ArtifactRef(label, path)
        if index.pca_morphology_dir is not None:
            for row in index.cluster_summary.itertuples(index=False):
                cluster_id = str(getattr(row, "cluster_id", ""))
                path = self._safe_child(
                    index.pca_morphology_dir,
                    Path("cluster_means") / f"{cluster_id.replace(' ', '_')}_mean.ply",
                )
                if path is not None and path.is_file():
                    label = f"聚类平均耳｜{cluster_id}"
                    self._models[label] = ArtifactRef(label, path)
        self.model_selector.blockSignals(True)
        self.model_selector.clear()
        self.model_selector.addItem("请选择三维模型")
        self.model_selector.addItems(self._models)
        self.model_selector.blockSignals(False)
        self.model_selector.setEnabled(bool(self._models))

    @staticmethod
    def _safe_child(root: Path, relative: Path) -> Path | None:
        if relative.is_absolute() or ".." in relative.parts:
            return None
        resolved_root = root.resolve()
        candidate = (resolved_root / relative).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            return None
        return candidate

    def _load_selected_model(self, label: str) -> None:
        artifact = self._models.get(label)
        if artifact is None or not hasattr(self.viewer, "load_layer"):
            return
        self.viewer.load_layer(LayerName.PCA_MORPHOLOGY, artifact)
