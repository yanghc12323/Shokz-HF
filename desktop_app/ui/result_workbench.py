"""Sample-level QC explanation and 3D layer selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from desktop_app.artifact_indexer import ArtifactIndex
from desktop_app.models import ArtifactRef, LayerName
from desktop_app.result_service import ResultService, SampleDetails
from desktop_app.viewers.mesh_viewer import MeshViewer


_LAYER_LABELS = {
    LayerName.RAW: "原始网格",
    LayerName.REPAIRED: "修复网格",
    LayerName.SALVAGED: "Salvaged 网格",
    LayerName.WHOLE_EAR: "整耳",
    LayerName.AVERAGE_EAR: "平均耳",
}


class ResultWorkbench(QWidget):
    """A focused workbench for evidence-backed model review."""

    def __init__(self, *, result_service: ResultService | None = None) -> None:
        super().__init__()
        self.result_service = result_service or ResultService()
        self.index: ArtifactIndex | None = None
        self.current_detail: SampleDetails | None = None
        self.viewer = MeshViewer()
        self._buttons: dict[LayerName, QToolButton] = {}
        self._layer_artifacts: dict[LayerName, ArtifactRef] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(16)
        self.result_scroll_area = QScrollArea()
        self.result_scroll_area.setObjectName("resultSidebarScroll")
        self.result_scroll_area.setWidgetResizable(True)
        self.result_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.result_scroll_area.setFixedWidth(390)
        self.result_sidebar = QFrame()
        self.result_sidebar.setObjectName("resultSidebar")
        self.result_scroll_area.setWidget(self.result_sidebar)
        left_layout = QVBoxLayout(self.result_sidebar)
        self.result_title_label = QLabel("结果复核")
        self.result_title_label.setObjectName("resultTitle")
        left_layout.addWidget(self.result_title_label)
        self.pca_title_label = QLabel("PCA 结果")
        self.pca_title_label.setObjectName("resultSectionTitle")
        left_layout.addWidget(self.pca_title_label)
        self.pca_summary_label = QLabel("PCA 结果：尚未加载运行结果。")
        self.pca_summary_label.setObjectName("pcaSummary")
        self.pca_summary_label.setWordWrap(True)
        left_layout.addWidget(self.pca_summary_label)
        self.pca_summary_table = self._table(5, 2)
        self.pca_summary_table.setHorizontalHeaderLabels(["指标", "结果"])
        self.pca_summary_table.setVerticalHeaderLabels([])
        self.pca_summary_table.setFixedHeight(165)
        left_layout.addWidget(self.pca_summary_table)
        self.open_pca_output_button = QPushButton("打开 PCA 结果文件夹")
        self.open_pca_output_button.setEnabled(False)
        self.open_pca_output_button.clicked.connect(self.open_pca_output_folder)
        left_layout.addWidget(self.open_pca_output_button)
        self.sample_box = QComboBox()
        self.sample_box.setObjectName("resultSampleSelector")
        self.sample_box.currentTextChanged.connect(self.select_sample)
        left_layout.addWidget(self.sample_box)
        self.status_label = QLabel("选择一次已完成运行以查看结果。")
        self.status_label.setObjectName("resultStatus")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)
        self.reason_label = QLabel()
        self.reason_label.setWordWrap(True)
        left_layout.addWidget(self.reason_label)
        for layer, label in _LAYER_LABELS.items():
            button = QToolButton()
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(lambda _checked=False, value=layer: self._load_layer(value))
            self._buttons[layer] = button
            left_layout.addWidget(button)
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("输入 region_id 高亮区域")
        self.region_input.returnPressed.connect(
            lambda: self.viewer.set_region_highlight(self.region_input.text())
        )
        left_layout.addWidget(self.region_input)
        reset = QPushButton("重置视角")
        reset.clicked.connect(self.viewer.reset_camera)
        left_layout.addWidget(reset)
        self.next_steps_label = QLabel(
            "下一步：确认模型与 QC 状态后，打开本次输出文件夹获取 CSV、PLY、OBJ、STL、PNG、manifest 和日志。"
        )
        self.next_steps_label.setWordWrap(True)
        left_layout.addWidget(self.next_steps_label)
        self.open_output_folder_button = QPushButton("打开本次输出文件夹")
        self.open_output_folder_button.setEnabled(False)
        self.open_output_folder_button.clicked.connect(self.open_output_folder)
        left_layout.addWidget(self.open_output_folder_button)
        left_layout.addStretch(1)
        layout.addWidget(self.result_scroll_area)

        self.review_splitter = QSplitter(Qt.Orientation.Vertical)
        self.review_splitter.setObjectName("resultReviewSplitter")
        self.pca_scores_panel = QFrame()
        self.pca_scores_panel.setObjectName("pcaScoresPanel")
        scores_layout = QVBoxLayout(self.pca_scores_panel)
        scores_layout.setContentsMargins(16, 14, 16, 16)
        self.pca_scores_label = QLabel("PCA Score")
        self.pca_scores_label.setObjectName("pcaScoresTitle")
        scores_layout.addWidget(self.pca_scores_label)
        scores_caption = QLabel("样本 × 主成分得分；可横向滚动查看全部 PC 列。")
        scores_caption.setObjectName("pcaScoresCaption")
        scores_layout.addWidget(scores_caption)
        self.pca_scores_table = self._table(0, 0)
        self.pca_scores_table.setMinimumHeight(170)
        scores_layout.addWidget(self.pca_scores_table, 1)

        self.viewer_panel = QFrame()
        self.viewer_panel.setObjectName("viewerPanel")
        viewer_layout = QVBoxLayout(self.viewer_panel)
        viewer_layout.setContentsMargins(16, 14, 16, 16)
        viewer_title = QLabel("三维模型查看")
        viewer_title.setObjectName("viewerTitle")
        viewer_layout.addWidget(viewer_title)
        viewer_layout.addWidget(self.viewer, 1)
        self.viewer_panel.setMinimumHeight(260)
        self.review_splitter.addWidget(self.pca_scores_panel)
        self.review_splitter.addWidget(self.viewer_panel)
        self.review_splitter.setStretchFactor(0, 4)
        self.review_splitter.setStretchFactor(1, 6)
        self.review_splitter.setSizes([270, 380])
        layout.addWidget(self.review_splitter, 1)
        self._set_layer_availability({})

    def set_attempt(self, index: ArtifactIndex) -> None:
        self.index = index
        self.open_output_folder_button.setEnabled(True)
        self.pca_summary_label.setText(self._pca_summary_text(index))
        pca_dir = index.output_dirs.get("selected_pca_dir")
        self.open_pca_output_button.setEnabled(pca_dir is not None and pca_dir.is_dir())
        self._set_pca_tables(index)
        self.sample_box.blockSignals(True)
        self.sample_box.clear()
        if "sample_tag" in index.batch_summary.columns:
            self.sample_box.addItems(sorted(index.batch_summary["sample_tag"].astype(str).tolist()))
        self.sample_box.blockSignals(False)
        if self.sample_box.count():
            self.select_sample(self.sample_box.currentText())
        else:
            self.status_label.setText("该运行没有可复核的样本记录。")
            self._set_layer_availability({})

    def open_output_folder(self) -> bool:
        """Open the isolated output root after the user has reviewed the model."""
        if self.index is None:
            return False
        return QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.index.attempt.artifacts_dir))
        )

    def open_pca_output_folder(self) -> bool:
        """Open the PCA artifacts created by the alignment mode selected for this run."""
        if self.index is None:
            return False
        pca_dir = self.index.output_dirs.get("selected_pca_dir")
        if pca_dir is None or not pca_dir.is_dir():
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(pca_dir)))

    @staticmethod
    def _pca_summary_text(index: ArtifactIndex) -> str:
        return "\n".join(f"{label}：{value}" for label, value in ResultWorkbench._pca_summary_rows(index))

    @staticmethod
    def _pca_summary_rows(index: ArtifactIndex) -> list[tuple[str, str]]:
        parameters = index.manifest.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        mode = str(parameters.get("alignment_mode", "gpa"))
        mode_label = "固定参考耳配准" if mode == "fixed-reference" else "GPA 配准"
        result = index.manifest.get("result")
        result = result if isinstance(result, dict) else {}
        pca_result = result.get("pca_result")
        pca_result = pca_result if isinstance(pca_result, dict) else {}
        status = str(result.get("pca_status", "未记录"))
        included = result.get("pca_included_count", "未记录")
        components = pca_result.get("retained_component_count", "未记录")
        variance = pca_result.get("retained_cumulative_explained_variance_ratio")
        variance_text = "未记录"
        if isinstance(variance, (int, float)):
            variance_text = f"{variance:.1%}"
        return [
            ("配准方式", mode_label),
            ("PCA 状态", status),
            ("纳入样本", str(included)),
            ("保留主成分", str(components)),
            ("累计解释方差", variance_text),
        ]

    @staticmethod
    def _table(rows: int, columns: int) -> QTableWidget:
        table = QTableWidget(rows, columns)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _set_pca_tables(self, index: ArtifactIndex) -> None:
        rows = self._pca_summary_rows(index)
        for row, (label, value) in enumerate(rows):
            self.pca_summary_table.setItem(row, 0, QTableWidgetItem(label))
            self.pca_summary_table.setItem(row, 1, QTableWidgetItem(value))

        scores = index.pca_scores
        self.pca_scores_table.clear()
        if scores.empty:
            self.pca_scores_table.setRowCount(1)
            self.pca_scores_table.setColumnCount(1)
            self.pca_scores_table.setHorizontalHeaderLabels(["PCA Score"])
            self.pca_scores_table.setItem(0, 0, QTableWidgetItem("本次运行没有可用的 PCA Score。"))
            return
        columns = [str(column) for column in scores.columns]
        self.pca_scores_table.setRowCount(len(scores))
        self.pca_scores_table.setColumnCount(len(columns))
        self.pca_scores_table.setHorizontalHeaderLabels(columns)
        for row_index, row in scores.iterrows():
            for column_index, column in enumerate(columns):
                value = row[column]
                text = f"{value:.4g}" if isinstance(value, float) else str(value)
                self.pca_scores_table.setItem(row_index, column_index, QTableWidgetItem(text))

    def select_sample(self, sample_tag: str) -> SampleDetails:
        if self.index is None:
            raise RuntimeError("尚未选择运行结果")
        detail = self.result_service.sample_details(self.index, sample_tag)
        self.current_detail = detail
        self.status_label.setText(
            f"Raw：{detail.raw_status}\nSalvage：{detail.salvage_status}\n"
            f"Weld：{detail.weld_status}\n对齐：{detail.alignment_status}\nPCA：{detail.pca_status}"
        )
        self.reason_label.setText(f"拦截说明：{detail.reason_zh}")
        self._layer_artifacts = self._find_layer_artifacts(sample_tag)
        self._set_layer_availability(self._layer_artifacts)
        return detail

    def layer_button(self, layer: LayerName | str) -> QToolButton:
        if isinstance(layer, str) and layer not in LayerName.__members__:
            for name, label in _LAYER_LABELS.items():
                if label == layer:
                    return self._buttons[name]
            raise KeyError(layer)
        return self._buttons[LayerName(layer)]

    def _find_layer_artifacts(self, sample_tag: str) -> dict[LayerName, ArtifactRef]:
        assert self.index is not None
        dirs = self.index.output_dirs
        candidates = {
            LayerName.RAW: ("raw_mesh_dir", Path(sample_tag)),
            LayerName.REPAIRED: ("repaired_mesh_dir", Path(sample_tag)),
            LayerName.SALVAGED: ("salvaged_mesh_dir", Path(sample_tag)),
            LayerName.WHOLE_EAR: ("weld_dir", Path(f"{sample_tag}_whole_ear_welded.ply")),
            LayerName.AVERAGE_EAR: ("selected_pca_dir", Path("mean_whole_ear.ply")),
        }
        artifacts: dict[LayerName, ArtifactRef] = {}
        for layer, (directory_key, relative) in candidates.items():
            root = dirs.get(directory_key)
            if root is None:
                continue
            path = root / relative
            if path.is_file() or (path.is_dir() and any(path.rglob("*.ply"))):
                artifacts[layer] = ArtifactRef(_LAYER_LABELS[layer], path)
        return artifacts

    def _set_layer_availability(self, artifacts: dict[LayerName, ArtifactRef]) -> None:
        for layer, button in self._buttons.items():
            available = layer in artifacts
            button.setEnabled(available)
            if available:
                button.setToolTip(f"加载{_LAYER_LABELS[layer]}图层")
            elif layer is LayerName.AVERAGE_EAR:
                button.setToolTip("PCA 未完成或平均耳产物不可用")
            else:
                button.setToolTip("该样本没有可用的此图层产物")

    def _load_layer(self, layer: LayerName) -> None:
        artifact = self._layer_artifacts.get(layer)
        if artifact is None:
            return
        try:
            self.viewer.load_layer(layer, artifact)
        except Exception as exc:
            self.status_label.setText(f"无法加载{_LAYER_LABELS[layer]}：{exc}")
