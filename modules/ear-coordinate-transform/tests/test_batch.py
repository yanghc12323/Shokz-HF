from __future__ import annotations

import csv
import json
import shutil
import unittest
import uuid
from pathlib import Path

import numpy as np
import trimesh

from ear_align.batch import batch_align_and_export, sample_key
from ear_align.settings import load_settings, save_reference_template


class BatchAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".test_runtime" / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_sample_key_pairs_model_and_landmark_csv(self) -> None:
        self.assertEqual(sample_key("T068_L.stl"), "t068_l")
        self.assertEqual(sample_key("T068_L_landmarks.csv"), "t068_l")
        self.assertEqual(sample_key("Case-01-R_POINTS.csv"), "case_01_r")

    def test_reference_template_settings_round_trip(self) -> None:
        path = self.root / "settings.json"
        save_reference_template("reference_R.stl", "reference.csv", "output", path)
        settings = load_settings(path)
        self.assertEqual(settings["reference_model"], "reference_R.stl")
        self.assertEqual(settings["reference_csv"], "reference.csv")
        self.assertEqual(settings["output_directory"], "output")

    def test_batch_continues_after_missing_csv_and_centers_every_success(self) -> None:
        vertices = np.array(
            [[10.0, 20.0, 30.0], [12.0, 20.0, 30.0], [10.0, 23.0, 30.0], [10.0, 20.0, 34.0]]
        )
        faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        landmark_ids = ("L7", "L13", "L15", "L26")

        reference_model = self.root / "REFERENCE_R.stl"
        reference_csv = self.root / "REFERENCE_R_landmarks.csv"
        self._write_mesh(reference_model, vertices, faces)
        self._write_csv(reference_csv, landmark_ids, vertices)

        models: list[Path] = []
        csvs: list[Path] = []
        for sample, shift in (("A_R", np.array([5.0, -2.0, 1.0])), ("B_R", np.array([-3.0, 7.0, 2.0]))):
            model = self.root / f"{sample}.stl"
            csv_path = self.root / f"{sample}_landmarks.csv"
            shifted = vertices + shift
            self._write_mesh(model, shifted, faces)
            self._write_csv(csv_path, landmark_ids, shifted)
            models.append(model)
            csvs.append(csv_path)

        missing_csv_model = self.root / "C_R.stl"
        self._write_mesh(missing_csv_model, vertices, faces)
        models.append(missing_csv_model)

        result = batch_align_and_export(
            reference_model,
            reference_csv,
            models,
            csvs,
            self.root / "output",
        )

        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.failure_count, 1)
        self.assertTrue(result.summary_path.is_file())
        with result.summary_path.open(encoding="utf-8") as handle:
            summary = json.load(handle)
        self.assertEqual(summary["success_count"], 2)
        self.assertEqual(summary["failure_count"], 1)
        for item in result.items:
            if item.result is not None:
                selected = np.vstack([item.result.landmarks[name] for name in landmark_ids])
                np.testing.assert_allclose(selected.mean(axis=0), np.zeros(3), atol=1e-12)
                self.assertTrue(item.result.output_obj_path.is_file())
                self.assertTrue(item.result.output_stl_path.is_file())
        self.assertTrue((self.root / "output" / "REFERENCE_R_centered.obj").is_file())
        self.assertTrue((self.root / "output" / "REFERENCE_R_centered.stl").is_file())

    @staticmethod
    def _write_mesh(path: Path, vertices: np.ndarray, faces: np.ndarray) -> None:
        trimesh.Trimesh(vertices=vertices, faces=faces, process=False).export(path)

    @staticmethod
    def _write_csv(path: Path, ids: tuple[str, ...], points: np.ndarray) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["landmark", "x", "y", "z"])
            for landmark_id, point in zip(ids, points, strict=True):
                writer.writerow([landmark_id, *point])


if __name__ == "__main__":
    unittest.main()

