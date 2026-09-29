"""Local model runner for the Meta Avatar backend.

The server never imports torch itself. Every heavy job runs in a short-lived
child process started through this module, so the several gigabytes of model
weights are handed back to the system as soon as one avatar is finished.

Expected folder layout below the local model directory:

    TripoSR/model/   config.yaml, model.ckpt   (stabilityai/TripoSR)
    TripoSR/source/  tsr/...                   (code from the TripoSR Space)
    u2net/           u2net.onnx                (rembg background removal)
    stable-diffusion-v1-5/                     (fp16 weights, photo to cartoon)
    .cache/          Hugging Face cache, holds the DINO config TripoSR needs

prepare_local_models.py creates all of it.
"""

import argparse
import gc
import os
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

WORKER_PATH = Path(__file__).resolve()
BACKGROUND_MODEL = 'u2net'
CARTOON_MODEL_FOLDER = 'stable-diffusion-v1-5'
QUALITY_CARTOON_MODEL_FOLDER = 'dreamshaper-8'
FACE_ADAPTER_MODEL_FOLDER = 'ip-adapter-face'
FACE_ADAPTER_FILES = [
    'models/image_encoder/config.json',
    'models/image_encoder/model.safetensors',
]
FACE_ADAPTER_WEIGHT = 'models/ip-adapter-plus-face_sd15.safetensors'
QUALITY_CARTOON_FILES = [
    'model_index.json',
    'scheduler/scheduler_config.json',
    'unet/config.json',
    'unet/diffusion_pytorch_model.fp16.safetensors',
    'vae/config.json',
    'vae/diffusion_pytorch_model.fp16.safetensors',
]
TRIPOSR_SOURCE_FILES = [
    'tsr/system.py',
    'tsr/utils.py',
    'tsr/models/isosurface.py',
    'tsr/models/nerf_renderer.py',
    'tsr/models/network_utils.py',
    'tsr/models/tokenizers/image.py',
    'tsr/models/tokenizers/triplane.py',
    'tsr/models/transformer/attention.py',
    'tsr/models/transformer/basic_transformer_block.py',
    'tsr/models/transformer/transformer_1d.py',
]
CARTOON_NEGATIVE_PROMPT = (
    'photo, flat cutout, paper doll, low detail, blurry face, tiny head, long body, long legs, cropped body, '
    'close-up, profile, duplicate head, two people, malformed arms, legs, hands, feet, fused limbs, extra limbs, '
    'distorted face, open mouth, big grin, teeth, text, watermark'
)
SHORT_NEGATIVE_PROMPT =('photographic face, pasted face, flat cutout, paper doll, low detail, blurry face, tiny head, long body, long legs, duplicate head, '
                        'two people, malformed arms, legs, hands, feet, fused limbs, extra limbs, distorted face, open mouth, big grin, teeth, cropped body, '
                        'portrait crop, profile, text')
_worker_lock = threading.Lock()


FLAGGED_EXIT_CODE = 3


class LocalWorkerError(RuntimeError):
    pass


class ResultFlagged(LocalWorkerError):
    """The safety checker rejected one generated image. Another seed usually passes."""


def _face_adapter_choice():
    choice = os.getenv('META_AVATAR_LOCAL_FACE_ADAPTER', 'none').strip().lower()
    if choice not in {'none', 'plus'}:
        raise LocalWorkerError('META_AVATAR_LOCAL_FACE_ADAPTER must be none or plus.')
    if choice == 'plus':
        try:
            import psutil
            memory = psutil.virtual_memory().total
        except ImportError:
            memory = 0
        if memory and memory < 16 * 1024 ** 3:
            raise LocalWorkerError('Plus Face needs at least 16 GB of RAM. Use the default photo mode instead.')
    return choice


def _face_adapter_files(choice):
    return FACE_ADAPTER_FILES + [FACE_ADAPTER_WEIGHT]


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


def run_cutout(image_path: Path, output_path: Path, *, models_dir: Path) -> None:
    _run_worker([
        'cutout',
        '--image', str(image_path),
        '--output', str(output_path),
        '--models-dir', str(models_dir),
    ])


def run_photo_cartoon(
    photo_path: Path,
    output_path: Path,
    prompt: str,
    *,
    models_dir: Path,
    device: str,
    strength: float,
    seed: int,
    expand: bool = False,
) -> None:
    """Turn a front portrait, upper-body or full-body photo into a full-body cartoon.

    strength decides how far the result may drift from the photo: low values
    keep the pose and clothes, high values give a stronger cartoon look.
    """
    tmp = [
        'cartoonize', '--photo', str(photo_path), '--output', str(output_path),
        '--prompt', prompt, '--models-dir', str(models_dir), '--device', device,
        '--strength', str(strength), '--seed', str(seed),
    ]
    if expand:
        tmp.append('--expand')
    if _face_adapter_choice() == 'plus':
        with tempfile.TemporaryDirectory(prefix='meta-avatar-face-') as folder:
            embeds = Path(folder) / 'face.safetensors'
            _run_worker([
                'encode-face', '--photo', str(photo_path), '--output', str(embeds),
                '--models-dir', str(models_dir), '--device', device,
            ])
            tmp.extend(['--identity-embeds', str(embeds)])
            _run_worker(tmp)
    else:
        _run_worker(tmp)


def run_name_cartoon(
    output_path: Path,
    prompt: str,
    models_dir: Path,
    device: str,
    seed: int,
) -> None:
    _run_worker([
        'cartoonize',
        '--name-only',
        '--output', str(output_path),
        '--prompt', prompt,
        '--models-dir', str(models_dir),
        '--device', device,
        '--seed', str(seed),
    ])


