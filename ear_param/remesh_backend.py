#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Selectable numerical backends for the remesh UV stages.

The CPU backend deliberately mirrors the established NumPy/SciPy operations.
CUDA remains an optional dependency so ordinary CLI and desktop installs do not
need a GPU runtime.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
import threading
from time import perf_counter, sleep
from typing import Callable, Iterator, Literal, Protocol

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve


RemeshBackendName = Literal["cpu", "cuda", "auto"]
_GPU_THREAD_LOCK = threading.Lock()
_GPU_LOCK_FILE = Path(tempfile.gettempdir()) / "shokz_remesh_cuda.lock"
_CUDA_WHEEL_LIBRARY_HANDLES: list[object] = []
_GPU_TIMING_FIELDS = (
    "lock_wait_seconds",
    "host_to_device_seconds",
    "harmonic_solve_seconds",
    "uv_lookup_seconds",
    "map_to_3d_seconds",
    "device_to_host_seconds",
    "region_wall_seconds",
)


def _empty_gpu_timing() -> dict[str, float]:
    return {field_name: 0.0 for field_name in _GPU_TIMING_FIELDS}


class RemeshBackend(Protocol):
    """Numerical operations that may be evaluated on CPU or CUDA."""

    name: str
    requested: str
    fallback_reason: str

    def region_scope(self) -> Iterator[None]:
        """Reserve this backend while one region is being calculated."""

    def solve_harmonic(self, matrix: csr_matrix, rhs: np.ndarray) -> np.ndarray:
        """Solve the two-coordinate harmonic UV system."""

    def locate(
        self,
        uv: np.ndarray,
        faces: np.ndarray,
        sample_uv: np.ndarray,
        tol: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return face IDs, barycentric coordinates and unmapped mask."""

    def map_to_3d(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        face_ids: np.ndarray,
        barycentric: np.ndarray,
    ) -> np.ndarray:
        """Map valid UV sample locations back to their source 3D faces."""


@dataclass(frozen=True)
class CpuRemeshBackend:
    """Reference SciPy/NumPy backend preserving the historical semantics."""

    requested: str = "cpu"
    fallback_reason: str = ""
    name: str = "cpu"

    @contextmanager
    def region_scope(self) -> Iterator[None]:
        yield

    def solve_harmonic(self, matrix: csr_matrix, rhs: np.ndarray) -> np.ndarray:
        return np.asarray(spsolve(matrix, rhs), dtype=float)

    def locate(
        self,
        uv: np.ndarray,
        faces: np.ndarray,
        sample_uv: np.ndarray,
        tol: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Reference point-in-triangle scan in ascending source face order."""
        uv = np.asarray(uv, dtype=float)
        faces = np.asarray(faces, dtype=int)
        sample_uv = np.asarray(sample_uv, dtype=float)

        face_indices = np.full(len(sample_uv), -1, dtype=int)
        bary = np.full((len(sample_uv), 3), np.nan, dtype=float)
        unmapped = np.ones(len(sample_uv), dtype=bool)
        tri_uvs = uv[faces]

        for sample_id, point in enumerate(sample_uv):
            for face_id, tri_uv in enumerate(tri_uvs):
                weights = _barycentric_2d(point, tri_uv)
                if weights is None:
                    continue
                if np.all(weights >= -tol) and np.all(weights <= 1.0 + tol):
                    clipped = np.clip(weights, 0.0, 1.0)
                    total = clipped.sum()
                    bary[sample_id] = clipped / total if total > 0 else clipped
                    face_indices[sample_id] = face_id
                    unmapped[sample_id] = False
                    break

        return face_indices, bary, unmapped

    def map_to_3d(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        face_ids: np.ndarray,
        barycentric: np.ndarray,
    ) -> np.ndarray:
        vertices = np.asarray(vertices, dtype=float)
        faces = np.asarray(faces, dtype=int)
        face_ids = np.asarray(face_ids, dtype=int)
        barycentric = np.asarray(barycentric, dtype=float)
        mapped = np.full((len(face_ids), 3), np.nan, dtype=float)
        for sample_id, face_id in enumerate(face_ids):
            if face_id >= 0:
                mapped[sample_id] = barycentric[sample_id] @ vertices[faces[face_id]]
        return mapped


class BackendComputationError(RuntimeError):
    """A CUDA operator failed before a complete region result was produced."""


@dataclass
class CudaRemeshBackend:
    """Optional CuPy backend for UV solve, lookup and 3D interpolation."""

    cp: object
    requested: str = "cuda"
    fallback_reason: str = ""
    name: str = "cuda"
    gpu_peak_bytes: int = 0
    fallback_reasons: list[str] | None = None
    gpu_region_count: int = 0
    gpu_timing_seconds: dict[str, float] = field(default_factory=_empty_gpu_timing)
    _pending_gpu_timers: list[tuple[str, object, object]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.fallback_reasons is None:
            self.fallback_reasons = []

    def record_fallback(self, reason: str) -> None:
        if reason and reason not in self.fallback_reasons:
            self.fallback_reasons.append(reason)

    @contextmanager
    def region_scope(self) -> Iterator[None]:
        """Serialize GPU work across threads and local Python processes."""
        wait_started = perf_counter()
        with _GPU_THREAD_LOCK, _interprocess_cuda_lock():
            self.gpu_timing_seconds["lock_wait_seconds"] += perf_counter() - wait_started
            self.gpu_region_count += 1
            region_started = perf_counter()
            try:
                yield
            finally:
                self._flush_gpu_timings()
                self.gpu_timing_seconds["region_wall_seconds"] += perf_counter() - region_started
                self._record_gpu_memory()
                self._release_gpu_memory()

    def solve_harmonic(self, matrix: csr_matrix, rhs: np.ndarray) -> np.ndarray:
        try:
            cp = self.cp
            from cupyx.scipy.sparse import csr_matrix as cupy_csr_matrix
            from cupyx.scipy.sparse.linalg import spsolve as cupy_spsolve

            device_matrix, device_rhs = self._time_gpu_operation(
                "host_to_device_seconds",
                lambda: (
                    cupy_csr_matrix(matrix, dtype=cp.float64),
                    cp.asarray(rhs, dtype=cp.float64),
                ),
            )

            def solve_on_device() -> object:
                if device_rhs.ndim == 1:
                    return cupy_spsolve(device_matrix, device_rhs)
                return cp.column_stack(
                    [
                        cupy_spsolve(device_matrix, device_rhs[:, axis])
                        for axis in range(device_rhs.shape[1])
                    ]
                )

            solved = self._time_gpu_operation("harmonic_solve_seconds", solve_on_device)
            host = self._time_gpu_operation("device_to_host_seconds", lambda: cp.asnumpy(solved))
            self._flush_gpu_timings()
            if not np.isfinite(host).all():
                raise BackendComputationError("CUDA harmonic solve returned non-finite UV")
            return np.asarray(host, dtype=float)
        except BackendComputationError:
            raise
        except Exception as exc:
            raise BackendComputationError(f"CUDA harmonic solve failed: {exc}") from exc

    def locate(
        self,
        uv: np.ndarray,
        faces: np.ndarray,
        sample_uv: np.ndarray,
        tol: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Batched GPU UV lookup, preserving the first valid CPU face ID."""
        try:
            cp = self.cp
            uv_device, faces_device, samples_device = self._time_gpu_operation(
                "host_to_device_seconds",
                lambda: (
                    cp.asarray(uv, dtype=cp.float64),
                    cp.asarray(faces, dtype=cp.int64),
                    cp.asarray(sample_uv, dtype=cp.float64),
                ),
            )
            sample_count = int(len(sample_uv))
            face_count = int(len(faces))

            def locate_on_device() -> tuple[object, object, object]:
                face_ids = cp.full(sample_count, -1, dtype=cp.int64)
                barycentric = cp.full((sample_count, 3), cp.nan, dtype=cp.float64)
                mapped = cp.zeros(sample_count, dtype=cp.bool_)

                # Limits the largest temporary to roughly 64 x 4096 x float64 arrays.
                for sample_start in range(0, sample_count, 64):
                    sample_stop = min(sample_start + 64, sample_count)
                    points = samples_device[sample_start:sample_stop]
                    block_mapped = mapped[sample_start:sample_stop]
                    block_face_ids = face_ids[sample_start:sample_stop]
                    block_barycentric = barycentric[sample_start:sample_stop]
                    for face_start in range(0, face_count, 4096):
                        face_stop = min(face_start + 4096, face_count)
                        triangles = uv_device[faces_device[face_start:face_stop]]
                        a = triangles[:, 0]
                        ab = triangles[:, 1] - a
                        ac = triangles[:, 2] - a
                        delta = points[:, None, :] - a[None, :, :]
                        denominator = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]
                        valid_triangle = cp.abs(denominator) >= 1e-15
                        beta = (
                            delta[:, :, 0] * ac[None, :, 1]
                            - delta[:, :, 1] * ac[None, :, 0]
                        ) / denominator[None, :]
                        gamma = (
                            ab[None, :, 0] * delta[:, :, 1]
                            - ab[None, :, 1] * delta[:, :, 0]
                        ) / denominator[None, :]
                        alpha = 1.0 - beta - gamma
                        weights = cp.stack((alpha, beta, gamma), axis=2)
                        valid = valid_triangle[None, :] & cp.all(
                            (weights >= -tol) & (weights <= 1.0 + tol), axis=2
                        )
                        has_candidate = cp.any(valid, axis=1)
                        accepted = (~block_mapped) & has_candidate
                        first = cp.argmax(valid, axis=1)
                        selected = weights[cp.arange(len(points)), first]
                        clipped = cp.clip(selected, 0.0, 1.0)
                        totals = clipped.sum(axis=1)
                        normalized = cp.where(
                            totals[:, None] > 0.0,
                            clipped / totals[:, None],
                            clipped,
                        )
                        block_face_ids[accepted] = face_start + first[accepted]
                        block_barycentric[accepted] = normalized[accepted]
                        block_mapped |= accepted
                return face_ids, barycentric, mapped

            face_ids, barycentric, mapped = self._time_gpu_operation(
                "uv_lookup_seconds",
                locate_on_device,
            )
            host_ids, host_barycentric, host_unmapped = self._time_gpu_operation(
                "device_to_host_seconds",
                lambda: (
                    np.asarray(cp.asnumpy(face_ids), dtype=int),
                    np.asarray(cp.asnumpy(barycentric), dtype=float),
                    np.asarray(cp.asnumpy(~mapped), dtype=bool),
                ),
            )
            self._flush_gpu_timings()
            if not np.isfinite(host_barycentric[~host_unmapped]).all():
                raise BackendComputationError("CUDA UV lookup returned non-finite barycentric values")
            return host_ids, host_barycentric, host_unmapped
        except BackendComputationError:
            raise
        except Exception as exc:
            raise BackendComputationError(f"CUDA UV lookup failed: {exc}") from exc

    def map_to_3d(
        self,
        vertices: np.ndarray,
        faces: np.ndarray,
        face_ids: np.ndarray,
        barycentric: np.ndarray,
    ) -> np.ndarray:
        try:
            cp = self.cp
            vertices_device, faces_device, face_ids_device, barycentric_device = (
                self._time_gpu_operation(
                    "host_to_device_seconds",
                    lambda: (
                        cp.asarray(vertices, dtype=cp.float64),
                        cp.asarray(faces, dtype=cp.int64),
                        cp.asarray(face_ids, dtype=cp.int64),
                        cp.asarray(barycentric, dtype=cp.float64),
                    ),
                )
            )

            def map_on_device() -> object:
                mapped = cp.full((len(face_ids), 3), cp.nan, dtype=cp.float64)
                valid = face_ids_device >= 0
                if bool(cp.any(valid)):
                    source_faces = faces_device[face_ids_device[valid]]
                    mapped[valid] = cp.einsum(
                        "ij,ijk->ik",
                        barycentric_device[valid],
                        vertices_device[source_faces],
                    )
                return mapped

            mapped = self._time_gpu_operation("map_to_3d_seconds", map_on_device)
            host = self._time_gpu_operation(
                "device_to_host_seconds",
                lambda: np.asarray(cp.asnumpy(mapped), dtype=float),
            )
            self._flush_gpu_timings()
            if not np.isfinite(host[np.asarray(face_ids) >= 0]).all():
                raise BackendComputationError("CUDA 3D mapping returned non-finite points")
            return host
        except BackendComputationError:
            raise
        except Exception as exc:
            raise BackendComputationError(f"CUDA 3D mapping failed: {exc}") from exc

    def _time_gpu_operation(
        self,
        metric: str,
        operation: Callable[[], object],
    ) -> object:
        """Queue a CUDA-event timing without adding a synchronization barrier."""
        try:
            start = self.cp.cuda.Event()
            end = self.cp.cuda.Event()
            start.record()
        except Exception:
            return operation()

        try:
            return operation()
        finally:
            try:
                end.record()
                self._pending_gpu_timers.append((metric, start, end))
            except Exception:
                pass

    def _flush_gpu_timings(self) -> None:
        """Resolve queued CUDA events after an existing host result transfer."""
        pending = self._pending_gpu_timers
        self._pending_gpu_timers = []
        for metric, start, end in pending:
            try:
                end.synchronize()
                elapsed = float(self.cp.cuda.get_elapsed_time(start, end)) / 1000.0
                if metric in self.gpu_timing_seconds and np.isfinite(elapsed) and elapsed >= 0.0:
                    self.gpu_timing_seconds[metric] += elapsed
            except Exception:
                pass

    def gpu_timing_report(self) -> dict[str, float | int]:
        """Return rounded, JSON-safe timing counters for this sample process."""
        return {
            "region_count": int(self.gpu_region_count),
            **{
                metric: round(float(self.gpu_timing_seconds.get(metric, 0.0)), 6)
                for metric in _GPU_TIMING_FIELDS
            },
        }

    def _record_gpu_memory(self) -> None:
        try:
            self.gpu_peak_bytes = max(
                self.gpu_peak_bytes,
                int(self.cp.get_default_memory_pool().total_bytes()),
            )
        except Exception:
            pass

    def _release_gpu_memory(self) -> None:
        try:
            self.cp.get_default_memory_pool().free_all_blocks()
            self.cp.get_default_pinned_memory_pool().free_all_blocks()
        except Exception:
            pass


def resolve_remesh_backend(requested: RemeshBackendName | str = "cpu") -> RemeshBackend:
    """Resolve a requested backend without making CUDA mandatory.

    ``auto`` is intentionally conservative until a validated CUDA backend is
    available: it reports why it retained the reference CPU implementation.
    """
    requested = str(requested).strip().lower()
    if requested not in {"cpu", "cuda", "auto"}:
        raise ValueError("remesh backend must be one of: cpu, cuda, auto")
    if requested == "cpu":
        return CpuRemeshBackend(requested="cpu")

    available, reason = _probe_cuda()
    if not available:
        if requested == "cuda":
            raise RuntimeError(f"CUDA remesh backend is unavailable: {reason}")
        return CpuRemeshBackend(requested="auto", fallback_reason=reason)

    try:
        return _build_cuda_backend(requested)
    except Exception as exc:
        reason = f"CUDA backend initialization failed: {exc}"
        if requested == "cuda":
            raise RuntimeError(reason) from exc
        return CpuRemeshBackend(requested="auto", fallback_reason=reason)


def cuda_available() -> tuple[bool, str]:
    """Public CUDA availability probe for diagnostics and conditionally-run tests."""
    return _probe_cuda()


def backend_diagnostics(requested: RemeshBackendName | str = "cpu") -> dict[str, object]:
    """Return the requested/effective backend without starting an analysis."""
    backend = resolve_remesh_backend(requested)
    return describe_backend(backend)


def describe_backend(backend: RemeshBackend) -> dict[str, object]:
    """Return JSON-safe backend diagnostics after one or more regions."""
    fallback_reasons = list(getattr(backend, "fallback_reasons", []) or [])
    effective = backend.name
    if backend.name == "cuda" and fallback_reasons:
        effective = "cuda_with_cpu_fallback"
    timing_report = getattr(backend, "gpu_timing_report", None)
    gpu_timing = timing_report() if callable(timing_report) else {
        "region_count": 0,
        **_empty_gpu_timing(),
    }
    return {
        "requested": backend.requested,
        "effective": effective,
        "fallback_reason": backend.fallback_reason or " | ".join(fallback_reasons),
        "gpu_peak_bytes": int(getattr(backend, "gpu_peak_bytes", 0)),
        "gpu_timing": gpu_timing,
    }


def _build_cuda_backend(requested: str) -> CudaRemeshBackend:
    _preload_cuda_wheel_libraries()
    import cupy as cp
    import cupyx.cusolver  # Verify the CUDA sparse solver can load in this process.

    return CudaRemeshBackend(cp=cp, requested=requested)


def _probe_cuda() -> tuple[bool, str]:
    """Return CUDA availability without importing CuPy in CPU-only installs."""
    try:
        _preload_cuda_wheel_libraries()
    except Exception as exc:
        return False, f"CUDA runtime library preload failed: {exc}"

    try:
        import cupy as cp
    except Exception:
        return False, "CuPy unavailable"

    try:
        import cupyx.cusolver  # noqa: F401 - imports the DLL-backed sparse solver.
    except Exception as exc:
        return False, f"CUDA sparse solver unavailable: {exc}"

    try:
        device_count = int(cp.cuda.runtime.getDeviceCount())
    except Exception as exc:
        return False, f"CUDA probe failed: {exc}"
    if device_count < 1:
        return False, "No CUDA device detected"
    return True, ""


def _preload_cuda_wheel_libraries() -> None:
    """Load pip-installed CUDA DLLs before importing CuPy sparse extensions.

    The CUDA Toolkit normally provides one unified ``bin`` directory.  The
    ``cupy-cuda12x[ctk]`` Windows installation instead spreads runtime DLLs
    across ``site-packages/nvidia/*/bin``.  CuPy can detect the device but may
    not add those folders before loading ``cupyx.cusolver``.  The official
    ``cuda-pathfinder`` dependency resolves and loads the required DLLs.
    Handles are retained for the lifetime of the process.
    """
    if os.name != "nt" or _CUDA_WHEEL_LIBRARY_HANDLES:
        return
    try:
        handles = [
            _load_cuda_wheel_library("nvrtc"),
            _load_cuda_wheel_library("cusolver"),
        ]
    except ImportError:
        # Older CuPy installations may rely on a conventional CUDA Toolkit.
        return
    _CUDA_WHEEL_LIBRARY_HANDLES.extend(handles)


def _load_cuda_wheel_library(name: str) -> object:
    """Indirection retained for unit tests of the Windows wheel loader."""
    from cuda.pathfinder import load_nvidia_dynamic_lib

    return load_nvidia_dynamic_lib(name)


@contextmanager
def _interprocess_cuda_lock(timeout_seconds: float = 3600.0) -> Iterator[None]:
    """Use one temporary lock file to serialize CUDA regions across processes."""
    _GPU_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _GPU_LOCK_FILE.open("a+b") as handle:
        if _GPU_LOCK_FILE.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        waited = 0.0
        while True:
            try:
                _try_lock_file(handle)
                break
            except OSError:
                if waited >= timeout_seconds:
                    raise BackendComputationError("timed out waiting for the shared CUDA remesh lock")
                sleep(0.05)
                waited += 0.05
        try:
            yield
        finally:
            _unlock_file(handle)


def _try_lock_file(handle: object) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: object) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _barycentric_2d(point: np.ndarray, triangle: np.ndarray) -> np.ndarray | None:
    a, b, c = np.asarray(triangle, dtype=float)
    matrix = np.column_stack((b - a, c - a))
    determinant = float(np.linalg.det(matrix))
    if abs(determinant) < 1e-15:
        return None
    beta, gamma = np.linalg.solve(matrix, np.asarray(point, dtype=float) - a)
    return np.array([1.0 - beta - gamma, beta, gamma], dtype=float)
