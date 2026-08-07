#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for selectable remesh compute backends."""

from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

import ear_param.remesh_backend as remesh_backend
from ear_param.remesh import locate_uv_samples_in_faces, make_subdivision_template
from ear_param.remesh_backend import (
    CudaRemeshBackend,
    backend_diagnostics,
    cuda_available,
    describe_backend,
    resolve_remesh_backend,
)


def test_auto_backend_falls_back_to_cpu_when_cuda_probe_reports_unavailable(monkeypatch):
    monkeypatch.setattr(
        "ear_param.remesh_backend._probe_cuda",
        lambda: (False, "CuPy unavailable"),
    )

    backend = resolve_remesh_backend("auto")

    assert (backend.name, backend.requested, backend.fallback_reason) == (
        "cpu",
        "auto",
        "CuPy unavailable",
    )


def test_cpu_backend_matches_reference_uv_locator():
    source = make_subdivision_template(6)
    target = make_subdivision_template(24)

    face_ids, barycentric, unmapped = resolve_remesh_backend("cpu").locate(
        source.uv,
        source.faces,
        target.uv,
        1e-9,
    )
    expected = locate_uv_samples_in_faces(source.uv, source.faces, target.uv)

    np.testing.assert_array_equal(face_ids, expected.face_indices)
    np.testing.assert_allclose(barycentric, expected.barycentric, atol=0.0, rtol=0.0)
    np.testing.assert_array_equal(unmapped, expected.unmapped_mask)


def test_auto_backend_selects_cuda_when_cuda_backend_builds(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        "ear_param.remesh_backend._probe_cuda",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "ear_param.remesh_backend._build_cuda_backend",
        lambda requested: sentinel,
        raising=False,
    )

    assert resolve_remesh_backend("auto") is sentinel


def test_auto_diagnostics_reports_cpu_fallback(monkeypatch):
    monkeypatch.setattr(
        "ear_param.remesh_backend._probe_cuda",
        lambda: (False, "CuPy unavailable"),
    )

    report = backend_diagnostics("auto")

    assert report == {
        "requested": "auto",
        "effective": "cpu",
        "fallback_reason": "CuPy unavailable",
        "gpu_peak_bytes": 0,
        "gpu_timing": {
            "region_count": 0,
            "lock_wait_seconds": 0.0,
            "host_to_device_seconds": 0.0,
            "harmonic_solve_seconds": 0.0,
            "uv_lookup_seconds": 0.0,
            "map_to_3d_seconds": 0.0,
            "device_to_host_seconds": 0.0,
            "region_wall_seconds": 0.0,
        },
    }


def test_cuda_backend_diagnostics_records_completed_gpu_event_segments():
    class FakeEvent:
        def record(self):
            pass

        def synchronize(self):
            pass

    class FakeCuda:
        @staticmethod
        def Event():
            return FakeEvent()

        @staticmethod
        def get_elapsed_time(start, end):
            return 250.0

    backend = CudaRemeshBackend(cp=SimpleNamespace(cuda=FakeCuda()))

    assert backend._time_gpu_operation("host_to_device_seconds", lambda: "copied") == "copied"
    backend._flush_gpu_timings()

    assert describe_backend(backend)["gpu_timing"] == {
        "region_count": 0,
        "lock_wait_seconds": 0.0,
        "host_to_device_seconds": 0.25,
        "harmonic_solve_seconds": 0.0,
        "uv_lookup_seconds": 0.0,
        "map_to_3d_seconds": 0.0,
        "device_to_host_seconds": 0.0,
        "region_wall_seconds": 0.0,
    }


def test_windows_cuda_probe_preloads_wheel_components_and_validates_solver(monkeypatch):
    calls: list[str] = []
    cupy = ModuleType("cupy")
    cupy.cuda = SimpleNamespace(
        runtime=SimpleNamespace(getDeviceCount=lambda: 1),
    )
    cupyx = ModuleType("cupyx")
    cupyx.__path__ = []  # Mark the fake module as an importable package.
    cusolver = ModuleType("cupyx.cusolver")
    cupyx.cusolver = cusolver

    monkeypatch.setitem(__import__("sys").modules, "cupy", cupy)
    monkeypatch.setitem(__import__("sys").modules, "cupyx", cupyx)
    monkeypatch.setitem(__import__("sys").modules, "cupyx.cusolver", cusolver)
    monkeypatch.setattr(
        remesh_backend,
        "_preload_cuda_wheel_libraries",
        lambda: calls.append("preload"),
        raising=False,
    )

    assert remesh_backend._probe_cuda() == (True, "")
    assert calls == ["preload"]


def test_windows_cuda_wheel_preload_loads_nvrtc_and_cusolver(monkeypatch):
    loaded: list[str] = []
    monkeypatch.setattr(remesh_backend.os, "name", "nt")
    monkeypatch.setattr(remesh_backend, "_CUDA_WHEEL_LIBRARY_HANDLES", [])
    monkeypatch.setattr(
        remesh_backend,
        "_load_cuda_wheel_library",
        lambda name: loaded.append(name) or object(),
        raising=False,
    )

    remesh_backend._preload_cuda_wheel_libraries()

    assert loaded == ["nvrtc", "cusolver"]


@pytest.mark.skipif(not cuda_available()[0], reason="CUDA backend unavailable")
def test_cuda_backend_matches_cpu_within_tolerance():
    source = make_subdivision_template(10)
    target = make_subdivision_template(24)
    cpu = resolve_remesh_backend("cpu")
    cuda = resolve_remesh_backend("cuda")

    cpu_ids, cpu_bary, cpu_unmapped = cpu.locate(
        source.uv, source.faces, target.uv, 1e-9
    )
    cuda_ids, cuda_bary, cuda_unmapped = cuda.locate(
        source.uv, source.faces, target.uv, 1e-9
    )

    np.testing.assert_array_equal(cuda_ids, cpu_ids)
    np.testing.assert_array_equal(cuda_unmapped, cpu_unmapped)
    np.testing.assert_allclose(cuda_bary, cpu_bary, atol=1e-12, rtol=0.0)
    vertices = np.column_stack((source.uv, np.zeros(len(source.uv))))
    np.testing.assert_allclose(
        cuda.map_to_3d(vertices, source.faces, cuda_ids, cuda_bary),
        cpu.map_to_3d(vertices, source.faces, cpu_ids, cpu_bary),
        atol=1e-8,
        rtol=0.0,
    )