def _run_worker(arguments: list[str]) -> None:
    timeout = int(os.getenv('META_AVATAR_LOCAL_TIMEOUT', '5400'))
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
            raise LocalWorkerError('The local model took too long and was stopped.') from error
    if result.returncode == FLAGGED_EXIT_CODE:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise ResultFlagged(lines[-1] if lines else 'The image model flagged this result.')
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise LocalWorkerError(lines[-1] if lines else 'The local model worker failed.')


# Everything below runs inside the child process.

def _use_local_model_folders(models_dir: Path) -> None:
    cache = models_dir / '.cache'
    numba = Path(os.getenv('NUMBA_CACHE_DIR', str(Path(tempfile.gettempdir()) / 'meta-avatar-numba')))
    numba.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(cache)
    os.environ['HF_HUB_CACHE'] = str(cache / 'hub')
    os.environ['U2NET_HOME'] = str(models_dir / 'u2net')
    os.environ['NUMBA_CACHE_DIR'] = str(numba)


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


def _clear_leg_gap(mask, rgb, box):
    import cv2
    import numpy as np

    x, y, bw, bh = box
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    middle = x + bw // 2
    search = max(18, int(bw * .18))
    first = max(0, y + int(bh * .54))
    last = min(gray.shape[0], y + int(bh * .995))
    rows = []
    for row in range(first, last):
        left = np.flatnonzero((gray[row, middle - search:middle] < 110) & (mask[row, middle - search:middle] > 0))
        right = np.flatnonzero((gray[row, middle:middle + search] < 110) & (mask[row, middle:middle + search] > 0))
        if not len(left) or not len(right):
            continue
        a = middle - search + int(left[-1])
        b = middle + int(right[0])
        if not 4 <= b - a - 1 <= bw * .17 or abs((a + b) / 2 - middle) > bw * .07:
            continue
        side1 = float(np.median(gray[row, max(0, a - 12):a + 1]))
        side2 = float(np.median(gray[row, b:min(gray.shape[1], b + 13)]))
        gap = float(np.median(gray[row, a + 1:b]))
        if side1 > 100 or side2 > 100 or gap < max(130, (side1 + side2) / 2 + 45):
            continue
        rows.append((row, a + 1, b))
    if len(rows) < bh * .18 or not any(row > y + bh * .85 for row, _, _ in rows):
        return mask
    for row, a, b in rows:
        mask[row, a:b] = 0
    return mask


def _grey_reference_cutout(image):
    import cv2
    import numpy as np
    from PIL import Image

    rgb = np.asarray(image.convert('RGB'), dtype=np.uint8)
    h, w = rgb.shape[:2]
    edge = max(2, min(h, w) // 100)
    border = np.concatenate((
        rgb[:edge].reshape(-1, 3), rgb[-edge:].reshape(-1, 3),
        rgb[:, :edge].reshape(-1, 3), rgb[:, -edge:].reshape(-1, 3)))
    bg = np.median(border.astype(np.float32), axis=0)
    border_distance = np.linalg.norm(border.astype(np.float32) - bg, axis=1)
    if float(np.percentile(border_distance, 98)) > 12:
        return None
    distance = np.linalg.norm(rgb.astype(np.float32) - bg, axis=2)
    limit = max(12, int(np.percentile(border_distance, 99)) + 7)
    mask = (distance > limit).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh, area = (int(value) for value in stats[best])
    if area < h * w * .025 or area > h * w * .8 or bh < h * .45 or bw < w * .08:
        return None
    mask = np.where(labels == best, 255, 0).astype(np.uint8)
    flood = mask.copy()
    cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)
    mask = cv2.bitwise_or(mask, cv2.bitwise_not(flood))
    mask = _clear_leg_gap(mask, rgb, (x, y, bw, bh))
    mask = cv2.erode(mask, kernel, iterations=2)
    mask = cv2.GaussianBlur(mask, (3, 3), .7)
    return Image.fromarray(np.dstack((rgb, mask)), 'RGBA')


def _person_cutout(image, models_dir: Path):
    import cv2
    import numpy as np
    from PIL import Image

    if not (models_dir / 'u2net' / f'{BACKGROUND_MODEL}.onnx').is_file():
        raise LocalWorkerError('The background removal model is missing. Run prepare_local_models.py once while online.')
    _use_local_model_folders(models_dir)
    import rembg
    cutout = rembg.remove(image.convert('RGB'), session=rembg.new_session(BACKGROUND_MODEL)).convert('RGBA')
    alpha = np.asarray(cutout.getchannel('A')).copy()
    height, width = alpha.shape
    count, labels, stats, _ = cv2.connectedComponentsWithStats((alpha >= 128).astype(np.uint8), 8)
    if count < 2:
        raise LocalWorkerError('The background remover could not find one complete person.')
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, box_width, box_height, area = (int(value) for value in stats[largest])
    if area < width * height * .04 or area > width * height * .7 or box_height < height * .45 or box_width < width * .08:
        raise LocalWorkerError('The background remover could not find one complete person.')
    other = max((int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, count) if index != largest), default=0)
    if other > area * .12:
        raise LocalWorkerError('The background remover found more than one foreground subject.')
    keep = cv2.dilate((labels == largest).astype(np.uint8), np.ones((5, 5), np.uint8)) != 0
    alpha[~keep] = 0
    corner = max(4, min(width, height) // 20)
    if any(np.any(alpha[ys, xs] >= 16) for ys, xs in (
        (slice(0, corner), slice(0, corner)),
        (slice(0, corner), slice(width - corner, width)),
        (slice(height - corner, height), slice(0, corner)),
        (slice(height - corner, height), slice(width - corner, width)),
    )):
        raise LocalWorkerError('The background remover left visible background in an image corner.')
    cutout.putalpha(Image.fromarray(alpha))
    return cutout


def _cutout(args: argparse.Namespace) -> None:
    from PIL import Image

    models_dir = Path(args.models_dir).expanduser().resolve()
    with Image.open(args.image) as source:
        cutout = _person_cutout(source, models_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cutout.save(output_path, format='PNG')


def _reconstruct(args: argparse.Namespace) -> None:
    models_dir = Path(args.models_dir).expanduser().resolve()
    source_dir = models_dir / 'TripoSR' / 'source'
    weights_dir = models_dir / 'TripoSR' / 'model'
    if not all((source_dir /name).is_file()and(source_dir/name).stat().st_size>0 for name in TRIPOSR_SOURCE_FILES)or not (weights_dir / 'model.ckpt').is_file():
        raise LocalWorkerError('TripoSR is not downloaded yet. Run prepare_local_models.py once while online.')
    if not (models_dir / 'u2net' / f'{BACKGROUND_MODEL}.onnx').is_file():
        raise LocalWorkerError('The background removal model is missing. Run prepare_local_models.py once while online.')

    _use_local_model_folders(models_dir)
    sys.path.insert(0, str(source_dir))
    _install_marching_cubes()

    import torch
    from PIL import Image
    from tsr.system import TSR
    from tsr.utils import resize_foreground, to_gradio_3d_orientation

    device = _pick_device(args.device)
    if device == 'cpu':
        torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))

    with Image.open(args.image) as source:
        image = _person_cutout(source, models_dir)
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


