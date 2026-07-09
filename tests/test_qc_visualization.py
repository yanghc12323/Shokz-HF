from pathlib import Path

import numpy as np
import trimesh

from ear_param.qc_visualization import (
    classify_region_qc,
    classify_repaired_region_qc,
    save_region_qc_figure,
    save_region_repaired_qc_figure,
)
from ear_param.remesh import (
    BoundaryPaths,
    LocatedSamples,
    PatchExtraction,
    PatchParameterization,
    RegionRemeshResult,
    SnappedLandmark,
    SubdivisionTemplate,
    make_subdivision_template,
    repair_unmapped_samples,
)


def _toy_result() -> tuple[trimesh.Trimesh, RegionRemeshResult]:
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])
    faces = np.array([[0, 1, 2]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    boundary = BoundaryPaths("A", "B", "C", [0, 1], [1, 2], [2, 0])
    snapped = {
        "A": SnappedLandmark("A", vertices[0], vertices[0], 0, 0.0),
        "B": SnappedLandmark("B", vertices[1], vertices[1], 1, 0.0),
        "C": SnappedLandmark("C", vertices[2], vertices[2], 2, 0.0),
    }
    patch = PatchExtraction(
        face_ids=np.array([0]),
        local_faces=faces,
        local_vertices=vertices,
        local_to_global=np.array([0, 1, 2]),
    )
    parameterization = PatchParameterization(
        uv=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
        local_faces=faces,
        local_vertices=vertices,
        local_to_global=np.array([0, 1, 2]),
        original_face_ids=np.array([0]),
        flipped_face_count=0,
        degenerate_face_count=0,
    )
    template = SubdivisionTemplate(
        resolution=1,
        barycentric=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
        uv=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
        faces=faces,
    )
    located = LocatedSamples(
        sample_uv=template.uv,
        face_indices=np.array([0, -1, 0]),
        barycentric=template.barycentric,
        unmapped_mask=np.array([False, True, False]),
    )
    result = RegionRemeshResult(
        region_id="R001",
        region_name="toy",
        snapped_landmarks=snapped,
        boundary_paths=boundary,
        patch=patch,
        parameterization=parameterization,
        template=template,
        located_samples=located,
        sample_points_3d=np.array([[0.0, 0.0, 0.0], [np.nan, np.nan, np.nan], [0.0, 1.0, 0.0]]),
    )
    return mesh, result


def _repairable_result() -> tuple[trimesh.Trimesh, RegionRemeshResult]:
    template = make_subdivision_template(3)
    vertices = np.column_stack([
        template.uv[:, 0],
        template.uv[:, 1],
        np.zeros(len(template.uv)),
    ])
    faces = template.faces
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    points = vertices.copy()
    unmapped = np.zeros(len(points), dtype=bool)
    unmapped[0] = True
    points[unmapped] = np.nan

    boundary = BoundaryPaths("L1", "L2", "L3", [0, 1], [1, 2], [2, 0])
    snapped = {
        "L1": SnappedLandmark("L1", vertices[0], vertices[0], 0, 0.0),
        "L2": SnappedLandmark("L2", vertices[1], vertices[1], 1, 0.0),
        "L3": SnappedLandmark("L3", vertices[2], vertices[2], 2, 0.0),
    }
    patch = PatchExtraction(
        face_ids=np.arange(len(faces)),
        local_faces=faces,
        local_vertices=vertices,
        local_to_global=np.arange(len(vertices)),
    )
    parameterization = PatchParameterization(
        uv=template.uv,
        local_faces=faces,
        local_vertices=vertices,
        local_to_global=np.arange(len(vertices)),
        original_face_ids=np.arange(len(faces)),
        flipped_face_count=0,
        degenerate_face_count=0,
    )
    located = LocatedSamples(
        sample_uv=template.uv,
        face_indices=np.where(unmapped, -1, 0),
        barycentric=template.barycentric,
        unmapped_mask=unmapped,
    )
    result = RegionRemeshResult(
        region_id="R001",
        region_name="repairable",
        snapped_landmarks=snapped,
        boundary_paths=boundary,
        patch=patch,
        parameterization=parameterization,
        template=template,
        located_samples=located,
        sample_points_3d=points,
    )
    return mesh, result


def test_classify_region_qc_reports_warning_for_some_unmapped_points():
    _, result = _toy_result()

    record = classify_region_qc("S001_L", result)

    assert record["sample_tag"] == "S001_L"
    assert record["region_id"] == "R001"
    assert record["sample_point_count"] == 3
    assert record["unmapped_count"] == 1
    assert record["status"] == "FAIL"


def test_save_region_qc_figure_writes_png():
    mesh, result = _toy_result()
    out_dir = Path(".test_artifacts")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "qc_visualization.png"

    save_region_qc_figure(mesh, result, out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    try:
        out_path.unlink()
        out_dir.rmdir()
    except OSError:
        pass


def test_classify_repaired_region_qc_reports_repair_counts():
    _, result = _repairable_result()
    repaired = repair_unmapped_samples(result)

    record = classify_repaired_region_qc("S001_L", result, repaired)

    assert record["sample_tag"] == "S001_L"
    assert record["raw_status"] == "WARNING"
    assert record["status"] == "PASS"
    assert record["raw_unmapped_count"] == 1
    assert record["repaired_unmapped_count"] == 0
    assert record["repair_count"] == 1
    assert record["repair_applied"] is True


def test_save_region_repaired_qc_figure_writes_png():
    mesh, result = _repairable_result()
    repaired = repair_unmapped_samples(result)
    out_dir = Path(".test_artifacts")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "qc_visualization_repaired.png"

    save_region_repaired_qc_figure(mesh, result, repaired, out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    try:
        out_path.unlink()
        out_dir.rmdir()
    except OSError:
        pass
