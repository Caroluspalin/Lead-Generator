"""Premium-pohjan heron ruutusarja videosta: mp4 sisään, työpöytä- ja puhelinruudut + still ulos.

  python scripts/demo_frames.py scripts/demo_lahteet/premium/veitsi.mp4 \\
      --tyopoyta-osuus 0:0.75 --puhelin-rajaus 1200:1076:700:0 --puhelin-osuus 0:0.85

Kirjoittaa kansioon app/templates/demo/assets/premium/ (--out):
  hero-l-01.webp …  työpöydän ruudut (1280 × 720)
  hero-p-01.webp …  puhelimen ruudut (780 × 724)
  hero-l.avif/.webp, hero-p.avif/.webp  still = kummankin sarjan ensimmäinen ruutu

Videon vaihto ei vaadi pohjan muutoksia: pohja lukee ruutujen määrän kansiosta (demo_site.asset_series) ja
tiedostojen osoitteet saavat uuden ?v=-tiivisteen. Kuvakoot ovat pohjan sopimus (CSS:n kuvasuhteet ja
width/height-attribuutit), joten ne ovat vakioita: rajaus valitsee, mikä osa videosta niihin tulee.
Vanhat saman nimiset ruudut poistetaan ensin, joten ruutumäärän pienentäminen ei jätä ylimääräisiä tiedostoja.

Rajaus on ffmpegin crop-muodossa LEVEYS:KORKEUS:X:Y lähdevideon pikseleinä. Jos rajauksen kuvasuhde ei ole
kohdekoon, reunoilta leikataan tasan. Osuus ALKU:LOPPU (0–1) kertoo, mikä osa videon liikkeestä käytetään.

Vaatii: ffmpeg (libsvtav1 AVIF-stilleihin), ffprobe ja cwebp. Aja scripts/demo_check.py tämän jälkeen:
se mittaa tekstin kontrastin uusien ruutujen päällä.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.demo_site import ASSET_DIR  # noqa: E402

Size = tuple[int, int]

FRAME_SIZES: dict[str, Size] = {"l": (1280, 720), "p": (780, 724)}
STILL_SIZES: dict[str, Size] = {"l": (1600, 900), "p": (780, 724)}


def run(args: list[str]) -> str:
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"{args[0]} epäonnistui:\n{done.stderr.strip()[-800:]}")
    return done.stdout


def frame_total(video: Path) -> int:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
               "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(video)])
    return int(out.strip().split(",")[0])


def parse_range(value: str) -> tuple[float, float]:
    start, end = (float(part) for part in value.split(":"))
    if not 0 <= start < end <= 1:
        raise argparse.ArgumentTypeError("osuus muodossa ALKU:LOPPU, 0 <= ALKU < LOPPU <= 1")
    return start, end


def parse_crop(value: str) -> str:
    parts = value.split(":")
    if len(parts) != 4 or not all(part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError("rajaus muodossa LEVEYS:KORKEUS:X:Y")
    return value


def pick_frames(total: int, count: int, span: tuple[float, float]) -> list[int]:
    """Tasavälein valitut ruudut videon osuudelta; lyhyessä videossa sama ruutu ei toistu."""
    first, last = span[0] * (total - 1), span[1] * (total - 1)
    picked = [round(first + (last - first) * i / (count - 1)) for i in range(count)]
    return sorted(set(picked))


def video_filter(indices: list[int], crop: Optional[str], size: Size) -> str:
    select = "+".join(f"eq(n\\,{i})" for i in indices)
    steps = [f"select='{select}'"]
    if crop:
        steps.append(f"crop={crop}")
    steps.append(f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=increase:flags=lanczos")
    steps.append(f"crop={size[0]}:{size[1]}")
    return ",".join(steps)


def extract(video: Path, indices: list[int], crop: Optional[str], size: Size, work: Path) -> list[Path]:
    work.mkdir(parents=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", video_filter(indices, crop, size),
         "-fps_mode", "passthrough", str(work / "%03d.png")])
    return sorted(work.glob("*.png"))


def remove_old(out: Path, name: str) -> None:
    for pattern in (f"{name}-[lp]-[0-9]*.webp", f"{name}-[lp].webp", f"{name}-[lp].avif"):
        for path in out.glob(pattern):
            path.unlink()


def build(video: Path, out: Path, name: str, crops: dict[str, Optional[str]],
          spans: dict[str, tuple[float, float]], counts: dict[str, int],
          quality: int, still_quality: int, avif_crf: int) -> list[Path]:
    total = frame_total(video)
    written: list[Path] = []
    remove_old(out, name)
    with tempfile.TemporaryDirectory() as tmp:
        for key in ("l", "p"):
            indices = pick_frames(total, counts[key], spans[key])
            pngs = extract(video, indices, crops[key], FRAME_SIZES[key], Path(tmp) / f"ruudut-{key}")
            for number, png in enumerate(pngs, start=1):
                target = out / f"{name}-{key}-{number:02d}.webp"
                run(["cwebp", "-quiet", "-q", str(quality), "-m", "6", str(png), "-o", str(target)])
                written.append(target)
            still = extract(video, indices[:1], crops[key], STILL_SIZES[key], Path(tmp) / f"still-{key}")[0]
            webp, avif = out / f"{name}-{key}.webp", out / f"{name}-{key}.avif"
            run(["cwebp", "-quiet", "-q", str(still_quality), "-m", "6", str(still), "-o", str(webp)])
            run(["ffmpeg", "-v", "error", "-y", "-i", str(still), "-frames:v", "1", "-c:v", "libsvtav1",
                 "-crf", str(avif_crf), "-preset", "4", "-pix_fmt", "yuv420p", str(avif)])
            written += [webp, avif]
    return written


def report(written: list[Path], name: str) -> None:
    for key, label in (("l", "Työpöytä"), ("p", "Puhelin")):
        frames = [p for p in written if p.name.startswith(f"{name}-{key}-")]
        sizes = [p.stat().st_size for p in frames]
        print(f"{label}: {len(frames)} ruutua {FRAME_SIZES[key][0]} × {FRAME_SIZES[key][1]}, "
              f"yhteensä {sum(sizes) / 1000:.0f} kt, suurin {max(sizes) / 1000:.1f} kt")
        for still in (p for p in written if p.stem == f"{name}-{key}"):
            print(f"  still {still.name}: {still.stat().st_size / 1000:.1f} kt")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, default=ASSET_DIR / "premium")
    parser.add_argument("--nimi", default="hero", help="tiedostojen alku (pohja odottaa: hero)")
    parser.add_argument("--tyopoyta-rajaus", type=parse_crop, help="oletus: koko kuva")
    parser.add_argument("--puhelin-rajaus", type=parse_crop, help="oletus: kuvan keskeltä")
    parser.add_argument("--tyopoyta-osuus", type=parse_range, default=(0.0, 1.0))
    parser.add_argument("--puhelin-osuus", type=parse_range, default=(0.0, 1.0))
    parser.add_argument("--tyopoyta-ruutuja", type=int, default=40)
    parser.add_argument("--puhelin-ruutuja", type=int, default=24)
    parser.add_argument("--laatu", type=int, default=62, help="ruutujen WebP-laatu")
    parser.add_argument("--still-laatu", type=int, default=74, help="stillin WebP-laatu")
    parser.add_argument("--avif-crf", type=int, default=26, help="stillin AVIF-laatu (pienempi = parempi)")
    args = parser.parse_args()

    for tool in ("ffmpeg", "ffprobe", "cwebp"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} puuttuu")
    if not args.video.is_file():
        raise SystemExit(f"Videota ei löydy: {args.video}")
    if min(args.tyopoyta_ruutuja, args.puhelin_ruutuja) < 2:
        raise SystemExit("Ruutuja pitää olla vähintään 2")

    written = build(
        args.video, args.out, args.nimi,
        crops={"l": args.tyopoyta_rajaus, "p": args.puhelin_rajaus},
        spans={"l": args.tyopoyta_osuus, "p": args.puhelin_osuus},
        counts={"l": args.tyopoyta_ruutuja, "p": args.puhelin_ruutuja},
        quality=args.laatu, still_quality=args.still_laatu, avif_crf=args.avif_crf,
    )
    report(written, args.nimi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
