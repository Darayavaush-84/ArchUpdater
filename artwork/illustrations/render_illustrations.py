"""Render ArchUpdater's empty-state illustrations with Blender.

Builds the scenes defined in build_scenes.py, renders them with Cycles and writes
the files the app ships in src/archupdater/resources/img/illustrations:

    ready.webp, checking.webp, waiting_network.webp  (looping, 90 frames at 30 fps)
    up_to_date.png                                   (still image)

Requires Blender 5.2 or newer, ImageMagick (magick) and ffmpeg built with libwebp.

    python artwork/illustrations/render_illustrations.py [--output DIR] [--save-blend FILE]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "src" / "archupdater" / "resources" / "img" / "illustrations"

ANIMATIONS = {
    "AU_Pronto": "ready.webp",
    "AU_Controllo": "checking.webp",
    "AU_Rete": "waiting_network.webp",
}
STILLS = {"AU_Aggiornato": "up_to_date.png"}
FPS = 30
SIZE = 440  # shipped at 2x the 220 px the app displays

# Runs inside Blender: build every scene, pick a GPU when one is available and
# render each scene's frames into FRAMES_DIR/<scene>/.
BLENDER_SCRIPT = """
import sys
import bpy

script, frames_dir, save_blend = sys.argv[sys.argv.index("--") + 1:]
namespace = {"__name__": "archupdater_illustrations"}
exec(compile(open(script).read(), script, "exec"), namespace)
report = namespace["build_all"]()
if report["invalid_drivers"]:
    raise SystemExit("Invalid drivers: " + ", ".join(report["invalid_drivers"]))

prefs = bpy.context.preferences.addons["cycles"].preferences
device = "CPU"
for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
    try:
        prefs.compute_device_type = backend
    except TypeError:
        continue
    prefs.get_devices()
    gpus = [d for d in prefs.devices if d.type == backend]
    if gpus:
        for d in prefs.devices:
            d.use = d in gpus
        device = "GPU"
        break
print(f"Rendering on {device} ({prefs.compute_device_type})")

if save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=save_blend, copy=True)
for name in report["scenes"]:
    scene = bpy.data.scenes[name]
    scene.cycles.device = device
    scene.render.filepath = f"{frames_dir}/{name}/####"
    bpy.ops.render.render(animation=True, scene=name)
"""


def render_frames(blender: str, frames_dir: Path, save_blend: Path | None) -> None:
    subprocess.run(
        [
            blender, "--background", "--factory-startup",
            "--python-expr", BLENDER_SCRIPT,
            "--", str(HERE / "build_scenes.py"), str(frames_dir), str(save_blend or ""),
        ],
        check=True,
    )


def medallion(src: Path, dst: Path) -> None:
    circle = f"circle {SIZE // 2},{SIZE // 2} {SIZE // 2},12"
    subprocess.run(
        [
            "magick", str(src), "-resize", f"{SIZE}x{SIZE}",
            "(", "-size", f"{SIZE}x{SIZE}", "xc:black", "-fill", "white", "-draw", circle, ")",
            "-alpha", "off", "-compose", "CopyOpacity", "-composite",
            "-fill", "none", "-stroke", "#2b4c9b", "-strokewidth", "4", "-draw", circle,
            str(dst),
        ],
        check=True,
    )


def encode_webp(frames: Path, dst: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS),
            "-i", str(frames / "%04d.png"),
            "-c:v", "libwebp_anim", "-quality", "85", "-loop", "0", str(dst),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="where to write the illustrations")
    parser.add_argument("--blender", default="blender", help="Blender executable")
    parser.add_argument("--save-blend", type=Path, help="also save the generated scenes to this .blend file")
    args = parser.parse_args()

    for tool in (args.blender, "magick", "ffmpeg"):
        if shutil.which(tool) is None:
            raise SystemExit(f"Required tool not found: {tool}")

    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archupdater-illustrations-") as tmp:
        work = Path(tmp)
        render_frames(args.blender, work / "frames", args.save_blend.resolve() if args.save_blend else None)
        for scene in [*ANIMATIONS, *STILLS]:
            frames = sorted((work / "frames" / scene).glob("*.png"))
            masked = work / "masked" / scene
            masked.mkdir(parents=True)
            with ThreadPoolExecutor() as pool:
                list(pool.map(lambda f: medallion(f, masked / f.name), frames))
            if scene in ANIMATIONS:
                encode_webp(masked, args.output / ANIMATIONS[scene])
            else:
                shutil.copy(masked / frames[0].name, args.output / STILLS[scene])
    print(f"Illustrations written to {args.output}")


if __name__ == "__main__":
    main()
