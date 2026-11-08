"""Search over a company's SEC filings, using ChromaDB.

For each ticker, the latest 10-K (annual report) and 10-Q (quarterly report)
are downloaded from SEC EDGAR, reduced to text, tagged with their section
(for example "Item 1A. Risk Factors"), split into overlapping passages, and
stored with OpenAI embeddings in a local ChromaDB. When a newer filing
appears it replaces the older one, so searches only return current reports.

SEC requires automated tools to identify themselves with a contact email, so
SEC_USER_AGENT must be set in .env, for example:

    SEC_USER_AGENT=AIMA research tool your-name@example.com

Pre-index the watchlist with `uv run index_filings`; otherwise a ticker is
indexed the first time the Advisor searches it.
"""
import os
import re
import sys
import time
import warnings
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv

load_dotenv()

# Filings are XHTML with embedded XBRL; the HTML parser reads them correctly
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

FORMS = ("10-K", "10-Q")
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
EMBED_BATCH = 100
DEFAULT_PATH = Path(__file__).parent.parent.parent / "filings_db"

_ITEM_RE = re.compile(r"^(?:part\s+i{1,3}\s*[,.\-–—]?\s*)?item\s+(\d{1,2}[a-c]?)\b\s*[.:\-–—]?\s*(.{0,90})$",
                      re.IGNORECASE)


class SecAccessError(RuntimeError):
    pass


# --- EDGAR ---

def _user_agent() -> str:
    agent = os.getenv("SEC_USER_AGENT", "").strip()
    if "@" not in agent:
        raise SecAccessError(
            "SEC requires a contact email for automated access. Add a line like "
            "'SEC_USER_AGENT=AIMA research tool your-name@example.com' to .env."
        )
    return agent


def sec_get(url: str) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=30)
    time.sleep(0.15)  # stay well under SEC's limit of 10 requests per second
    if response.status_code == 403:
        raise SecAccessError(f"SEC refused the request ({url}). Check SEC_USER_AGENT in .env.")
    response.raise_for_status()
    return response


_cik_by_ticker: dict[str, str] = {}


def lookup_cik(ticker: str) -> str:
    if not _cik_by_ticker:
        for company in sec_get("https://www.sec.gov/files/company_tickers.json").json().values():
            _cik_by_ticker[company["ticker"].upper()] = str(company["cik_str"]).zfill(10)
    try:
        return _cik_by_ticker[ticker.upper()]
    except KeyError:
        raise SecAccessError(f"{ticker} is not in SEC's list of company tickers.") from None


