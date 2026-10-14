"""Real Singapore speech: transcripts from the IMDA National Speech Corpus (NSC).

    python -m data.nsc                  # -> data/nsc/part{3,4,5,6}.jsonl   text only, about 1 MB each (skips existing)
    python -m data.nsc --bank --audio   # -> data/nsc/bank_clips.jsonl + audio/: bank-themed Part 6 clips with audio
    python -m data.nsc --heldout        # -> data/nsc/heldout.jsonl (+ .sha256): unseen Part 3-4 training clips
    python -m data.nsc --bank-test      # -> data/nsc/bank_test_raw.txt: unseen Part 6 training bank clips to label
    python -m data.nsc --bank-test2     # -> data/nsc/bank_test2_raw.txt: the next 150, the test for fixes made on the first

Source: MERaLiON/Multitask-National-Speech-Corpus-v1, the ASR-PART{n}-Test configs (1,000 clips of about 30 s
each, with reference transcripts), read through the Hugging Face dataset viewer API, so only the rows' text is
fetched, and audio only when asked for. (The recursal/reprocessed_singapore_national_speech_corpus mirror's
Part 5-6 transcripts are empty and its tars interleave audio.) Licence: Singapore Open Data Licence v1.0;
attribute IMDA. Not committed to git.

    Part 3  everyday conversations between pairs (same room, or separate rooms over a telephone line)
    Part 4  conversations with code-switching into Mandarin, Malay or Tamil
    Part 5  debates, finance talk, positive and negative emotion
    Part 6  role-played service calls: banks / telcos / insurance, HDB / MOE / MSF, hotels / holidays / restaurants

None of it has PII labels.
"""

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "nsc"
API = "https://datasets-server.huggingface.co/rows"
DATASET = "MERaLiON/Multitask-National-Speech-Corpus-v1"
PARTS = (3, 4, 5, 6)
BANK = ["bank", "account", "savings", "current account", "credit card", "debit card", "card", "loan", "mortgage",
        "interest", "fixed deposit", "transfer", "remittance", "otp", "pin", "atm", "cheque", "overdraft",
        "balance", "statement", "withdraw", "deposit", "paynow", "giro", "nric", "branch"]
OTHER = ["insurance", "policy", "premium", "claim", "coverage", "insured", "plan", "data", "mobile line",
         "roaming", "broadband", "sim", "contract", "telco", "handset",
         # the other two Part 6 designs: HDB / MOE / MSF and holidays / hotels / restaurants
         "hdb", "flat", "bto", "grant", "school", "edusave", "bursary", "moe", "msf", "ministry", "student",
         "hotel", "holiday", "booking", "restaurant", "reservation", "travel", "flight", "package"]


def _count(words, text):
    return sum(len(re.findall(rf"\b{re.escape(w)}\b", text)) for w in words)


def is_bank(text: str) -> bool:
    """ponytail: keyword vote (the clips carry no domain label); check a sample by hand before relying on it."""
    low = text.lower()
    bank = _count(BANK, low)
    return bank >= 2 and bank > _count(OTHER, low)


def rows(config: str):
    offset = 0
    while True:
        q = urllib.parse.urlencode({"dataset": DATASET, "config": config, "split": "train", "offset": offset, "length": 100})
        for attempt in range(8):                        # the viewer API returns the odd 502/503
            try:
                page = json.load(urllib.request.urlopen(f"{API}?{q}", timeout=60))
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 7:
                    raise
                time.sleep(min(30, 2 ** attempt))
        yield from page["rows"]
        offset += len(page["rows"])
        if not page["rows"] or offset >= page["num_rows_total"]:
            return
        time.sleep(0.5)                                 # be polite to the viewer API


