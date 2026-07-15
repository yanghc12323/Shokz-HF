"""Sample-level QC explanation and 3D layer selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
        left = QFrame()
        left.setObjectName("resultSidebar")
        left.setFixedWidth(300)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("结果复核"))
        self.sample_box = QComboBox()
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
        left_layout.addStretch(1)
        layout.addWidget(left)
        layout.addWidget(self.viewer, 1)
        self._set_layer_availability({})

    def set_attempt(self, index: ArtifactIndex) -> None:
        self.index = index
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
            LayerName.AVERAGE_EAR: ("pca_dir", Path("mean_whole_ear.ply")),
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
