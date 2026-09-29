"""Download every model the backend runs locally. Needs internet once.

    python prepare_local_models.py [--dir local_models]

Files that are already present are skipped, so running it again is cheap.
"""

import argparse
import os
import time
from pathlib import Path

os.environ.setdefault('HF_HUB_DISABLE_XET', '1')

from huggingface_hub import snapshot_download

DEFAULT_DIR = Path(__file__).resolve().parent / 'local_models'
BACKGROUND_MODEL = 'u2net'
CARTOON_REPO = 'stable-diffusion-v1-5/stable-diffusion-v1-5'
QUALITY_CARTOON_REPO = 'Lykon/dreamshaper-8'
FACE_ADAPTER_REPO = 'h94/IP-Adapter'
# Only the fp16 weights: about 2.6 GB instead of 40 GB for the whole repository.
CARTOON_FILES = [
    'model_index.json',
    'feature_extractor/preprocessor_config.json',
    'scheduler/scheduler_config.json',
    'tokenizer/merges.txt',
    'tokenizer/special_tokens_map.json',
    'tokenizer/tokenizer_config.json',
    'tokenizer/vocab.json',
    'safety_checker/config.json',
    'safety_checker/model.fp16.safetensors',
    'text_encoder/config.json',
    'text_encoder/model.fp16.safetensors',
    'unet/config.json',
    'unet/diffusion_pytorch_model.fp16.safetensors',
    'vae/config.json',
    'vae/diffusion_pytorch_model.fp16.safetensors',
]
QUALITY_CARTOON_FILES = [
    'model_index.json',
    'scheduler/scheduler_config.json',
    'unet/config.json',
    'unet/diffusion_pytorch_model.fp16.safetensors',
    'vae/config.json',
    'vae/diffusion_pytorch_model.fp16.safetensors',
]
FACE_ADAPTER_FILES = [
    'models/ip-adapter-plus-face_sd15.safetensors',
    'models/image_encoder/config.json',
    'models/image_encoder/model.safetensors',
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


def present(folder: Path, names: list[str]) -> bool:
    return all((folder / name).is_file() and (folder / name).stat().st_size > 0 for name in names)


def with_retries(label: str, action) -> None:
    print(f'Downloading {label}...', flush=True)
    for attempt in range(1, 5):
        try:
            action()
            return
        except Exception as error:
            if attempt == 4:
                raise
            print(f'Connection dropped ({error}). Retrying {attempt + 1}/4...', flush=True)
            time.sleep(2 * attempt)


def download_triposr(root: Path) -> None:
    weights = root / 'TripoSR' / 'model'
    if not present(weights, ['config.yaml', 'model.ckpt']):
        with_retries('TripoSR weights', lambda: snapshot_download(
            repo_id='stabilityai/TripoSR', local_dir=str(weights), max_workers=2))
    source = root / 'TripoSR' / 'source'
    if not present(source, TRIPOSR_SOURCE_FILES):
        # The model repository has no code; the Space next to it does.
        with_retries('TripoSR source code', lambda: snapshot_download(
            repo_id='stabilityai/TripoSR', repo_type='space', local_dir=str(source),
            allow_patterns=['tsr/**'], max_workers=2))
    # TripoSR builds its image encoder from the DINO config, not the DINO weights.
    with_retries('DINO config', lambda: snapshot_download(
        repo_id='facebook/dino-vitb16', cache_dir=str(root / '.cache' / 'hub'),
        allow_patterns=['config.json']))


def download_background_model(root: Path) -> None:
    folder = root / 'u2net'
    if present(folder, [f'{BACKGROUND_MODEL}.onnx']):
        return
    folder.mkdir(parents=True, exist_ok=True)
    os.environ['U2NET_HOME'] = str(folder)
    from rembg import new_session
    with_retries(f'{BACKGROUND_MODEL} background removal model', lambda: new_session(BACKGROUND_MODEL))


def download_cartoon_model(root: Path) -> None:
    folder = root / 'stable-diffusion-v1-5'
    if present(folder, CARTOON_FILES):
        return
    with_retries('Stable Diffusion 1.5 (fp16)', lambda: snapshot_download(
        repo_id=CARTOON_REPO, local_dir=str(folder), allow_patterns=CARTOON_FILES, max_workers=2))


def download_quality_cartoon_model(root: Path) -> None:
    folder = root / 'dreamshaper-8'
    if present(folder, QUALITY_CARTOON_FILES):
        return
    with_retries('DreamShaper 8 quality UNet and VAE (fp16)', lambda: snapshot_download(
        repo_id=QUALITY_CARTOON_REPO, local_dir=str(folder), allow_patterns=QUALITY_CARTOON_FILES, max_workers=2))


def download_face_adapter(root: Path) -> None:
    folder = root / 'ip-adapter-face'
    if present(folder, FACE_ADAPTER_FILES):
        return
    with_retries('optional IP-Adapter Plus Face and CLIP image encoder', lambda: snapshot_download(
        repo_id=FACE_ADAPTER_REPO, local_dir=str(folder), allow_patterns=FACE_ADAPTER_FILES, max_workers=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir', default=str(DEFAULT_DIR), help='where to store the models')
    parser.add_argument('--face-adapter', action='store_true', help='also download the optional face guide for machines with at least 16 GB RAM')
    args = parser.parse_args()
    root = Path(args.dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(root / '.cache')

    download_triposr(root)
    download_background_model(root)
    download_cartoon_model(root)
    download_quality_cartoon_model(root)
    if args.face_adapter:
        download_face_adapter(root)

    if not present(root, ['TripoSR/model/model.ckpt', f'u2net/{BACKGROUND_MODEL}.onnx']) or not present(root / 'TripoSR/source', TRIPOSR_SOURCE_FILES) or not present(root / 'stable-diffusion-v1-5', CARTOON_FILES) or not present(root / 'dreamshaper-8', QUALITY_CARTOON_FILES):
        raise SystemExit('Some model files are still missing. Run the script again.')
    if args.face_adapter and not present(root / 'ip-adapter-face', FACE_ADAPTER_FILES):
        raise SystemExit('The optional face adapter files are still missing. Run the script again with --face-adapter.')
    print(f'Local models are ready in {root}')


if __name__ == '__main__':
    main()