def clean(text: str) -> str:
    """NSC transcription conventions -> plain speech text, as an ASR system would emit it.
    (um) [lah] #Tampines# !wah! -> um lah Tampines wah; <mandarin>我们:wo men</mandarin> -> wo men; n_t_u -> n t u; hong-kong -> hong kong;
    cut-off words (ha~) and noise tags (<s/>, <c/>, <UNK>) dropped."""
    text = re.sub(r"<(\w+)>[^<:]*:([^<]*)</\1>", r"\2", text)       # code-switched span: keep the romanisation
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\S*~", " ", text)
    text = re.sub(r"[()\[\]#!]", "", text)                       # #proper noun#, !interjection!
    text = re.sub(r"(?<=\w)[_-](?=\w)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def utterances(answer: str) -> list[dict]:
    """'<Speaker1>: ...\\n<Speaker2>: ...' -> [{speaker, text}]. Which speaker is the agent is not labelled."""
    out = []
    parts = re.split(r"<Speaker(\d+)>:", answer)          # test splits put a turn per line, training splits inline
    for speaker, said in zip(["1"] + parts[1::2], parts[0::2]):
        if (said := clean(said)):
            out.append({"speaker": f"speaker{speaker}", "text": said})
    return out


def fetch(part: int, keep=lambda answer: True, audio_dir: Path | None = None) -> list[dict]:
    kept = []
    for r in rows(f"ASR-PART{part}-Test"):
        answer = r["row"]["answer"]
        if not keep(answer) or not utterances(answer):
            continue
        c = {"id": f"NSC{part}T{r['row_idx']:04d}", "part": part, "answer": answer}     # raw: cleaned on load
        if audio_dir and (src := (r["row"]["context"] or [{}])[0].get("src")):
            urllib.request.urlretrieve(src, audio_dir / f"{c['id']}.wav")     # signed URLs expire: fetch now
        kept.append(c)
    return kept


def write(path: Path, calls: list[dict]) -> None:
    with open(path, "w") as f:
        f.writelines(json.dumps(c) + "\n" for c in calls)


def load(part: int | str) -> list[dict]:
    path = OUT / (f"part{part}.jsonl" if isinstance(part, int) else f"{part}.jsonl")
    if not path.exists():
        raise SystemExit(f"{path} is missing: run `python -m data.nsc` first")
    return [c | {"utterances": utterances(c["answer"])} for c in map(json.loads, open(path))]


# Held out from the round-4 detector fixes, which were designed on the Part 3-6 test sets: 500 clips from
# the middle shard of each of the Part 3 and Part 4 training splits, hashed when fetched and scored once.
# The viewer API does not serve rows that deep, so the parquet shard is read directly, transcript column
# only (HTTP range requests; no audio is downloaded).
HELDOUT_PER_PART = 500
BANK_TEST = 150


def _train_answers(part: int, n: int, keep=lambda answer: True) -> list[tuple[str, str]]:
    """The first n kept clips, reading shards from the middle one onwards."""
    import pyarrow.parquet as pq                       # requirements-experiments.txt
    from huggingface_hub import HfFileSystem
    fs = HfFileSystem()
    files = sorted(fs.ls(f"datasets/{DATASET}/ASR-PART{part}-Train", detail=False))
    out = []
    for shard in files[len(files) // 2:]:
        f, row = pq.ParquetFile(fs.open(shard, block_size=2**20)), 0
        for g in range(f.metadata.num_row_groups):
            for a in f.read_row_group(g, columns=["answer"]).column("answer").to_pylist():
                if keep(a):
                    out.append((f"NSC{part}Tr{re.search(r'(\d+)-of-', shard)[1]}-{row:04d}", a))
                row += 1
            if len(out) >= n:
                return out[:n]
    return out


def heldout() -> list[dict]:
    path, h = OUT / "heldout.jsonl", OUT / "heldout.jsonl.sha256"
    if hashlib.sha256(path.read_bytes()).hexdigest() != h.read_text().split()[0]:
        raise SystemExit(f"{path} changed since it was frozen")
    return load("heldout")


def main(argv: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    if "--heldout" in argv:
        path = OUT / "heldout.jsonl"
        write(path, [{"id": cid, "part": part, "answer": a} for part in (3, 4)
                     for cid, a in _train_answers(part, HELDOUT_PER_PART) if utterances(a)])
        (OUT / "heldout.jsonl.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  heldout.jsonl\n")
        print(f"froze {path}")
        return
    if "--bank-test" in argv or "--bank-test2" in argv:
        # Labelled by hand into bank_test*.txt (data/heldout.py format) before any detector runs on it.
        second = "--bank-test2" in argv
        with open(OUT / f"bank_test{'2' if second else ''}_raw.txt", "w") as f:
            for cid, a in _train_answers(6, 2 * BANK_TEST, is_bank)[BANK_TEST if second else 0:][:BANK_TEST]:
                f.write(f"### {cid} low\n" + "".join(f"{'A' if u['speaker'] == 'speaker1' else 'C'}: {u['text']}\n"
                                                    for u in utterances(a)))
        print(f"{BANK_TEST} clips -> {f.name}")
        return
    if "--bank" in argv:
        audio = OUT / "audio" if "--audio" in argv else None
        if audio:
            audio.mkdir(exist_ok=True)
        write(OUT / "bank_clips.jsonl", calls := fetch(6, is_bank, audio))
        print(f"{len(calls)} bank clips -> {OUT / 'bank_clips.jsonl'}")
        return
    for part in PARTS:
        if (OUT / f"part{part}.jsonl").exists():      # delete a file to fetch it again
            continue
        write(OUT / f"part{part}.jsonl", calls := fetch(part))
        print(f"Part {part}: {len(calls)} clips")


if __name__ == "__main__":
    main(sys.argv[1:])
