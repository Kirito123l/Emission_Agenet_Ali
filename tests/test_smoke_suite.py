"""Regression tests for the evaluation smoke-suite wrapper."""
import json

from evaluation import run_smoke_suite as smoke_mod


def test_run_smoke_suite_writes_summary_with_expected_defaults(tmp_path, monkeypatch):
    calls = {}

    def fake_norm(samples_path, output_dir, enable_executor_standardization):
        calls["normalization"] = {
            "samples_path": samples_path,
            "output_dir": output_dir,
            "enable_executor_standardization": enable_executor_standardization,
        }
        return {"task": "normalization", "sample_accuracy": 1.0}

    def fake_file(samples_path, output_dir, enable_file_analyzer, enable_file_context_injection, macro_column_mapping_modes):
        calls["file_grounding"] = {
            "samples_path": samples_path,
            "output_dir": output_dir,
            "enable_file_analyzer": enable_file_analyzer,
            "enable_file_context_injection": enable_file_context_injection,
            "macro_column_mapping_modes": macro_column_mapping_modes,
        }
        return {"task": "file_grounding", "routing_accuracy": 1.0}

    def fake_end2end(
        samples_path,
        output_dir,
        mode,
        enable_file_analyzer,
        enable_file_context_injection,
        enable_executor_standardization,
        macro_column_mapping_modes,
        only_task,
    ):
        calls["end2end"] = {
            "samples_path": samples_path,
            "output_dir": output_dir,
            "mode": mode,
            "enable_file_analyzer": enable_file_analyzer,
            "enable_file_context_injection": enable_file_context_injection,
            "enable_executor_standardization": enable_executor_standardization,
            "macro_column_mapping_modes": macro_column_mapping_modes,
            "only_task": only_task,
        }
        return {"task": "end2end", "end2end_completion_rate": 1.0}

    monkeypatch.setattr(smoke_mod, "run_normalization_evaluation", fake_norm)
    monkeypatch.setattr(smoke_mod, "run_file_grounding_evaluation", fake_file)
    monkeypatch.setattr(smoke_mod, "run_end2end_evaluation", fake_end2end)

    output_dir = tmp_path / "smoke"
    summary = smoke_mod.run_smoke_suite(output_dir=output_dir)

    assert summary["suite"] == "smoke"
    assert summary["recommended_defaults"]["mode"] == "tool"
    assert summary["recommended_defaults"]["macro_column_mapping_modes"] == list(smoke_mod.DEFAULT_MACRO_MODES)
    assert calls["file_grounding"]["macro_column_mapping_modes"] == smoke_mod.DEFAULT_MACRO_MODES
    assert calls["end2end"]["mode"] == "tool"
    assert calls["end2end"]["only_task"] is None

    summary_path = output_dir / "smoke_summary.json"
    assert summary_path.exists()

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["metrics"]["normalization"]["task"] == "normalization"
    assert payload["metrics"]["file_grounding"]["task"] == "file_grounding"
    assert payload["metrics"]["end2end"]["task"] == "end2end"
