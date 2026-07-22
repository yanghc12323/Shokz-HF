"""Interactive local mesh viewing with optional QC region highlighting."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

import pyvista as pv
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from desktop_app.models import ArtifactRef, LayerName


class MeshViewer(QWidget):
    """Load only the selected, project-scoped mesh layer into a VTK viewport."""

    def __init__(self, *, interactor_factory: Callable[..., QWidget] | None = None) -> None:
        super().__init__()
        self._interactor_factory = interactor_factory
        self.plotter: object | None = None
        self._mesh: pv.DataSet | None = None
        self._region_actor: object | None = None
        self.current_layer: LayerName | None = None
        self.highlighted_region: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel("选择可用图层以加载三维模型。\n鼠标左键旋转，滚轮缩放，右键平移。")
        self.placeholder.setObjectName("meshViewerPlaceholder")
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder)
        self._layout = layout

    def load_layer(self, layer: LayerName, artifact: ArtifactRef) -> None:
        mesh = self._read_mesh(artifact.path)
        plotter = self._ensure_plotter()
        plotter.clear()
        plotter.add_mesh(
            mesh,
            color="#6f9cab",
            smooth_shading=True,
            show_edges=False,
            ambient=0.25,
            diffuse=0.75,
            specular=0.18,
            specular_power=18,
        )
        plotter.add_text(
            f"图层：{artifact.label}",
            position="upper_left",
            font_size=10,
            color="#284955",
        )
        self._mesh = mesh
        self.current_layer = LayerName(layer)
        self._region_actor = None
        self.set_region_highlight(self.highlighted_region)
        plotter.reset_camera()

    def reset_camera(self) -> None:
        if self.plotter is not None:
            self.plotter.reset_camera()

    def set_region_highlight(self, region_id: str | None) -> None:
        self.highlighted_region = region_id or None
        if self.plotter is None or self._mesh is None:
            return
        if self._region_actor is not None and hasattr(self.plotter, "remove_actor"):
            self.plotter.remove_actor(self._region_actor)
            self._region_actor = None
        if self.highlighted_region is None:
            return
        subset = self._region_subset(self._mesh, self.highlighted_region)
        if subset is not None and subset.n_points:
            self._region_actor = self.plotter.add_mesh(
                subset,
                color="#f59e0b",
                opacity=0.9,
                show_edges=True,
            )

    def _ensure_plotter(self):
        if self.plotter is not None:
            return self.plotter
        if self._interactor_factory is None:
            if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
                raise RuntimeError("当前环境没有可用图形桌面，无法启动三维渲染。")
            from pyvistaqt import QtInteractor

            factory = QtInteractor
        else:
            factory = self._interactor_factory
        self.plotter = factory(self)
        self.plotter.set_background("#eef4f6")
        self.plotter.add_axes(line_width=1, labels_off=True)
        self._layout.replaceWidget(self.placeholder, self.plotter)
        self.placeholder.hide()
        return self.plotter

    @staticmethod
    def _read_mesh(path: Path) -> pv.DataSet:
        path = Path(path)
        if path.is_file():
            return pv.read(path)
        if not path.is_dir():
            raise FileNotFoundError(f"图层产物不存在: {path}")
        files = sorted(candidate for candidate in path.rglob("*.ply") if candidate.is_file())
        if not files:
            raise FileNotFoundError(f"图层目录没有 PLY 文件: {path}")
        meshes = [pv.read(candidate) for candidate in files]
        return meshes[0] if len(meshes) == 1 else pv.merge(meshes, merge_points=False)

    @staticmethod
    def _region_subset(mesh: pv.DataSet, region_id: str) -> pv.DataSet | None:
        for attributes in (mesh.point_data, mesh.cell_data):
            if "region_id" not in attributes:
                continue
            values = attributes["region_id"]
            mask = [str(value) == region_id for value in values]
            if attributes is mesh.point_data:
                return mesh.extract_points(mask, adjacent_cells=True)
            return mesh.extract_cells(mask)
        return None