def latest_filings(ticker: str) -> list[dict]:
    """The most recent 10-K and 10-Q for a ticker."""
    cik = lookup_cik(ticker)
    recent = sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()["filings"]["recent"]
    found = {}
    for i, form in enumerate(recent["form"]):
        if form in FORMS and form not in found:
            accession = recent["accessionNumber"][i]
            found[form] = {
                "ticker": ticker.upper(),
                "form": form,
                "filed": recent["filingDate"][i],
                "period": recent["reportDate"][i],
                "accession": accession,
                "url": (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{accession.replace('-', '')}/{recent['primaryDocument'][i]}"),
            }
    return [found[form] for form in FORMS if form in found]


# --- text processing ---

def filing_text(html: bytes | str) -> str:
    """Readable text from a filing's HTML, without hidden XBRL data.

    Pass the raw bytes when possible, so the filing's own character encoding is
    used (decoding as Latin-1 turns curly quotes into replacement characters)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.IGNORECASE)):
        tag.decompose()
    lines = (re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def split_sections(text: str) -> list[tuple[str, str]]:
    """Splits filing text at "Item N." headings. Returns (section name, text) pairs."""
    sections, name, lines = [], "Cover and introduction", []
    for line in text.splitlines():
        heading = _ITEM_RE.match(line)
        if heading and len(line) < 120:
            if lines:
                sections.append((name, "\n".join(lines)))
            title = heading.group(2).strip(" .")
            name = f"Item {heading.group(1).upper()}" + (f". {title}" if title else "")
            lines = []
        lines.append(line)
    if lines:
        sections.append((name, "\n".join(lines)))
    return sections


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Splits text into passages of about `size` characters, breaking between lines
    where possible, with `overlap` characters repeated between neighbors."""
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            newline = text.rfind("\n", start + size // 2, end)
            if newline != -1:
                end = newline
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        # Begin the next passage at a word boundary rather than mid-word
        boundary = re.search(r"\s", text[start:start + 60])
        if boundary:
            start += boundary.end()
    return chunks


# --- the index ---

def openai_embeddings():
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
    return OpenAIEmbeddingFunction(model_name="text-embedding-3-small", api_key_env_var="OPENAI_API_KEY")


class FilingsIndex:
    def __init__(self, path: Path | str | None = None, embedding_function=None, fetch_filings=None, fetch_html=None):
        import chromadb
        path = path or os.getenv("AIMA_FILINGS_PATH") or DEFAULT_PATH
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            "sec_filings", embedding_function=embedding_function or openai_embeddings(),
            metadata={"hnsw:space": "cosine"},
        )
        self.fetch_filings = fetch_filings or latest_filings
        self.fetch_html = fetch_html or (lambda url: sec_get(url).content)
        self._checked: dict[str, date] = {}

    def is_indexed(self, accession: str) -> bool:
        return bool(self.collection.get(where={"accession": accession}, limit=1)["ids"])

    def index_ticker(self, ticker: str) -> list[str]:
        """Indexes any filing newer than what is stored. Returns a line per filing added."""
        ticker = ticker.upper()
        added = []
        for filing in self.fetch_filings(ticker):
            if self.is_indexed(filing["accession"]):
                continue
            passages, metadatas = [], []
            for section, text in split_sections(filing_text(self.fetch_html(filing["url"]))):
                for piece in chunk(text):
                    passages.append(piece)
                    metadatas.append({**{k: filing[k] for k in ("ticker", "form", "filed", "period", "accession")},
                                      "section": section})
            ids = [f"{filing['accession']}-{i}" for i in range(len(passages))]
            for start in range(0, len(passages), EMBED_BATCH):
                end = start + EMBED_BATCH
                self.collection.add(ids=ids[start:end], documents=passages[start:end], metadatas=metadatas[start:end])
            # Drop the older filing of the same form so searches only see current reports
            self.collection.delete(where={"$and": [
                {"ticker": ticker}, {"form": filing["form"]}, {"accession": {"$ne": filing["accession"]}},
            ]})
            added.append(f"{ticker} {filing['form']} filed {filing['filed']}: {len(passages)} passages")
        self._checked[ticker] = date.today()
        return added

    def search(self, ticker: str, query: str, n_results: int = 5) -> list[dict]:
        ticker = ticker.upper()
        if self._checked.get(ticker) != date.today():
            self.index_ticker(ticker)
        result = self.collection.query(query_texts=[query], n_results=n_results, where={"ticker": ticker})
        return [{"text": text, **meta} for text, meta in zip(result["documents"][0], result["metadatas"][0])]


_index: FilingsIndex | None = None


def get_index() -> FilingsIndex:
    global _index
    if _index is None:
        _index = FilingsIndex()
    return _index


def main():
    """uv run index_filings [TICKER ...]: indexes the given tickers, or the watchlist."""
    tickers = sys.argv[1:]
    if not tickers:
        from first_ai_agents.watchlist import load_watchlist
        tickers = load_watchlist()["tickers"]
    index = get_index()
    for ticker in tickers:
        try:
            added = index.index_ticker(ticker)
            print("\n".join(added) if added else f"{ticker.upper()} is already up to date")
        except Exception as e:
            print(f"{ticker.upper()} error: {e}")


if __name__ == "__main__":
    main()
