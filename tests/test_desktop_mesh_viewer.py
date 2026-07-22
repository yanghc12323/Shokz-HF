from pathlib import Path

from PySide6.QtWidgets import QLabel

from desktop_app.models import ArtifactRef, LayerName
from desktop_app.viewers.mesh_viewer import MeshViewer


class FakePlotter(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.calls: list[tuple[str, object]] = []

    def clear(self) -> None:
        self.calls.append(("clear", None))

    def add_mesh(self, mesh, **kwargs) -> None:
        self.calls.append(("add_mesh", kwargs))

    def reset_camera(self) -> None:
        self.calls.append(("reset_camera", None))

    def set_background(self, color) -> None:
        self.calls.append(("set_background", color))

    def add_axes(self, **kwargs) -> None:
        self.calls.append(("add_axes", kwargs))

    def add_text(self, text, **kwargs) -> None:
        self.calls.append(("add_text", (text, kwargs)))


def test_mesh_viewer_loads_a_supported_mesh_and_tracks_region(qtbot, tmp_path: Path):
    import pyvista as pv

    path = tmp_path / "mesh.ply"
    pv.Sphere(theta_resolution=8, phi_resolution=8).save(path)
    viewer = MeshViewer(interactor_factory=FakePlotter)
    qtbot.addWidget(viewer)

    viewer.load_layer(LayerName.WHOLE_EAR, ArtifactRef("整耳", path))
    viewer.set_region_highlight("R01")
    viewer.reset_camera()

    assert viewer.current_layer is LayerName.WHOLE_EAR
    assert viewer.highlighted_region == "R01"
    assert any(call[0] == "add_mesh" for call in viewer.plotter.calls)
    assert any(call[0] == "reset_camera" for call in viewer.plotter.calls)
    assert ("set_background", "#eef4f6") in viewer.plotter.calls
    assert any(call[0] == "add_axes" for call in viewer.plotter.calls)
    assert any(call[0] == "add_text" for call in viewer.plotter.calls)


def test_mesh_viewer_rejects_headless_vtk_before_creating_a_render_window(monkeypatch, qtbot, tmp_path: Path):
    import pyvista as pv

    path = tmp_path / "mesh.ply"
    pv.Sphere(theta_resolution=8, phi_resolution=8).save(path)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    viewer = MeshViewer()
    qtbot.addWidget(viewer)

    try:
        viewer.load_layer(LayerName.WHOLE_EAR, ArtifactRef("整耳", path))
    except RuntimeError as exc:
        assert "图形" in str(exc)
    else:
        raise AssertionError("headless VTK must be rejected before renderer creation")