def _passes_safety_checker(image, model_dir: Path) -> bool:
    import torch
    from diffusers.pipelines.stable_diffusion.safety_checker import StableDiffusionSafetyChecker, cosine_distance
    from transformers import CLIPImageProcessor

    checker = StableDiffusionSafetyChecker.from_pretrained(
        str(model_dir / 'safety_checker'), variant='fp16', dtype=torch.float32, local_files_only=True)
    processor = CLIPImageProcessor.from_pretrained(str(model_dir / 'feature_extractor'), local_files_only=True)
    clip_input = processor(images=[image], return_tensors='pt').pixel_values.float()
    with torch.inference_mode():
        pooled = checker.vision_model(clip_input)[1]
        embeds = checker.visual_projection(pooled)
        special = cosine_distance(embeds, checker.special_care_embeds)[0] - checker.special_care_embeds_weights
        adjustment = .01 if bool(torch.any(special > 0)) else 0
        scores = cosine_distance(embeds, checker.concept_embeds)[0] - checker.concept_embeds_weights + adjustment
    margin = float(os.getenv('META_AVATAR_SAFETY_MARGIN', '.02'))
    if not 0 <= margin <= .05:
        raise LocalWorkerError('META_AVATAR_SAFETY_MARGIN must be between 0 and 0.05.')
    score = float(scores.max())
    if score > margin:
        print(f'The local safety checker rejected this image with score {score:.4f}.', file=sys.stderr)
        return False
    return True


