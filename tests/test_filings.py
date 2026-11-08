import math
import re

import pytest
from chromadb.api.types import EmbeddingFunction

import first_ai_agents.filings as filings
import first_ai_agents.tools.custom_tool as tools


class WordEmbeddings(EmbeddingFunction):
    """Stand-in for OpenAI embeddings: hashed word counts, so passages that share words match."""

    def __init__(self):
        pass

    def __call__(self, input):
        vectors = []
        for text in input:
            v = [0.0] * 256
            for word in re.findall(r"[a-z]+", text.lower()):
                v[hash(word) % 256] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / norm for x in v])
        return vectors

    @staticmethod
    def name():
        return "word-test"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return WordEmbeddings()


def filing_html(revenue_line: str) -> str:
    return f"""<html><body>
    <ix:header><ix:hidden>dei:EntityRegistrantName NVIDIA hidden xbrl facts</ix:hidden></ix:header>
    <div style="display:none">hidden boilerplate</div>
    <p>NVIDIA Corporation</p>
    <p>PART I</p>
    <p>Item 1A. Risk Factors</p>
    <p>Export controls on chips sold to China could reduce our data center revenue.</p>
    <p>We depend on a small number of suppliers for advanced packaging.</p>
    <p>Item 7. Management's Discussion and Analysis</p>
    <p>{revenue_line}</p>
    </body></html>"""


def make_filing(ticker, form, accession, filed):
    return {"ticker": ticker, "form": form, "filed": filed, "period": filed, "accession": accession,
            "url": f"https://sec.example/{accession}.htm"}


@pytest.fixture
def index(tmp_path):
    state = {
        "filings": {
            "NVDA": [make_filing("NVDA", "10-K", "0001-25-000001", "2026-02-25"),
                     make_filing("NVDA", "10-Q", "0001-26-000075", "2026-08-26")],
            "AAPL": [make_filing("AAPL", "10-K", "0002-25-000010", "2025-10-31")],
        },
        "html": {
            "0001-25-000001": filing_html("Revenue grew 114 percent driven by data center demand."),
            "0001-26-000075": filing_html("Quarterly revenue rose 56 percent; gaming revenue declined."),
            "0002-25-000010": filing_html("iPhone revenue was flat while services revenue grew."),
        },
        "html_requests": 0,
    }

    def fetch_html(url):
        state["html_requests"] += 1
        return state["html"][url.rsplit("/", 1)[1].removesuffix(".htm")]

    idx = filings.FilingsIndex(path=tmp_path / "chroma", embedding_function=WordEmbeddings(),
                               fetch_filings=lambda ticker: state["filings"][ticker], fetch_html=fetch_html)
    idx.state = state
    return idx


def test_filing_text_drops_hidden_xbrl():
    text = filings.filing_text(filing_html("Revenue grew."))
    assert "Export controls" in text and "Revenue grew." in text
    assert "hidden xbrl" not in text and "hidden boilerplate" not in text


def test_split_sections():
    sections = dict(filings.split_sections(filings.filing_text(filing_html("Revenue grew."))))
    assert "Export controls" in sections["Item 1A. Risk Factors"]
    assert "Revenue grew." in sections["Item 7. Management's Discussion and Analysis"]
    assert "NVIDIA Corporation" in sections["Cover and introduction"]


def test_chunk_sizes_and_overlap():
    text = "\n".join(f"Line {i} " + "x" * 90 for i in range(100))
    pieces = filings.chunk(text, size=1000, overlap=200)
    assert len(pieces) > 1
    assert all(len(p) <= 1000 for p in pieces)
    assert pieces[0][-150:] in text and pieces[1][:50] in pieces[0]  # neighbors overlap
    assert filings.chunk("") == []


def test_index_and_search_cites_form_and_section(index):
    results = index.search("nvda", "export controls risk")
    assert results[0]["form"] in ("10-K", "10-Q")
    assert results[0]["section"] == "Item 1A. Risk Factors"
    assert "Export controls" in results[0]["text"]
    assert all(r["ticker"] == "NVDA" for r in results)


def test_search_stays_within_the_ticker(index):
    index.index_ticker("NVDA")
    results = index.search("AAPL", "revenue")
    assert results and all(r["ticker"] == "AAPL" for r in results)


def test_already_indexed_filings_are_skipped(index):
    assert len(index.index_ticker("NVDA")) == 2
    requests_after_first = index.state["html_requests"]
    assert index.index_ticker("NVDA") == []
    assert index.state["html_requests"] == requests_after_first


def test_a_newer_filing_replaces_the_older_one(index):
    index.index_ticker("NVDA")
    index.state["filings"]["NVDA"][1] = make_filing("NVDA", "10-Q", "0001-26-000099", "2026-11-20")
    index.state["html"]["0001-26-000099"] = filing_html("Quarterly revenue rose 70 percent.")
    added = index.index_ticker("NVDA")
    assert added == ["NVDA 10-Q filed 2026-11-20: " + added[0].split(": ")[1]]
    stored = {m["accession"] for m in index.collection.get(where={"ticker": "NVDA"})["metadatas"]}
    assert stored == {"0001-25-000001", "0001-26-000099"}


def test_missing_contact_email_is_explained(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "")
    with pytest.raises(filings.SecAccessError, match="contact email"):
        filings._user_agent()
    monkeypatch.setenv("SEC_USER_AGENT", "AIMA research tool someone@example.com")
    assert filings._user_agent() == "AIMA research tool someone@example.com"


def test_tool_formats_passages(index, monkeypatch):
    monkeypatch.setattr(filings, "_index", index)
    result = tools.search_sec_filings.run(ticker="nvda", query="export controls risk")
    assert result.startswith('Passages from NVDA\'s SEC filings for "export controls risk":')
    assert "filed 2026-" in result and "Item 1A. Risk Factors" in result


def test_tool_falls_back_when_filings_are_unavailable(monkeypatch):
    class Broken:
        def search(self, ticker, query):
            raise filings.SecAccessError("SEC requires a contact email")
    monkeypatch.setattr(filings, "_index", Broken())
    result = tools.search_sec_filings.run(ticker="nvda", query="risks")
    assert "unavailable for NVDA" in result and "Continue without them" in result
