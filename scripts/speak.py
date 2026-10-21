"""Аудиовыпуск по сценарию со ссылками: проверка ссылок, озвучка, транскрипт.

    python speak.py --dir <папка> [--script audio/script.md] [--engine silero|edge|elevenlabs] [--voice xenia] [--check-only]

Каждая строка сценария, кроме заголовков «#», должна ссылаться на тезис: [c4]. Тезисы
перепроверяются заново (check_claims.verify): не прошедший тезис — выпуск не собирается.

Silero запускать Python-ом, где стоит torch (см. README). Silero молча ПРОПУСКАЕТ цифры,
латиницу и прочие не кириллические знаки, поэтому числа переводятся в слова (num2words),
а всё остальное некириллическое — ошибка с перечнем символов.
Выход: audio/episode.mp3, audio/speech.txt, audio/transcript.md. Нужен ffmpeg в PATH.
"""
import argparse, json, os, pathlib, re, subprocess, sys, tempfile, urllib.request, wave

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from check_claims import verify
from speak_check import parse

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--script", default="audio/script.md")
ap.add_argument("--engine", default="silero", choices=["silero", "edge", "elevenlabs"])
ap.add_argument("--voice", help="silero: xenia|baya|kseniya|aidar|eugene; edge: ru-RU-SvetlanaNeural; elevenlabs: voice_id")
ap.add_argument("--check-only", action="store_true")
a = ap.parse_args()

d = pathlib.Path(a.dir)
claims, _, _ = verify(d)
by_id = {c["id"]: c for s in claims.get("sections", []) for c in s.get("claims", [])}
blocks, speech, errors = parse((d / a.script).read_text(encoding="utf-8"), by_id, a.engine)
if errors:
    print("Сценарий не прошёл проверку:")
    print("\n".join("  " + e for e in errors))
    sys.exit(1)
words = sum(len(t.split()) for _, t, _ in blocks)
print(f"сценарий в порядке: {len(blocks)} строк, {words} слов (~{words / 150:.1f} мин)")
if a.check_only:
    sys.exit(0)


audio = d / "audio"
audio.mkdir(exist_ok=True)
(audio / "speech.txt").write_text("\n".join(speech) + "\n", encoding="utf-8")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


out = audio / "episode.mp3"
if a.engine == "silero":
    import numpy as np, torch
    p = pathlib.Path.home() / ".cache/istoki/v5_ru.pt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        torch.hub.download_url_to_file("https://models.silero.ai/models/tts/ru/v5_ru.pt", str(p))
    model = torch.package.PackageImporter(str(p)).load_pickle("tts_models", "model")
    sr, parts = 48000, []
    for (is_head, _, _), text in zip(blocks, speech):
        parts.append(np.zeros(int(sr * (1.0 if is_head else 0.45))))
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if sent.strip():
                parts.append(model.apply_tts(text=sent, speaker=a.voice or "xenia", sample_rate=sr).numpy())
                parts.append(np.zeros(int(sr * 0.25)))
    pcm = (np.concatenate(parts) * 32767).clip(-32768, 32767).astype(np.int16)
    wav = audio / "episode.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    ffmpeg("-i", str(wav), "-af", "loudnorm=I=-16", "-b:a", "128k", str(out))
    wav.unlink()
elif a.engine == "edge":
    import asyncio, edge_tts
    asyncio.run(edge_tts.Communicate("\n\n".join(speech), a.voice or "ru-RU-SvetlanaNeural").save(str(out)))
else:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or not a.voice:
        sys.exit("нужны ELEVENLABS_API_KEY и --voice <voice_id>")
    chunks, cur = [], ""
    for t in speech:
        if len(cur) + len(t) > 2500:
            chunks.append(cur); cur = ""
        cur += t + "\n\n"
    chunks.append(cur)
    tmp = pathlib.Path(tempfile.mkdtemp())
    for i, ch in enumerate(chunks):
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{a.voice}?output_format=mp3_44100_128",
            data=json.dumps({"text": ch, "model_id": "eleven_multilingual_v2"}).encode(),
            headers={"xi-api-key": key, "Content-Type": "application/json"})
        (tmp / f"{i:03d}.mp3").write_bytes(urllib.request.urlopen(req, timeout=300).read())
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in sorted(tmp.glob("*.mp3"))), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))


# ---------- транскрипт ----------
def ref_md(r):
    ev = by_id[r]["evidence"]
    return f"{r}: " + "; ".join(f"[{e['source']}.md:{e['line']}](../sources/{e['source']}.md)" for e in ev)


T = [f"# Транскрипт: {claims.get('question', '')}", "", f"Движок: {a.engine}. Каждая фраза — со ссылкой на выписку.", ""]
for is_head, text, refs in blocks:
    T.append(f"## {text}" if is_head else f"- {text} — {'; '.join(ref_md(r) for r in refs)}")
(audio / "transcript.md").write_text("\n".join(T) + "\n", encoding="utf-8")
print(f"готово: {out}")
