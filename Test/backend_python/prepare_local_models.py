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
    if not present(source, ['tsr/system.py']):
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir', default=str(DEFAULT_DIR), help='where to store the models')
    root = Path(parser.parse_args().dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(root / '.cache')

    download_triposr(root)
    download_background_model(root)
    download_cartoon_model(root)

    if not present(root, ['TripoSR/model/model.ckpt', 'TripoSR/source/tsr/system.py', f'u2net/{BACKGROUND_MODEL}.onnx']) or not present(root / 'stable-diffusion-v1-5', CARTOON_FILES):
        raise SystemExit('Some model files are still missing. Run the script again.')
    print(f'Local models are ready in {root}')


if __name__ == '__main__':
    main()
