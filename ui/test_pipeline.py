import json
from pathlib import Path
import pytest
import pipeline


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    proj = tmp_path / "edit-fake"
    proj.mkdir()
    edl = {
        "version": 1,
        "sources": {"MAIN": str(tmp_path / "bruto" / "fake.mkv")},
        "ranges": [
            {"source": "MAIN", "start": 1.0, "end": 3.0},
            {"source": "MAIN", "start": 5.0, "end": 8.0},
        ],
        "grade": "", "total_duration_s": 10.0, "overlays": [],
    }
    (proj / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    (proj / "zooms.json").write_text("[1.0, 1.05]", encoding="utf-8")
    tdir = proj / "transcripts"
    tdir.mkdir()
    words = [
        {"text": "Oi", "start": 1.0, "end": 1.2, "type": "word"},
        {"text": " ", "start": 1.2, "end": 1.25, "type": "spacing"},
        {"text": "gente", "start": 1.25, "end": 1.6, "type": "word"},
        # gap de 0.9s => quebra de frase
        {"text": "Agora", "start": 2.5, "end": 2.9, "type": "word"},
    ]
    (tdir / "fake.json").write_text(
        json.dumps({"text": "Oi gente Agora", "words": words,
                    "audio_duration_secs": 10.0}), encoding="utf-8")
    (proj / "master.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nOi gente\n\n"
        "2\n00:00:02,000 --> 00:00:04,500\nAgora\n", encoding="utf-8")
    (proj / "preview.mp4").write_bytes(b"\x00" * 16)
    (tmp_path / "bruto").mkdir()
    (tmp_path / "Formatos").mkdir()
    (tmp_path / "Formatos" / "padrao-youtube.md").write_text("# receita",
                                                             encoding="utf-8")
    return tmp_path


def test_find_projects(fake_root):
    projs = pipeline.find_projects(fake_root)
    assert projs == [{"id": "edit-fake", "name": "edit-fake",
                      "has_preview": True, "has_final": False}]


def test_project_dir_rejects_escape(fake_root):
    with pytest.raises(ValueError):
        pipeline.project_dir(fake_root, "../fora")


def test_phrases_split_on_gap(fake_root):
    tr = json.loads((fake_root / "edit-fake" / "transcripts" /
                     "fake.json").read_text(encoding="utf-8"))
    ph = pipeline.phrases_from_transcript(tr)
    assert [p["text"] for p in ph] == ["Oi gente", "Agora"]
    assert ph[0]["start"] == 1.0 and ph[0]["end"] == 1.6


def test_parse_srt(fake_root):
    srt = (fake_root / "edit-fake" / "master.srt").read_text(encoding="utf-8")
    subs = pipeline.parse_srt(srt)
    assert subs[1] == {"start": 2.0, "end": 4.5, "text": "Agora"}


def test_load_project_payload(fake_root):
    p = pipeline.load_project(fake_root, "edit-fake")
    assert len(p["edl"]["ranges"]) == 2
    assert p["zooms"] == [1.0, 1.05]
    assert p["phrases"][0]["text"] == "Oi gente"
    assert p["state"] == {}
    assert p["queue"] == []
    assert p["claude_online"] is False
    assert p["source_duration"] == 10.0
