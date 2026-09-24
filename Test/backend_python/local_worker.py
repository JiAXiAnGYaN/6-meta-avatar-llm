"""Local model runner for the Meta Avatar backend.

The server never imports torch itself. Every heavy job runs in a short-lived
child process started through this module, so the several gigabytes of model
weights are handed back to the system as soon as one avatar is finished.

Expected folder layout below the local model directory:

    TripoSR/model/   config.yaml, model.ckpt   (stabilityai/TripoSR)
    TripoSR/source/  tsr/...                   (code from the TripoSR Space)
    u2net/           u2net.onnx                (rembg background removal)
    .cache/          Hugging Face cache, holds the DINO config TripoSR needs

prepare_local_models.py creates all of it.
"""

import argparse
import gc
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

WORKER_PATH = Path(__file__).resolve()
BACKGROUND_MODEL = 'u2net'
_worker_lock = threading.Lock()


class LocalWorkerError(RuntimeError):
    pass


def run_triposr(
    image_path: Path,
    output_path: Path,
    processed_path: Path,
    *,
    models_dir: Path,
    resolution: int,
    foreground_ratio: float,
    device: str,
) -> None:
    """Build a GLB from one front full-body image.

    processed_path receives the cut-out, rescaled image TripoSR actually saw.
    The texture baker needs exactly that framing to line the picture up with
    the mesh.
    """
    _run_worker([
        'triposr',
        '--image', str(image_path),
        '--output', str(output_path),
        '--processed', str(processed_path),
        '--models-dir', str(models_dir),
        '--resolution', str(resolution),
        '--foreground-ratio', str(foreground_ratio),
        '--device', device,
    ])


