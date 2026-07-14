"""Batch-only Tkinter interface for ear coordinate alignment."""

from __future__ import annotations

import queue
import re
import threading
import traceback
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk

from .batch import BatchAlignmentResult, batch_align_and_export, sample_key
from .pipeline import DEFAULT_LANDMARK_IDS
from .settings import load_settings, save_reference_template


class EarAlignApp:
    """Desktop form with one unambiguous batch-processing workflow."""

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("耳模型批量坐标变换与 OBJ/STL 导出")
        self.root.geometry("940x620")
        self.root.minsize(800, 560)

        saved = load_settings()
        self.reference_model = StringVar(value=str(saved.get("reference_model", "")))
        self.reference_csv = StringVar(value=str(saved.get("reference_csv", "")))
        self.output_directory = StringVar(
            value=str(saved.get("output_directory") or (Path.cwd() / "output"))
        )
        self.batch_models_text = StringVar(value="尚未选择")
        self.batch_csvs_text = StringVar(value="尚未选择")
        self.landmark_ids = StringVar(value=" ".join(DEFAULT_LANDMARK_IDS))
        self.auto_mirror = BooleanVar(value=True)
        self.mirror_axis = StringVar(value="x")
        restored = bool(self.reference_model.get() and self.reference_csv.get())
        self.status = StringVar(
            value="已恢复上一次参考模板。请选择本批次模型和 CSV。"
            if restored
            else "请选择参考模板、本批次模型和 CSV。"
        )
        self.batch_model_paths: list[str] = []
        self.batch_csv_paths: list[str] = []
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        self._build()
        self.root.after(100, self._poll_events)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="耳模型批量坐标变换",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(
            frame,
            text="一次选择全部待处理模型和 landmarks CSV；程序按样本文件名自动匹配并批量导出。",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))

        rows = [
            ("参考耳模型", self.reference_model, self._choose_reference_model, "浏览…"),
            ("参考耳标定点 CSV", self.reference_csv, self._choose_reference_csv, "浏览…"),
            ("本批次耳模型", self.batch_models_text, self._choose_batch_models, "选择多个…"),
            ("本批次标定点 CSV", self.batch_csvs_text, self._choose_batch_csvs, "选择多个…"),
            ("输出目录", self.output_directory, self._choose_output_directory, "浏览…"),
        ]
        for index, (label, variable, command, button_text) in enumerate(rows, start=2):
            ttk.Label(frame, text=label).grid(
                row=index, column=0, sticky="w", padx=(0, 12), pady=6
            )
            state = "readonly" if variable in (self.batch_models_text, self.batch_csvs_text) else "normal"
            ttk.Entry(frame, textvariable=variable, state=state).grid(
                row=index, column=1, sticky="ew", pady=6
            )
            ttk.Button(frame, text=button_text, command=command).grid(
                row=index, column=2, padx=(10, 0), pady=6
            )

        options = ttk.LabelFrame(frame, text="坐标变换设置", padding=12)
        options.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(14, 10))
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="用于计算 R、t 的点").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Entry(options, textvariable=self.landmark_ids).grid(
            row=0, column=1, columnspan=3, sticky="ew"
        )
        ttk.Checkbutton(
            options,
            text="左右耳不同时自动镜像",
            variable=self.auto_mirror,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(options, text="镜像轴").grid(
            row=1, column=2, padx=(18, 6), pady=(10, 0)
        )
        ttk.Combobox(
            options,
            textvariable=self.mirror_axis,
            values=("x", "y", "z"),
            state="readonly",
            width=5,
        ).grid(row=1, column=3, pady=(10, 0))
        ttk.Label(
            options,
            text="✓ 固定将参考标定点中心平移到 (0, 0, 0)，所有批量结果使用同一坐标原点。",
            foreground="#1f6f43",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))

        note = (
            "匹配示例：T068_L.stl ↔ T068_L_landmarks.csv。默认使用 L7、L13、L15、L26；"
            "CSV 可包含其他点。若误将参考模型或参考 CSV 选入批次，程序会自动排除。"
        )
        ttk.Label(frame, text=note, wraplength=880, foreground="#555555").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )

        actions = ttk.Frame(frame)
        actions.grid(row=9, column=0, columnspan=3, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(
            actions,
            text="开始批量坐标变换",
            command=self._start_batch,
        )
        self.run_button.grid(row=0, column=1, padx=(12, 0))

        self.details = ttk.Treeview(frame, columns=("value",), show="tree headings", height=8)
        self.details.heading("#0", text="样本/结果")
        self.details.heading("value", text="状态、误差和输出路径")
        self.details.column("#0", width=170, stretch=False)
        self.details.column("value", width=680)
        self.details.grid(row=10, column=0, columnspan=3, sticky="nsew", pady=(14, 0))
        frame.rowconfigure(10, weight=1)

    @staticmethod
    def _model_types() -> list[tuple[str, str]]:
        return [("三维模型", "*.obj *.stl *.ply"), ("所有文件", "*.*")]

    @staticmethod
    def _csv_types() -> list[tuple[str, str]]:
        return [("CSV 标定点", "*.csv"), ("所有文件", "*.*")]

    def _choose_reference_model(self) -> None:
        selected = filedialog.askopenfilename(parent=self.root, filetypes=self._model_types())
        if selected:
            self.reference_model.set(selected)
            self._remember_reference()
            self._refresh_selection_status()

    def _choose_reference_csv(self) -> None:
        selected = filedialog.askopenfilename(parent=self.root, filetypes=self._csv_types())
        if selected:
            self.reference_csv.set(selected)
            self._remember_reference()
            self._refresh_selection_status()

    def _choose_batch_models(self) -> None:
        selected = list(
            filedialog.askopenfilenames(
                parent=self.root,
                title="选择本批次全部 OBJ/STL/PLY",
                filetypes=self._model_types(),
            )
        )
        if selected:
            self.batch_model_paths = selected
            self.batch_models_text.set(self._selection_label(selected))
            self._refresh_selection_status()

    def _choose_batch_csvs(self) -> None:
        selected = list(
            filedialog.askopenfilenames(
                parent=self.root,
                title="选择本批次全部 landmarks CSV",
                filetypes=self._csv_types(),
            )
        )
        if selected:
            self.batch_csv_paths = selected
            self.batch_csvs_text.set(self._selection_label(selected))
            self._refresh_selection_status()

    def _choose_output_directory(self) -> None:
        selected = filedialog.askdirectory(parent=self.root)
        if selected:
            self.output_directory.set(selected)
            self._remember_reference()

    @staticmethod
    def _selection_label(paths: list[str]) -> str:
        names = [Path(path).name for path in paths]
        preview = "；".join(names[:3])
        if len(names) > 3:
            preview += f"；…另 {len(names) - 3} 个"
        return f"已选择 {len(names)} 个：{preview}"

    @staticmethod
    def _resolved(path: str | Path) -> Path:
        return Path(path).resolve(strict=False)

    def _filtered_batch_paths(self) -> tuple[list[str], list[str]]:
        reference_model = self._resolved(self.reference_model.get().strip())
        reference_csv = self._resolved(self.reference_csv.get().strip())
        models = [
            path for path in self.batch_model_paths if self._resolved(path) != reference_model
        ]
        csvs = [path for path in self.batch_csv_paths if self._resolved(path) != reference_csv]
        return models, csvs

    def _matching_counts(self, models: list[str], csvs: list[str]) -> tuple[int, int, int]:
        model_keys = {sample_key(path) for path in models}
        csv_keys = {sample_key(path) for path in csvs}
        return (
            len(model_keys & csv_keys),
            len(model_keys - csv_keys),
            len(csv_keys - model_keys),
        )

    def _refresh_selection_status(self) -> None:
        if not self.batch_model_paths and not self.batch_csv_paths:
            return
        models, csvs = self._filtered_batch_paths()
        matched, missing_csv, extra_csv = self._matching_counts(models, csvs)
        self.status.set(
            f"批次预检：可匹配 {matched}，缺少 CSV {missing_csv}，多余 CSV {extra_csv}。"
        )

    def _remember_reference(self) -> None:
        try:
            save_reference_template(
                self.reference_model.get().strip(),
                self.reference_csv.get().strip(),
                self.output_directory.get().strip(),
            )
        except OSError as exc:
            self.status.set(f"参考模板记忆保存失败：{exc}")

    def _inputs(self) -> tuple[Path, Path, Path, tuple[str, ...], list[str], list[str]]:
        reference_model = Path(self.reference_model.get().strip())
        reference_csv = Path(self.reference_csv.get().strip())
        for label, path in (("参考耳模型", reference_model), ("参考耳 CSV", reference_csv)):
            if not path.is_file():
                raise ValueError(f"{label}不存在或尚未选择：{path}")
        output_text = self.output_directory.get().strip()
        if not output_text:
            raise ValueError("请选择输出目录")
        ids = tuple(
            item.upper()
            for item in re.split(r"[,，;；\s]+", self.landmark_ids.get().strip())
            if item
        )
        if len(ids) < 3:
            raise ValueError("至少需要 3 个非共线的对应标定点")
        models, csvs = self._filtered_batch_paths()
        if not models:
            raise ValueError("尚未选择待批量处理的模型")
        if not csvs:
            raise ValueError("尚未选择待批量处理的 landmarks CSV")
        for path in models + csvs:
            if not Path(path).is_file():
                raise ValueError(f"所选批次文件不存在：{path}")
        return reference_model, reference_csv, Path(output_text), ids, models, csvs

    def _start_batch(self) -> None:
        try:
            ref_model, ref_csv, output, ids, models, csvs = self._inputs()
        except Exception as exc:
            messagebox.showerror("输入有误", str(exc), parent=self.root)
            return

        matched, missing_csv, extra_csv = self._matching_counts(models, csvs)
        if matched == 0:
            messagebox.showerror(
                "无法匹配",
                "没有任何模型能按文件名匹配到 CSV。\n\n"
                "例如：T068_L.stl 应对应 T068_L_landmarks.csv。",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "确认批量坐标变换",
            f"待处理模型：{len(models)}\nCSV：{len(csvs)}\n"
            f"可匹配：{matched}\n缺少 CSV：{missing_csv}\n多余 CSV：{extra_csv}\n\n"
            "所有成功样本都会以参考四点中心为坐标原点。是否开始？",
            parent=self.root,
        ):
            return

        output.mkdir(parents=True, exist_ok=True)
        self._remember_reference()
        auto_mirror = self.auto_mirror.get()
        mirror_axis = self.mirror_axis.get()
        self.run_button.configure(state="disabled")
        self.status.set(f"正在批量处理 {len(models)} 个模型…")
        for item in self.details.get_children():
            self.details.delete(item)

        def worker() -> None:
            try:
                result = batch_align_and_export(
                    ref_mesh_path=ref_model,
                    ref_landmark_csv=ref_csv,
                    moving_mesh_paths=models,
                    moving_landmark_csv_paths=csvs,
                    output_directory=output,
                    landmark_ids=ids,
                    auto_mirror=auto_mirror,
                    mirror_axis=mirror_axis,
                    center_reference=True,
                )
                self.events.put(("success", result))
            except Exception as exc:
                self.events.put(("error", (exc, traceback.format_exc())))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            event, payload = self.events.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_events)
            return

        self.run_button.configure(state="normal")
        if event == "success":
            self._show_success(payload)  # type: ignore[arg-type]
        else:
            error, details = payload  # type: ignore[misc]
            self.status.set("批量运行失败，请检查输入。")
            messagebox.showerror(
                "处理失败",
                f"{error}\n\n详细信息：\n{details}",
                parent=self.root,
            )
        self.root.after(100, self._poll_events)

    def _show_success(self, result: BatchAlignmentResult) -> None:
        self.status.set(
            f"批量完成：成功 {result.success_count}，失败 {result.failure_count}，"
            f"未匹配 CSV {len(result.unmatched_csv_paths)}。"
        )
        self.details.insert("", "end", text="批量汇总", values=(str(result.summary_path),))
        for item in result.items:
            if item.result is not None:
                value = (
                    f"成功；RMS={float(item.result.metrics['rms_error']):.6g}；"
                    f"{item.result.output_obj_path}"
                )
            else:
                value = f"失败；{item.error}"
            self.details.insert("", "end", text=item.sample_id, values=(value,))
        message = (
            f"成功：{result.success_count}\n失败：{result.failure_count}\n"
            f"未匹配 CSV：{len(result.unmatched_csv_paths)}\n\n汇总：{result.summary_path}"
        )
        if result.failure_count:
            messagebox.showwarning("批量处理完成（有失败项）", message, parent=self.root)
        else:
            messagebox.showinfo("批量处理完成", message, parent=self.root)


def main() -> None:
    root = Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except Exception:
        pass
    EarAlignApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