def _body_template(width, height, tie=True, shirt_color=None, jacket_color=None, head=True):
    from PIL import Image, ImageDraw

    image = Image.new('RGB', (width, height), (190, 190, 190))
    draw = ImageDraw.Draw(image)
    skin = (205, 163, 132)
    suit = jacket_color or (50, 61, 78)
    shirt = shirt_color or (225, 228, 230)
    shoe = (35, 35, 38)
    if head:
        draw.ellipse((width * .4, height * .04, width * .6, height * .205), fill=skin)
    draw.rectangle((width * .47, height * .175, width * .53, height * .22), fill=skin)
    draw.polygon(((width * .32, height * .215), (width * .68, height * .215), (width * .61, height * .525), (width * .39, height * .525)), fill=suit)
    draw.polygon(((width * .325, height * .225), (width * .265, height * .255), (width * .23, height * .565), (width * .305, height * .58), (width * .39, height * .285)), fill=suit)
    draw.polygon(((width * .675, height * .225), (width * .735, height * .255), (width * .77, height * .565), (width * .695, height * .58), (width * .61, height * .285)), fill=suit)
    draw.ellipse((width * .215, height * .545, width * .305, height * .63), fill=skin)
    draw.ellipse((width * .695, height * .545, width * .785, height * .63), fill=skin)
    draw.polygon(((width * .405, height * .22), (width * .595, height * .22), (width * .555, height * .43), (width * .445, height * .43)), fill=shirt)
    if tie:
        draw.polygon(((width * .482, height * .225), (width * .518, height * .225), (width * .525, height * .405), (width * .5, height * .45), (width * .475, height * .405)), fill=(45, 55, 90))
    else:
        seam = tuple(max(0, int(value * .72)) for value in shirt)
        draw.line(((width * .46, height * .22), (width * .5, height * .265), (width * .54, height * .22)), fill=seam, width=max(2, width // 100))
    draw.polygon(((width * .395, height * .505), (width * .49, height * .505), (width * .47, height * .865), (width * .37, height * .865)), fill=(62, 67, 78))
    draw.polygon(((width * .51, height * .505), (width * .605, height * .505), (width * .63, height * .865), (width * .53, height * .865)), fill=(62, 67, 78))
    draw.ellipse((width * .345, height * .84, width * .485, height * .92), fill=shoe)
    draw.ellipse((width * .515, height * .84, width * .655, height * .92), fill=shoe)
    return image


def _photo_face(path):
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    photo = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    grey = cv2.cvtColor(np.asarray(photo), cv2.COLOR_RGB2GRAY)
    image_height, image_width = grey.shape
    min_face = max(36, min(96, int(min(image_width, image_height) * .04)))
    front = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
    profile = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')
    if front.empty() or profile.empty():
        raise LocalWorkerError('The local face detector is not available.')
    raw = []
    middle = (image_width * .5, image_height * .5)
    for angle in (-20, 0, 20):
        matrix = cv2.getRotationMatrix2D(middle, angle, 1.0)
        turned = grey if angle == 0 else cv2.warpAffine(grey, matrix, (image_width, image_height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        found = front.detectMultiScale(turned, scaleFactor=1.07, minNeighbors=4, minSize=(min_face, min_face))
        inverse = cv2.invertAffineTransform(matrix)
        for x, y, w, h in found:
            points = np.array([[[x, y], [x + w, y], [x + w, y + h], [x, y + h]]], dtype=np.float32)
            mapped = cv2.transform(points, inverse)[0]
            x0 = max(0, int(mapped[:, 0].min()))
            y0 = max(0, int(mapped[:, 1].min()))
            x1 = min(image_width, int(mapped[:, 0].max()))
            y1 = min(image_height, int(mapped[:, 1].max()))
            if x1 - x0 >= min_face and y1 - y0 >= min_face:
                raw.append((x0, y0, x1, y1))
    for flipped in (False, True):
        tmp = cv2.flip(grey, 1) if flipped else grey
        found = profile.detectMultiScale(tmp, scaleFactor=1.07, minNeighbors=4, minSize=(min_face, min_face))
        for x, y, w, h in found:
            x0 = image_width - x - w if flipped else x
            raw.append((int(x0), int(y), int(x0 + w), int(y + h)))
    raw.sort(key=lambda item: (item[2] - item[0]) * (item[3] - item[1]), reverse=True)
    faces = []
    for box in raw:
        same = False
        for old in faces:
            ix = max(0, min(box[2], old[2]) - max(box[0], old[0]))
            iy = max(0, min(box[3], old[3]) - max(box[1], old[1]))
            overlap = ix * iy
            area1 = (box[2] - box[0]) * (box[3] - box[1])
            area2 = (old[2] - old[0]) * (old[3] - old[1])
            if overlap / max(1, area1 + area2 - overlap) >= .18 or overlap / max(1, min(area1, area2)) >= .65:
                same = True
                break
        if not same:
            faces.append(box)
    if not faces:
        raise LocalWorkerError('The local worker could not find the face in this photo.')
    x0, y0, x1, y1 = faces[0]
    w = x1 - x0
    h = y1 - y0
    x0 = max(0, int(x0 - w * .25))
    y0 = max(0, int(y0 - h * .45))
    x1 = min(photo.width, int(x1 + w * .25))
    y1 = min(photo.height, int(y1 + h * .2))
    photo = photo.crop((x0, y0, x1, y1))
    return ImageOps.fit(photo, (512, 512), Image.Resampling.LANCZOS, centering=(.5, .42))


def _body_from_prompt(width, height, prompt):
    prompt = prompt.lower()
    colors = {
        'light blue': (189, 215, 232), 'dark blue': (38, 57, 80),
        'charcoal': (47, 49, 56), 'navy': (38, 48, 76),
        'grey': (100, 105, 109), 'gray': (100, 105, 109),
        'black': (37, 39, 42), 'dark': (47, 51, 55),
        'blue': (59, 89, 123), 'brown': (91, 68, 54),
        'white': (228, 229, 228)
    }
    shirt = next((rgb for word, rgb in colors.items() if word + ' shirt' in prompt), None)
    jacket = next((rgb for word, rgb in colors.items() if word + ' jacket' in prompt), None)
    tie = _prompt_has_tie(prompt)
    return _body_template(width, height, tie=tie, shirt_color=shirt, jacket_color=jacket, head=False)


def _prompt_has_tie(prompt):
    return any(piece.strip().endswith(' tie') and not piece.strip().startswith(('no ', 'without '))
               for piece in prompt.lower().split(','))


def _head_crop(face):
    import cv2
    import numpy as np

    rgb = np.asarray(face.convert('RGB'))
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
    boxes = detector.detectMultiScale(grey, scaleFactor=1.07, minNeighbors=3, minSize=(40, 40)) if not detector.empty() else []
    boxes = [box for box in boxes if box[1] + box[3] / 2 < face.height * .7]
    if boxes:
        x, y, w, h = max(boxes, key=lambda box: box[2] * box[3])
        left = max(0, int(x - w * .13))
        top = max(0, int(y - h * .25))
        right = min(face.width, int(x + w * 1.13))
        bottom = min(face.height, int(y + h * 1.08))
        return face.crop((left, top, right, bottom))
    return face.crop((int(face.width * .12), 0, int(face.width * .88), int(face.height * .76)))


def _photo_negative(prompt):
    import re

    lower = prompt.lower()
    negative = SHORT_NEGATIVE_PROMPT
    if 'clean-shaven' in lower:
        negative += ', beard, moustache, mustache, goatee, stubble, facial hair'
    if re.search(r'\bshort (?:[a-z]+ ){0,3}hair\b', lower):
        negative += ', long hair, shoulder-length hair, ponytail, flowing hair'
    if not _prompt_has_tie(lower):
        negative += ', necktie, tie'
    if any(word + ' shirt' in lower for word in ('grey', 'gray', 'dark', 'black', 'blue', 'light blue')):
        negative += ', white shirt'
    if 'shirt' in lower and 'scarf' not in lower:
        negative += ', scarf, neck wrap, hoodie, hood, turtleneck, cowl neck'
    return negative


def _photo_template(face, width, height, prompt=''):
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

    body = _body_from_prompt(width, height, prompt)
    bust = ImageOps.contain(face.convert('RGB'), (max(128, int(width * .35)), max(160, int(height * .25))), Image.Resampling.LANCZOS)
    pixels = np.asarray(bust, dtype=np.float32)
    border = max(4, bust.width // 14)
    corners = np.concatenate((pixels[:border, :border].reshape(-1, 3), pixels[:border, -border:].reshape(-1, 3)))
    background = np.median(corners, axis=0)
    if np.percentile(np.linalg.norm(corners - background, axis=1), 90) < 20:
        distance = np.linalg.norm(pixels - background, axis=2)
        alpha = np.clip((distance - 10) * 14, 0, 255)
        fade = np.ones(bust.height, dtype=np.float32)
        end = max(0, bust.height - 12)
        fade[end:] = np.linspace(1, 0, bust.height - end)
        alpha = (alpha * fade[:, None]).astype(np.uint8)
        matte = Image.fromarray(alpha, 'L').filter(ImageFilter.GaussianBlur(2))
        body.paste(bust, ((width - bust.width) // 2, int(height * .03)), matte)
        return body
    fw = max(96, int(width * .205))
    fh = max(128, int(height * .18))
    face = ImageOps.contain(_head_crop(face), (fw, fh), Image.Resampling.LANCZOS)
    fw, fh = face.size
    mask = Image.new('L', (fw, fh), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((3, 2, fw - 3, fh - 2), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(4, fw // 18)))
    rgb = np.asarray(face.convert('RGB'), dtype=np.float32)
    edge = max(3, min(fw, fh) // 12)
    corners = np.concatenate((rgb[:edge, :edge].reshape(-1, 3), rgb[:edge, -edge:].reshape(-1, 3)))
    bg = np.median(corners, axis=0)
    if np.percentile(np.linalg.norm(corners - bg, axis=1), 90) < 20:
        distance = np.linalg.norm(rgb - bg, axis=2)
        matte = Image.fromarray(np.clip((distance - 12) * 14, 0, 255).astype(np.uint8), 'L')
        mask = ImageChops.multiply(mask, matte)
    if face.mode == 'RGBA':
        mask = ImageChops.multiply(mask, face.getchannel('A'))
    body.paste(face.convert('RGB'), ((width - fw) // 2, int(height * .035) + (max(128, int(height * .18)) - fh) // 2), mask)
    return body


def _blend_stylized_face(body, face):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    width, height = body.size
    grey = cv2.cvtColor(np.asarray(body.convert('RGB')), cv2.COLOR_RGB2GRAY)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
    found = detector.detectMultiScale(grey[:int(height * .24)], scaleFactor=1.07, minNeighbors=3, minSize=(30, 30)) if not detector.empty() else []
    found = [box for box in found if box[1] + box[3] / 2 < height * .2 and box[2] >= width * .08]
    if len(found):
        x, y, w, h = max(found, key=lambda item: item[2] * item[3])
        size = max(80, min(int(max(w, h) * 1.42), int(width * .25)))
        left = int(x + w / 2 - size / 2)
        top = int(y + h / 2 - size / 2 - h * .18)
    else:
        size = max(80, min(int(width * .205), int(height * .16)))
        left = (width - size) // 2
        top = int(height * .048)
    left = max(0, min(width - size, left))
    top = max(0, min(height - size, top))
    portrait = ImageOps.fit(_head_crop(face).convert('RGB'), (size, size), Image.Resampling.LANCZOS)
    rgb = np.asarray(portrait, dtype=np.float32)
    edge = max(3, size // 12)
    corners = np.concatenate((rgb[:edge, :edge].reshape(-1, 3), rgb[:edge, -edge:].reshape(-1, 3), rgb[-edge:, :edge].reshape(-1, 3), rgb[-edge:, -edge:].reshape(-1, 3)))
    background = np.median(corners, axis=0)
    distance = np.linalg.norm(rgb - background, axis=2)
    alpha = np.clip((distance - 10) * 15, 0, 255).astype(np.uint8)
    oval = Image.new('L', (size, size), 0)
    ImageDraw.Draw(oval).ellipse((2, 2, size - 3, size - 3), fill=255)
    alpha = np.minimum(alpha, np.asarray(oval))
    fade = np.ones(size, dtype=np.float32)
    start = int(size * .83)
    fade[start:] = np.linspace(1, 0, size - start)
    alpha = (alpha.astype(np.float32) * fade[:, None]).astype(np.uint8)
    mask = Image.fromarray(alpha, 'L').filter(ImageFilter.GaussianBlur(max(2, size // 40)))
    merged = body.convert('RGB').copy()
    merged.paste(portrait, (left, top), mask)
    return merged


def _keep_face_details(body, face):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
    if detector.empty():
        return body
    source = cv2.cvtColor(np.asarray(face.convert('RGB')), cv2.COLOR_RGB2GRAY)
    target = cv2.cvtColor(np.asarray(body.convert('RGB')), cv2.COLOR_RGB2GRAY)
    face_boxes = detector.detectMultiScale(source, scaleFactor=1.05, minNeighbors=3, minSize=(40, 40))
    body_boxes = detector.detectMultiScale(target[:int(body.height * .24)], scaleFactor=1.05, minNeighbors=3, minSize=(25, 25))
    body_boxes = [box for box in body_boxes if box[1] + box[3] / 2 < body.height * .2 and box[2] >= body.width * .08]
    if not len(face_boxes) or not len(body_boxes):
        return body
    sx, sy, sw, sh = max(face_boxes, key=lambda item: item[2] * item[3])
    x, y, w, h = max(body_boxes, key=lambda item: item[2] * item[3])
    crop = face.crop((int(sx), int(sy), int(sx + sw), int(sy + sh)))
    crop = ImageOps.fit(crop, (int(w), int(h)), Image.Resampling.LANCZOS)
    mask = Image.new('L', (int(w), int(h)), 0)
    ImageDraw.Draw(mask).ellipse((int(w * .09), int(h * .05), int(w * .91), int(h * .95)), fill=205)
    mask = mask.filter(ImageFilter.GaussianBlur(max(4, int(w) // 12)))
    result = body.convert('RGB').copy()
    result.paste(crop, (int(x), int(y)), mask)
    return result


def _save_cartoon_stage(args, name, image):
    if os.getenv('META_AVATAR_LOCAL_DEBUG_STAGES', '0') == '1':
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path.with_name(path.stem + '.' + name + '.png'), format='PNG')


def _encode_face(args):
    import torch
    from safetensors.torch import save_file
    from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

    models_dir = Path(args.models_dir).expanduser().resolve()
    adapter_dir = models_dir / FACE_ADAPTER_MODEL_FOLDER
    choice = _face_adapter_choice()
    if choice != 'plus':
        raise LocalWorkerError('Face adapter encoding needs META_AVATAR_LOCAL_FACE_ADAPTER=plus.')
    if not all((adapter_dir / name).is_file() and (adapter_dir / name).stat().st_size > 0 for name in _face_adapter_files(choice)):
        raise LocalWorkerError('The face identity model is missing. Download the local quality models in the launcher.')
    device = _pick_device(args.device)
    _use_local_model_folders(models_dir)
    dtype = torch.float32 if device == 'cpu' else torch.float16
    face = _photo_face(args.photo).convert('RGB')
    processor = CLIPImageProcessor()
    pixels = processor(images=face, return_tensors='pt').pixel_values.to(device=device, dtype=dtype)
    encoder = CLIPVisionModelWithProjection.from_pretrained(
        str(adapter_dir / 'models' / 'image_encoder'), torch_dtype=dtype,
        use_safetensors=True, local_files_only=True).to(device)
    encoder.eval()
    with torch.inference_mode():
        positive = encoder(pixels, output_hidden_states=True).hidden_states[-2]
        negative = encoder(torch.zeros_like(pixels), output_hidden_states=True).hidden_states[-2]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_file({'face': torch.cat((negative.unsqueeze(0), positive.unsqueeze(0))).cpu().contiguous()}, str(output))
    del encoder, pixels, face, positive, negative
    if device == 'mps':
        torch.mps.empty_cache()
    gc.collect()


def _load_face_embeds(path, device):
    from safetensors.torch import load_file

    data = load_file(str(path))['face']
    if tuple(data.shape) != (2, 1, 257, 1280):
        raise LocalWorkerError('The face identity data is invalid. Generate the image again.')
    return [data.to(device)]


def _clean_cartoon_background(image):
    import rembg
    from PIL import Image

    session = rembg.new_session(BACKGROUND_MODEL)
    cutout = rembg.remove(image.convert('RGB'), session=session).convert('RGBA')
    del session
    box = cutout.getchannel('A').getbbox()
    if not box:
        raise LocalWorkerError('The background remover could not find the generated person.')
    person = cutout.crop(box)
    width, height = image.size
    scale = min(width * .76 / person.width, height * .88 / person.height)
    size = (max(1, int(person.width * scale)), max(1, int(person.height * scale)))
    person = person.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', image.size, (220, 220, 220, 255))
    canvas.alpha_composite(person, ((width - person.width) // 2, (height - person.height) // 2))
    return canvas.convert('RGB')


def _load_cartoon_pipeline(model_dir, quality_dir, device, adapter_dir=None):
    import torch
    from diffusers import AutoencoderKL, DPMSolverMultistepScheduler, StableDiffusionImg2ImgPipeline, UNet2DConditionModel

    dtype = torch.float32 if device == 'cpu' else torch.float16
    unet = UNet2DConditionModel.from_pretrained(
        str(quality_dir / 'unet'), torch_dtype=dtype, variant='fp16', use_safetensors=True, local_files_only=True)
    vae = AutoencoderKL.from_pretrained(
        str(quality_dir / 'vae'), torch_dtype=dtype, variant='fp16', use_safetensors=True, local_files_only=True)
    pipeline = StableDiffusionImg2ImgPipeline.from_pretrained(
        str(model_dir), unet=unet, vae=vae, torch_dtype=dtype, variant='fp16', use_safetensors=True,
        safety_checker=None, requires_safety_checker=False, local_files_only=True)
    try:
        from diffusers import DEISMultistepScheduler
        pipeline.scheduler = DEISMultistepScheduler.from_pretrained(
            str(quality_dir), subfolder='scheduler', local_files_only=True)
    except (ImportError, OSError, TypeError, ValueError):
        pipeline.scheduler = DPMSolverMultistepScheduler.from_pretrained(
            str(quality_dir), subfolder='scheduler', local_files_only=True,
            algorithm_type='dpmsolver++', use_karras_sigmas=True)
    if adapter_dir is None:
        pipeline.enable_attention_slicing()
    pipeline.vae.enable_slicing()
    if adapter_dir is not None:
        pipeline.load_ip_adapter(
            str(adapter_dir), subfolder='models',
            weight_name=Path(FACE_ADAPTER_WEIGHT).name,
            image_encoder_folder=None, local_files_only=True)
        scale = float(os.getenv('META_AVATAR_LOCAL_FACE_SCALE', '.7'))
        if not 0 <= scale <= 1:
            raise LocalWorkerError('META_AVATAR_LOCAL_FACE_SCALE must be between 0 and 1.')
        pipeline.set_ip_adapter_scale(scale)
    return pipeline.to(device)


def _expand_cartoon(args, model_dir, quality_dir, adapter_dir, device, width, height):
    import torch

    face = _photo_face(args.photo)
    template = _photo_template(face, width, height, args.prompt)
    gc.collect()
    pipeline = _load_cartoon_pipeline(model_dir, quality_dir, device, adapter_dir)
    embeds = _load_face_embeds(args.identity_embeds, device)
    steps = int(os.getenv('META_AVATAR_LOCAL_IMAGE_STEPS', '30'))
    first_strength =max (.52 ,min (.62 ,args.strength +.14 ))
    second_strength =max (.2 ,min (.28 ,args.strength -.18 ))
    with torch.inference_mode():
        first = pipeline(
            prompt=args.prompt, negative_prompt=SHORT_NEGATIVE_PROMPT,
            image=template, strength=first_strength, num_inference_steps=max(20, steps), guidance_scale=6.8,
            ip_adapter_image_embeds=embeds,
            generator=torch.Generator(device='cpu').manual_seed(args.seed + 1000))
        middle = first.images[0].convert('RGB')
        del first
        result = pipeline(
            prompt=args.prompt,
            negative_prompt=SHORT_NEGATIVE_PROMPT,
            image=middle, strength=second_strength, num_inference_steps=max(24, steps), guidance_scale=6.2,
            ip_adapter_image_embeds=embeds,
            generator=torch.Generator(device='cpu').manual_seed(args.seed + 2000))
    cartoon = result.images[0].convert('RGB')
    del pipeline, result, face, template, middle, embeds
    if device == 'mps':
        torch.mps.empty_cache()
    gc.collect()
    return cartoon


def _expand_cartoon_no_adapter(args, model_dir, quality_dir, device, width, height):
    import torch

    pipeline = _load_cartoon_pipeline(model_dir, quality_dir, device)
    face = _photo_face(args.photo)
    face_prompt = args.prompt.replace('polished 3D animated film cartoon', 'stylized 3D animated film cartoon')
    face_prompt = face_prompt.replace('front full body, normal proportions, A-pose, hands and shoes visible,', 'frontal portrait,')
    face_negative = 'photorealistic, different person, big grin, teeth, pasted face, blurry face'
    if 'clean-shaven' in args.prompt.lower():
        face_negative += ', mustache, moustache, beard, stubble'
    if not _prompt_has_tie(args.prompt):
        face_negative += ', tie'
    body_prompt = args.prompt
    if not _prompt_has_tie(args.prompt) and 'no tie' not in body_prompt.lower():
        body_prompt += ', open collar, no tie'
    steps = int(os.getenv('META_AVATAR_LOCAL_IMAGE_STEPS', '30'))
    with torch.inference_mode():
        face_result = pipeline(
            prompt=face_prompt, negative_prompt=face_negative, image=face,
            strength=.32, num_inference_steps=max(30, steps), guidance_scale=6.2,
            generator=torch.Generator(device='cpu').manual_seed(args.seed + 1000))
        stylized = face_result.images[0].convert('RGB')
        del face_result
        _save_cartoon_stage(args, 'face', stylized)
        if device == 'mps':
            torch.mps.empty_cache()
        template = _photo_template(stylized, width, height, args.prompt)
        body_result = pipeline(
            prompt=body_prompt, negative_prompt=_photo_negative(args.prompt),
            image=template, strength=max(.44, min(.5, args.strength + .04)),
            num_inference_steps=max(24, steps), guidance_scale=6.8,
            generator=torch.Generator(device='cpu').manual_seed(args.seed + 2000))
        body = body_result.images[0].convert('RGB')
        del body_result
        _save_cartoon_stage(args, 'body', body)
        if device == 'mps':
            torch.mps.empty_cache()
        joined = _blend_stylized_face(body, stylized)
        _save_cartoon_stage(args, 'joined', joined)
        result = pipeline(
            prompt=body_prompt, negative_prompt=_photo_negative(args.prompt),
            image=joined, strength=max(.18, min(.22, args.strength - .22)),
            num_inference_steps=max(24, steps), guidance_scale=6.2,
            generator=torch.Generator(device='cpu').manual_seed(args.seed + 3000))
    cartoon = result.images[0].convert('RGB')
    _save_cartoon_stage(args, 'final-before-face', cartoon)
    cartoon = _keep_face_details(cartoon, stylized)
    del pipeline, result, face, stylized, template, body, joined
    if device == 'mps':
        torch.mps.empty_cache()
    gc.collect()
    return cartoon


def _name_cartoon(args, model_dir, quality_dir, device, width, height):
    import torch

    pipeline = _load_cartoon_pipeline(model_dir, quality_dir, device)
    template = _body_template(width, height)
    steps = int(os.getenv('META_AVATAR_LOCAL_IMAGE_STEPS', '30'))
    with torch.inference_mode():
        result = pipeline(
            prompt=args.prompt,
            negative_prompt=SHORT_NEGATIVE_PROMPT,
            image=template, strength=.72, num_inference_steps=max(30, steps),
            guidance_scale=7.5,
            generator=torch.Generator(device='cpu').manual_seed(args.seed))
    cartoon = result.images[0].convert('RGB')
    del pipeline, result, template
    if device == 'mps':
        torch.mps.empty_cache()
    gc.collect()
    return cartoon


def _cartoonize(args: argparse.Namespace) -> None:
    models_dir = Path(args.models_dir).expanduser().resolve()
    model_dir = models_dir / CARTOON_MODEL_FOLDER
    quality_dir = models_dir / QUALITY_CARTOON_MODEL_FOLDER
    adapter_dir = models_dir / FACE_ADAPTER_MODEL_FOLDER
    if not (model_dir / 'model_index.json').is_file():
        raise LocalWorkerError('Stable Diffusion is not downloaded yet. Run prepare_local_models.py once while online.')
    if not all((quality_dir / name).is_file() and (quality_dir / name).stat().st_size > 0 for name in QUALITY_CARTOON_FILES):
        raise LocalWorkerError('The local quality image model is not downloaded yet. Run prepare_local_models.py once while online.')
    if not (models_dir / 'u2net' / f'{BACKGROUND_MODEL}.onnx').is_file():
        raise LocalWorkerError('The background removal model is missing. Run prepare_local_models.py once while online.')
    if not args.name_only and _face_adapter_choice() == 'plus':
        choice = _face_adapter_choice()
        if not all((adapter_dir / name).is_file() and (adapter_dir / name).stat().st_size > 0 for name in _face_adapter_files(choice)):
            raise LocalWorkerError('The face identity model is missing. Download the local quality models in the launcher.')
        if not args.identity_embeds or not Path(args.identity_embeds).is_file():
            raise LocalWorkerError('The face identity data is missing. Generate the image again.')
    if not 0.2 <= args.strength <= 0.75:
        raise LocalWorkerError('The cartoon strength must be between 0.2 and 0.75.')
    width, height = _cartoon_size()
    _use_local_model_folders(models_dir)

    import torch
    from PIL import Image, ImageOps

    device = _pick_device(args.device)
    if args.name_only:
        cartoon = _name_cartoon(args, model_dir, quality_dir, device, width, height)
    elif not args.photo:
        raise LocalWorkerError('--photo is required unless --name-only is used.')
    elif args.expand:
        if _face_adapter_choice() == 'plus':
            cartoon = _expand_cartoon(args, model_dir, quality_dir, adapter_dir, device, width, height)
        else:
            cartoon = _expand_cartoon_no_adapter(args, model_dir, quality_dir, device, width, height)
    else:
        import rembg

        person = rembg.remove(Image.open(args.photo).convert('RGB'), session=rembg.new_session(BACKGROUND_MODEL))
        person = ImageOps.contain(person.convert('RGBA'), (width, height), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (width, height), (190, 190, 190, 255))
        canvas.paste(person, ((width - person.width) // 2, (height - person.height) // 2), person)
        adapter = adapter_dir if _face_adapter_choice() == 'plus' else None
        pipeline = _load_cartoon_pipeline(model_dir, quality_dir, device, adapter)
        embeds = _load_face_embeds(args.identity_embeds, device) if adapter is not None else None
        with torch.inference_mode():
            tmp = dict(
                prompt=args.prompt, negative_prompt=CARTOON_NEGATIVE_PROMPT,
                image=canvas.convert('RGB'), strength=args.strength,
                num_inference_steps=int(os.getenv('META_AVATAR_LOCAL_IMAGE_STEPS', '30')),
                guidance_scale=7.5, generator=torch.Generator(device='cpu').manual_seed(args.seed))
            if embeds is not None:
                tmp['ip_adapter_image_embeds'] = embeds
            result = pipeline(**tmp)
        cartoon = result.images[0]
        del pipeline, result, embeds
        if device == 'mps':
            torch.mps.empty_cache()
        gc.collect()

    cartoon = _clean_cartoon_background(cartoon)
    if not _passes_safety_checker(cartoon, model_dir):
        raise ResultFlagged('The image model flagged this result.')
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cartoon.save(output_path, format='PNG')


def _cartoon_size() -> tuple[int, int]:
    text = os.getenv('META_AVATAR_LOCAL_IMAGE_SIZE', '512x768').lower()
    try:
        width, height = (int(part) for part in text.split('x'))
    except ValueError as error:
        raise LocalWorkerError('META_AVATAR_LOCAL_IMAGE_SIZE must look like 512x768.') from error
    if not (256 <= width <= 1024 and 256 <= height <= 1024 and width % 8 == 0 and height % 8 == 0):
        raise LocalWorkerError('META_AVATAR_LOCAL_IMAGE_SIZE must use multiples of 8 from 256 to 1024.')
    return width, height


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
    cutout = commands.add_parser('cutout', help='image to person-only PNG')
    cutout.add_argument('--image', required=True)
    cutout.add_argument('--output', required=True)
    cutout.add_argument('--models-dir', required=True)
    encode_face = commands.add_parser('encode-face', help='photo face to identity data')
    encode_face.add_argument('--photo', required=True)
    encode_face.add_argument('--output', required=True)
    encode_face.add_argument('--models-dir', required=True)
    encode_face.add_argument('--device', required=True)
    cartoonize = commands.add_parser('cartoonize', help='photo to cartoon image')
    cartoonize.add_argument('--photo')
    cartoonize.add_argument('--output', required=True)
    cartoonize.add_argument('--prompt', required=True)
    cartoonize.add_argument('--models-dir', required=True)
    cartoonize.add_argument('--device', required=True)
    cartoonize.add_argument('--strength', type=float, default=.42)
    cartoonize.add_argument('--seed', type=int, required=True)
    cartoonize.add_argument('--expand', action='store_true')
    cartoonize.add_argument('--name-only', action='store_true')
    cartoonize.add_argument('--identity-embeds')
    args = parser.parse_args()
    try:
        if args.command == 'cartoonize':
            _cartoonize(args)
        elif args.command == 'encode-face':
            _encode_face(args)
        elif args.command == 'cutout':
            _cutout(args)
        else:
            _reconstruct(args)
    except ResultFlagged as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(FLAGGED_EXIT_CODE)
    except Exception as error:
        message = str(error)
        if 'out of memory' in message.lower() or 'cannot allocate memory' in message.lower():
            message = 'The local model ran out of memory. Close other programs and try again.'
        print(message, file=sys.stderr)
        raise SystemExit(1)
    finally:
        gc.collect()


if __name__ == '__main__':
    main()