def _run_worker(arguments: list[str]) -> None:
    timeout = int(os.getenv('META_AVATAR_LOCAL_TIMEOUT', '1800'))
    # One job at a time: two TripoSR runs side by side do not fit in 16 GB.
    with _worker_lock:
        try:
            result = subprocess.run(
                [sys.executable, str(WORKER_PATH), *arguments],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise LocalWorkerError('Local 3D reconstruction timed out.') from error
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise LocalWorkerError(lines[-1] if lines else 'The local model worker failed.')


# Everything below runs inside the child process.

def _use_local_model_folders(models_dir: Path) -> None:
    cache = models_dir / '.cache'
    os.environ['HF_HOME'] = str(cache)
    os.environ['HF_HUB_CACHE'] = str(cache / 'hub')
    os.environ['U2NET_HOME'] = str(models_dir / 'u2net')


def _install_marching_cubes() -> None:
    """Provide the torchmcubes module TripoSR imports, backed by scikit-image.

    torchmcubes has no macOS wheel. Its vertices come out in (k, j, i) order,
    and TripoSR swaps them back with v_pos[..., [2, 1, 0]]. scikit-image
    already returns (i, j, k), so the columns are reversed here first;
    without that the finished avatar lies on its back. Reversing the axes
    mirrors the mesh, so the triangle winding is flipped as well to keep the
    faces pointing outwards.
    """
    import numpy as np
    import torch
    from skimage.measure import marching_cubes as skimage_marching_cubes

    def marching_cubes(volume, threshold):
        grid = volume.detach().float().cpu().numpy()
        try:
            vertices, faces, _, _ = skimage_marching_cubes(grid, level=float(threshold), allow_degenerate=False)
        except (RuntimeError, ValueError) as error:
            raise RuntimeError('TripoSR found no surface in this image.') from error
        vertices = np.ascontiguousarray(vertices[:, ::-1], dtype=np.float32)
        faces = np.ascontiguousarray(faces[:, ::-1], dtype=np.int64)
        return torch.from_numpy(vertices).to(volume.device), torch.from_numpy(faces).to(volume.device)

    module = types.ModuleType('torchmcubes')
    module.marching_cubes = marching_cubes
    sys.modules['torchmcubes'] = module


def _pick_device(requested: str) -> str:
    import torch

    device = requested.strip().lower()
    if device == 'auto':
        if torch.cuda.is_available():
            return 'cuda'
        if torch.backends.mps.is_available():
            return 'mps'
        return 'cpu'
    if device.startswith('cuda') and not torch.cuda.is_available():
        raise LocalWorkerError('CUDA was selected but is not available.')
    if device == 'mps' and not torch.backends.mps.is_available():
        raise LocalWorkerError('Apple Metal was selected but is not available.')
    if device not in {'cpu', 'mps'} and not device.startswith('cuda'):
        raise LocalWorkerError('The device must be cpu, mps, cuda or auto.')
    return device


def _on_grey_background(image):
    """Flatten an RGBA cut-out onto 50 % grey, the way the TripoSR demo does."""
    import numpy as np
    from PIL import Image

    pixels = np.asarray(image).astype(np.float32) / 255.0
    alpha = pixels[:, :, 3:4]
    flattened = pixels[:, :, :3] * alpha + (1.0 - alpha) * 0.5
    return Image.fromarray((flattened * 255.0).astype(np.uint8))


def _reconstruct(args: argparse.Namespace) -> None:
    models_dir = Path(args.models_dir).expanduser().resolve()
    source_dir = models_dir / 'TripoSR' / 'source'
    weights_dir = models_dir / 'TripoSR' / 'model'
    if not (source_dir / 'tsr' / 'system.py').is_file() or not (weights_dir / 'model.ckpt').is_file():
        raise LocalWorkerError('TripoSR is not downloaded yet. Run prepare_local_models.py once while online.')
    if not (models_dir / 'u2net' / f'{BACKGROUND_MODEL}.onnx').is_file():
        raise LocalWorkerError('The background removal model is missing. Run prepare_local_models.py once while online.')

    _use_local_model_folders(models_dir)
    sys.path.insert(0, str(source_dir))
    _install_marching_cubes()

    import rembg
    import torch
    from PIL import Image
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground, to_gradio_3d_orientation

    device = _pick_device(args.device)
    if device == 'cpu':
        torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))

    image = Image.open(args.image).convert('RGB')
    image = remove_background(image, rembg.new_session(BACKGROUND_MODEL))
    image = resize_foreground(image, args.foreground_ratio)
    image = _on_grey_background(image)
    processed_path = Path(args.processed)
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(processed_path, format='PNG')

    model = TSR.from_pretrained(str(weights_dir), config_name='config.yaml', weight_name='model.ckpt')
    model.renderer.set_chunk_size(int(os.getenv('META_AVATAR_LOCAL_CHUNK_SIZE', '8192')))
    model.to(device)
    with torch.inference_mode():
        scene_codes = model([image], device=device)
    mesh = model.extract_mesh(scene_codes, resolution=args.resolution)[0]
    mesh = to_gradio_3d_orientation(mesh)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(output_path)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise LocalWorkerError('TripoSR wrote an empty model file.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    triposr = commands.add_parser('triposr', help='image to GLB')
    triposr.add_argument('--image', required=True)
    triposr.add_argument('--output', required=True)
    triposr.add_argument('--processed', required=True)
    triposr.add_argument('--models-dir', required=True)
    triposr.add_argument('--resolution', type=int, required=True)
    triposr.add_argument('--foreground-ratio', type=float, required=True)
    triposr.add_argument('--device', required=True)
    args = parser.parse_args()
    try:
        _reconstruct(args)
    except Exception as error:
        message = str(error)
        if 'out of memory' in message.lower() or 'cannot allocate memory' in message.lower():
            message = 'Local TripoSR ran out of memory. Close other programs or lower META_AVATAR_MC_RESOLUTION.'
        print(message, file=sys.stderr)
        raise SystemExit(1)
    finally:
        gc.collect()


if __name__ == '__main__':
    main()
