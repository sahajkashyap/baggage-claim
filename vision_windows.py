"""
On-device text reading for Windows, using the reader built into Windows 10
and 11 (Windows.Media.Ocr). Same contract as the Mac helper `vision.swift`:

    read_text(path)  -> [{"text", "conf", "x", "y", "w", "h"}], pixel coords, origin top-left
    read_rects(path) -> []   (Windows has no built-in paper detector; the
                             colour and texture detectors carry that job)

Needs the `winsdk` package:  pip install winsdk
Nothing here touches the network.
"""
import asyncio
import os
import sys

_ENGINE = None


def available():
    if sys.platform != "win32":
        return False
    try:
        import winsdk.windows.media.ocr  # noqa: F401
        return True
    except Exception:
        return False


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        eng = OcrEngine.try_create_from_language(Language("en-US"))
        if eng is None:
            eng = OcrEngine.try_create_from_user_profile_languages()
        if eng is None:
            raise RuntimeError("Windows OCR is not available: install the English language pack "
                               "(Settings > Time & Language > Language > Add a language > English)")
        _ENGINE = eng
    return _ENGINE


async def _read(path):
    from winsdk.windows.storage import StorageFile, FileAccessMode
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from PIL import Image

    eng = _engine()
    limit = OcrEngine.max_image_dimension  # 2600 on current Windows
    scale = 1.0
    src = os.path.abspath(path)
    tmp = None
    with Image.open(src) as im:
        w, h = im.size
        if max(w, h) > limit:
            scale = limit / max(w, h)
            tmp = src + ".ocr.png"
            im.convert("RGB").resize((int(w * scale), int(h * scale)), Image.LANCZOS).save(tmp)
            src = tmp
    try:
        f = await StorageFile.get_file_from_path_async(src)
        stream = await f.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await eng.recognize_async(bitmap)
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    out = []
    for line in result.lines:
        words = list(line.words)
        if not words:
            continue
        x0 = min(wd.bounding_rect.x for wd in words)
        y0 = min(wd.bounding_rect.y for wd in words)
        x1 = max(wd.bounding_rect.x + wd.bounding_rect.width for wd in words)
        y1 = max(wd.bounding_rect.y + wd.bounding_rect.height for wd in words)
        out.append({"text": line.text, "conf": 1.0,
                    "x": int(x0 / scale), "y": int(y0 / scale),
                    "w": int((x1 - x0) / scale), "h": int((y1 - y0) / scale)})
    return out


def read_text(path):
    return asyncio.run(_read(path))


def read_rects(path):
    return []


if __name__ == "__main__":
    import json
    mode, path = sys.argv[1], sys.argv[2]
    print(json.dumps(read_text(path) if mode == "text" else read_rects(path)))
