from __future__ import annotations

import csv
import json
import shutil
import unittest
import uuid
from pathlib import Path

import numpy as np
import trimesh

from ear_align.alignment import kabsch
from ear_align.io import read_landmarks
from ear_align.mirroring import detect_side_from_filename, mirror_mesh, mirror_points
from ear_align.pipeline import align_and_export_mesh


class AlignmentTests(unittest.TestCase):
    def test_reads_landmark_header_and_keeps_all_rows(self) -> None:
        root = Path.cwd() / ".test_runtime"
        root.mkdir(exist_ok=True)
        path = root / f"landmarks_{uuid.uuid4().hex}.csv"
        self.addCleanup(path.unlink, True)
        path.write_text(
            "landmark,x,y,z\n"
            "L2,-11.4121,43.26588,-23.7317\n"
            "L7,2.272746,35.07171,-15.4864\n"
            "L26,7.955016,-15.6423,-3.40754\n"
            "L13,1.141937,14.28255,-12.6089\n"
            "L15,-19.2358,9.8684,-5.87021\n",
            encoding="utf-8",
        )

        landmarks = read_landmarks(path)

        self.assertEqual(set(landmarks), {"L2", "L7", "L13", "L15", "L26"})
        np.testing.assert_allclose(landmarks["L7"], [2.272746, 35.07171, -15.4864])

    def test_side_detection_and_mirror_reverse_face_winding(self) -> None:
        self.assertEqual(detect_side_from_filename("subject-01_L.stl"), "L")
        self.assertEqual(detect_side_from_filename("subject_01_R.obj"), "R")
        with self.assertRaises(ValueError):
            detect_side_from_filename("subject_left.stl")

        points = np.array([[1.0, 2.0, 3.0], [-4.0, 5.0, 6.0]])
        np.testing.assert_array_equal(
            mirror_points(points, "x"), np.array([[-1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        )
        mesh = trimesh.Trimesh(
            vertices=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            faces=[[0, 1, 2]],
            process=False,
        )
        mirrored = mirror_mesh(mesh, "x")
        np.testing.assert_array_equal(mirrored.faces, [[2, 1, 0]])

    def test_kabsch_recovers_proper_rigid_transform(self) -> None:
        source = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]]
        )
        angle = np.deg2rad(37.0)
        rotation = np.array(
            [[np.cos(angle), -np.sin(angle), 0.0], [np.sin(angle), np.cos(angle), 0.0], [0.0, 0.0, 1.0]]
        )
        translation = np.array([4.0, -2.0, 7.5])
        target = (rotation @ source.T).T + translation

        transform = kabsch(source, target)

        np.testing.assert_allclose(transform.rotation, rotation, atol=1e-12)
        np.testing.assert_allclose(transform.translation, translation, atol=1e-12)
        np.testing.assert_allclose(transform.apply(source), target, atol=1e-12)
        self.assertAlmostEqual(transform.determinant, 1.0, places=12)

    def test_pipeline_exports_mesh_landmarks_transform_and_metrics(self) -> None:
        # Avoid tempfile.TemporaryDirectory here: its restrictive Windows ACL
        # can make the directory inaccessible in managed sandbox environments.
        root = Path.cwd() / ".test_runtime" / uuid.uuid4().hex
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root, True)
        try:
            vertices = np.array(
                [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
            )
            faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
            moving_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

            angle = np.deg2rad(20.0)
            rotation = np.array(
                [[1.0, 0.0, 0.0], [0.0, np.cos(angle), -np.sin(angle)], [0.0, np.sin(angle), np.cos(angle)]]
            )
            translation = np.array([3.0, 4.0, -5.0])
            reference_vertices = (rotation @ vertices.T).T + translation
            reference_mesh = trimesh.Trimesh(vertices=reference_vertices, faces=faces, process=False)

            moving_path = root / "S001_R.stl"
            reference_path = root / "S002_R.stl"
            moving_mesh.export(moving_path)
            reference_mesh.export(reference_path)
            moving_csv = root / "moving.csv"
            reference_csv = root / "reference.csv"
            landmark_ids = ("L7", "L13", "L15", "L26")
            self._write_csv(moving_csv, landmark_ids, vertices)
            self._write_csv(reference_csv, landmark_ids, reference_vertices)

            result = align_and_export_mesh(
                reference_path,
                moving_path,
                reference_csv,
                moving_csv,
                root / "output" / "moving_aligned.obj",
                root / "output" / "moving_aligned.stl",
            )

            for path in (
                result.output_obj_path,
                result.output_stl_path,
                result.output_landmarks_path,
                result.transform_path,
                result.metrics_path,
            ):
                self.assertTrue(path.is_file() and path.stat().st_size > 0, path)
            exported = trimesh.load(result.output_obj_path, process=False)
            # STL stores triangle vertices independently, so loading the four-face
            # input expands it from four shared vertices to twelve vertices. The
            # exported OBJ must preserve that loaded topology exactly.
            np.testing.assert_allclose(exported.vertices, result.mesh.vertices, atol=1e-7)
            np.testing.assert_array_equal(exported.faces, result.mesh.faces)
            self.assertLess(float(result.metrics["rms_error"]), 1e-12)
            with result.transform_path.open(encoding="utf-8") as handle:
                transform_json = json.load(handle)
            self.assertIn("R", transform_json)
            self.assertIn("t", transform_json)
            self.assertEqual(np.asarray(transform_json["matrix"]).shape, (4, 4))
            self.assertAlmostEqual(transform_json["det_R"], 1.0, places=12)
            self.assertTrue(transform_json["center_reference"])
            aligned_selected = np.vstack([result.landmarks[item] for item in landmark_ids])
            np.testing.assert_allclose(aligned_selected.mean(axis=0), np.zeros(3), atol=1e-12)
            self.assertIsNotNone(result.output_reference_obj_path)
            self.assertIsNotNone(result.output_reference_stl_path)
            self.assertIsNotNone(result.output_reference_landmarks_path)
            for path in (
                result.output_reference_obj_path,
                result.output_reference_stl_path,
                result.output_reference_landmarks_path,
            ):
                assert path is not None
                self.assertTrue(path.is_file() and path.stat().st_size > 0, path)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @staticmethod
    def _write_csv(path: Path, ids: tuple[str, ...], points: np.ndarray) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["landmark", "x", "y", "z"])
            for landmark_id, point in zip(ids, points, strict=True):
                writer.writerow([landmark_id, *point])


if __name__ == "__main__":
    unittest.main()
