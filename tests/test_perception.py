from datetime import datetime

from app.perception import HAZARD_TAXONOMY, dhash, exif_facts, hamming, sniff, vision_hazards
from app.synthetic import photo, reencode


def test_signatures():
    assert sniff(photo()) == "image/jpeg"
    assert sniff(b"<script>alert(1)</script>") is None


def test_perceptual_hash_separates_new_scene_from_reused_photo():
    before, after = photo("before"), photo("after")
    assert hamming(dhash(before), dhash(reencode(before))) <= 10
    assert hamming(dhash(before), dhash(after)) > 10


def test_exif_time_and_gps_round_trip():
    facts = exif_facts(photo(captured_at=datetime(2026, 10, 17, 9, 30), lat=3.139, lon=101.6869))
    assert facts["captured_at"].startswith("2026-10-17T09:30") and abs(facts["lat"] - 3.139) < 1e-4


class Vision:
    def complete_vision(self, system, text, uri, schema):
        assert "<data>" in text
        return {"hazards": [{"label": "unprotected_edge", "confidence": 0.9, "visible_evidence": "open slab edge"},
                            {"label": "alien_invasion", "confidence": 0.99, "visible_evidence": "x"},
                            {"label": "missing_ppe", "confidence": 0.2, "visible_evidence": "maybe"}]}


def test_vision_output_is_filtered_by_taxonomy_and_confidence():
    kept = vision_hazards(Vision(), photo(), "image/jpeg", "note")["hazards"]
    assert [h["label"] for h in kept] == ["unprotected_edge"] and kept[0]["label"] in HAZARD_TAXONOMY
