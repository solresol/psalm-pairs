# build_psalms_from_tanachus_xml.py
import io, json, re, zipfile, unicodedata, requests
from xml.etree import ElementTree as ET

XML_ZIP_URL = "https://www.tanach.us/Books/Tanach.xml.zip"  # Technical page lists this
BOOK_NAME_CANDIDATES = ("Psalms.xml", "Tehillim.xml")        # robust if naming differs

def strip_bidi_and_cgj(s: str) -> str:
    # remove bidi controls + CGJ + NBSP -> space
    bidi = dict.fromkeys(map(ord, [
        "\u200e","\u200f","\u202a","\u202b","\u202c","\u202d","\u202e",
        "\u2066","\u2067","\u2068","\u2069","\ufeff","\u034f"
    ]), None)
    s = s.translate(bidi).replace("\u00a0", " ")
    return s

def strip_diacritics(s: str) -> str:
    # removes niqqud + cantillation (all Mn combining marks)
    return "".join(ch for ch in unicodedata.normalize("NFD", s)
                   if unicodedata.category(ch) != "Mn")

def fetch_psalms_xml_bytes():
    r = requests.get(XML_ZIP_URL, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        # find Psalms.xml regardless of path case
        names = z.namelist()
        target = None
        for cand in BOOK_NAME_CANDIDATES:
            target = next((n for n in names if n.lower().endswith("/"+cand.lower()) or n.lower().endswith(cand.lower())), None)
            if target: break
        if not target:
            raise FileNotFoundError(f"Could not find Psalms XML; in archive I see: {names[:5]} ...")
        return z.read(target)

def iter_psalms(psalms_xml_bytes):
    # XML may carry namespaces; we’ll match on localnames (“endswith”)
    root = ET.fromstring(psalms_xml_bytes)
    def local(tag): return tag.split("}")[-1]
    # Chapters are often <c n="…">; verses <v n="…">. Fall back to any element whose localname matches.
    chapters = [e for e in root.iter() if local(e.tag) in ("c","chapter")]
    if not chapters:
        # Some builds nest verses directly under a book-level element; we can infer chapters by the verse's chapter @n (rare).
        verses = [e for e in root.iter() if local(e.tag) in ("v","verse")]
        # try to bucket by the chapter attribute on verse elements if present (not guaranteed)
        buckets = {}
        for v in verses:
            vnum = v.attrib.get("n")
            # when only verse @n exists, we can’t reconstruct chapters safely → bail out
            raise RuntimeError("Could not find chapter elements. Please share a sample of Psalms.xml so I can adjust the selector.")
    for c in chapters:
        cnum = c.attrib.get("n")
        if not cnum:
            # try to read number from a child label if present
            continue
        ps_num = int(cnum)
        verses = []
        for v in c.iter():
            if local(v.tag) in ("v","verse"):
                vnum = int(v.attrib["n"])
                # Collect all text nodes under verse, join with spaces
                text = "".join(v.itertext())
                text = strip_bidi_and_cgj(text).strip()
                verses.append({"v": vnum, "text_he": text})
        if verses:
            yield ps_num, verses

def write_outputs(ps_iter, out_dir="psalms_json"):
    import os
    os.makedirs(out_dir, exist_ok=True)
    jsonl = []
    total = 0
    for ps_num, verses in ps_iter:
        txt_no_diacritics = " ".join(strip_diacritics(v["text_he"]) for v in verses)
        words = len([w for w in re.split(r"\s+", txt_no_diacritics) if w])
        obj = {
            "psalm": ps_num,
            "verses": verses,
            "stats": {"verses": len(verses),
                      "chars_no_diacritics": len(txt_no_diacritics.replace(" ", "")),
                      "words": words}
        }
        path = os.path.join(out_dir, f"psalm_{ps_num:03d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        jsonl.append(obj)
        total += 1
    with open("psalms.jsonl", "w", encoding="utf-8") as f:
        for row in sorted(jsonl, key=lambda x: x["psalm"]):
            f.write(json.dumps(row, ensure_ascii=False)+"\n")
    assert total == 150, f"Expected 150 psalms; saw {total}. Check selectors."

if __name__ == "__main__":
    xml_bytes = fetch_psalms_xml_bytes()
    ps_iter = iter_psalms(xml_bytes)
    write_outputs(ps_iter)
