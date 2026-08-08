from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / "assets" / "voice-cache"


def test_validated_voice_cache_is_bundled():
    files = list(CACHE.glob("*.spk"))
    assert len(files) == 1
    stem = files[0].stem
    assert (CACHE / f"{stem}.rvq").stat().st_size > 0
    assert (CACHE / f"{stem}.json").stat().st_size > 0
    assert files[0].stat().st_size > 0


def test_runpod_pipeline_prefers_cached_reference():
    script = (REPO_ROOT / "scripts" / "runpod-pipeline.sh").read_text(encoding="utf-8")
    assert "qwen3_tts_ref_spk" in script
    assert "qwen3_tts_ref_rvq" in script
    assert "QWEN3_TTS_REF_SPK" in script
