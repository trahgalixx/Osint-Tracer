"""Uji jalur Claude dengan klien tiruan (tanpa jaringan). Jalankan: python -m tests.test_llm"""
import json
import os
from types import SimpleNamespace as NS

import anthropic

from sample.make_sample import make
from tracer import llm
from tracer.analyze import analyze

CALLS = []


class FakeMessages:
    def create(self, **kw):
        CALLS.append(kw)
        assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
        assert kw["output_config"]["format"]["type"] == "json_schema"
        assert "<data>" in kw["messages"][0]["content"]
        schema = kw["output_config"]["format"]["schema"]
        if len(CALLS) == 2:  # simulasikan penolakan satu kali
            return NS(stop_reason="refusal", content=[])
        out = {k: ([] if v["type"] == "array" else ("sedang" if "enum" in v else f"isi {k}"))
               for k, v in schema["properties"].items()}
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(out))])


class FakeClient:
    def __init__(self, *a, **k):
        self.beta = NS(messages=FakeMessages())


def main():
    anthropic.Anthropic = FakeClient
    os.environ["ANTHROPIC_API_KEY"] = "test"
    posts = make()
    res = analyze(posts)
    llm.enrich(res, {p.id: p for p in posts}, max_narratives=3)
    got = [n["id"] for n in res["narratives"] if "llm" in n]
    assert len(got) == 2, got                      # 3 narasi, 1 ditolak → 2 diperkaya
    assert res["llm_overall"]["confidence"] == "sedang"
    assert len(CALLS) == 4                         # 3 narasi + 1 penilaian keseluruhan
    print("OK  — narasi diperkaya:", got, "| penolakan ditangani | penilaian keseluruhan ada")


if __name__ == "__main__":
    main()
