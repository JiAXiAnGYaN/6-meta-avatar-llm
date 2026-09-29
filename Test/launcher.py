"""Small window that prepares and starts the Meta Avatar demo.

1. Download Core + Quality - TripoSR, u2net and DreamShaper 8 (once, online)
2. Prepare Qwen           - pulls the text, vision and chat model into Ollama (once, online)
3. Start Program          - starts the backend and opens the Unity project

Generation and chat work offline after steps 1 and 2 while Ollama is running.
The German MP list needs internet the first time it is downloaded or refreshed.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / 'backend_python'
UNITY_DIR = ROOT / 'frontend_unity'
MODELS_DIR = BACKEND_DIR / 'local_models'
BACKEND_PORT = 8000
REQUIRED_MODEL_FILES = [
    'TripoSR/model/config.yaml',
    'TripoSR/model/model.ckpt',
    'TripoSR/source/tsr/system.py',
    'TripoSR/source/tsr/utils.py',
    'TripoSR/source/tsr/models/isosurface.py',
    'TripoSR/source/tsr/models/nerf_renderer.py',
    'TripoSR/source/tsr/models/network_utils.py',
    'TripoSR/source/tsr/models/tokenizers/image.py',
    'TripoSR/source/tsr/models/tokenizers/triplane.py',
    'TripoSR/source/tsr/models/transformer/attention.py',
    'TripoSR/source/tsr/models/transformer/basic_transformer_block.py',
    'TripoSR/source/tsr/models/transformer/transformer_1d.py',
    'u2net/u2net.onnx',
    'stable-diffusion-v1-5/model_index.json',
    'stable-diffusion-v1-5/feature_extractor/preprocessor_config.json',
    'stable-diffusion-v1-5/scheduler/scheduler_config.json',
    'stable-diffusion-v1-5/tokenizer/merges.txt',
    'stable-diffusion-v1-5/tokenizer/special_tokens_map.json',
    'stable-diffusion-v1-5/tokenizer/tokenizer_config.json',
    'stable-diffusion-v1-5/tokenizer/vocab.json',
    'stable-diffusion-v1-5/safety_checker/config.json',
    'stable-diffusion-v1-5/safety_checker/model.fp16.safetensors',
    'stable-diffusion-v1-5/text_encoder/config.json',
    'stable-diffusion-v1-5/text_encoder/model.fp16.safetensors',
    'stable-diffusion-v1-5/unet/config.json',
    'stable-diffusion-v1-5/unet/diffusion_pytorch_model.fp16.safetensors',
    'stable-diffusion-v1-5/vae/config.json',
    'stable-diffusion-v1-5/vae/diffusion_pytorch_model.fp16.safetensors',
    'dreamshaper-8/model_index.json',
    'dreamshaper-8/scheduler/scheduler_config.json',
    'dreamshaper-8/unet/config.json',
    'dreamshaper-8/unet/diffusion_pytorch_model.fp16.safetensors',
    'dreamshaper-8/vae/config.json',
    'dreamshaper-8/vae/diffusion_pytorch_model.fp16.safetensors',
]
OPTIONAL_FACE_FILES = [
    'ip-adapter-face/models/ip-adapter-plus-face_sd15.safetensors',
    'ip-adapter-face/models/image_encoder/config.json',
    'ip-adapter-face/models/image_encoder/model.safetensors',
]

backend = None
ollama_server = None
events = queue.Queue()


def send(kind: str, text: str = '') -> None:
    events.put((kind, text))


def venv_python() -> Path:
    if os.name == 'nt':
        return BACKEND_DIR / '.venv' / 'Scripts' / 'python.exe'
    return BACKEND_DIR / '.venv' / 'bin' / 'python'


def base_python() -> str:
    """A Python 3.10-3.12 to build the virtual environment with."""
    for version in ('3.12', '3.11', '3.10'):
        framework = Path(f'/Library/Frameworks/Python.framework/Versions/{version}/bin/python3')
        if framework.is_file():
            return str(framework)
        found = shutil.which(f'python{version}')
        if found:
            return found
    if (3, 10) <= sys.version_info[:2] <= (3, 12):
        return sys.executable
    raise RuntimeError('Python 3.10, 3.11 or 3.12 is needed. Install one from python.org.')


def native(command: list[str]) -> list[str]:
    """On Apple Silicon, make sure Python runs natively even if the launcher runs under Rosetta."""
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.optional.arm64'], text=True, capture_output=True)
        if result.stdout.strip() == '1':
            return ['/usr/bin/arch', '-arm64', *command]
    return command


def run_logged(command: list[str], failure: str) -> None:
    """Run a command and stream its output into the launcher log."""
    process = subprocess.Popen(native(command), cwd=BACKEND_DIR, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, bufsize=1)
    for line in process.stdout:
        line = line.rstrip()
        # Download bars redraw the same line many times; keep only finished ones.
        if line and ('%|' not in line or '100%' in line):
            send('log', line[-300:])
    if process.wait() != 0:
        raise RuntimeError(failure)


def python_environment() -> Path:
    python = venv_python()
    if not python.is_file():
        send('status', 'Creating the Python environment...')
        run_logged([base_python(), '-m', 'venv', str(BACKEND_DIR / '.venv')], 'Could not create the Python environment.')
    requirements=BACKEND_DIR/'requirements.txt'
    wanted=hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp=python.parent.parent/'.requirements.sha256'
    check = subprocess.run(native([str(python), '-c', 'import fastapi,uvicorn,mediapipe,certifi,multipart,numpy,rembg,onnxruntime,torch,transformers,huggingface_hub,omegaconf,einops,trimesh,skimage,imageio,diffusers,accelerate,safetensors']),
                           cwd=BACKEND_DIR, capture_output=True, text=True)
    current=stamp.read_text().strip()if stamp.is_file()else ''
    if check.returncode != 0 or current!=wanted:
        send('status', 'Installing Python packages. The first time takes several minutes...')
        run_logged([str(python), '-m', 'pip', 'install', '-r', str(requirements)],
                   'Could not install the Python packages. See the log above.')
        stamp.write_text(wanted)
    return python


def models_ready() -> bool:
    files =all((MODELS_DIR /name ).is_file ()and (MODELS_DIR /name ).stat ().st_size >0 for name in REQUIRED_MODEL_FILES )
    dino =any(x.is_file()and x.stat().st_size>0 for x in MODELS_DIR.glob('.cache/hub/models--facebook--dino-vitb16/snapshots/*/config.json'))
    return files and dino


def download_models() -> None:
    try:
        python = python_environment()
        send('status', 'Downloading Core + Quality models (about 7 GB total). Keep this window open...')
        run_logged([str(python), '-u', str(BACKEND_DIR / 'prepare_local_models.py'), '--dir', str(MODELS_DIR)],
                   'The model download stopped. Check the internet connection and click the button again.')
        send('done', 'Core + Quality models are ready.')
    except Exception as error:
        send('error', str(error))


def ollama_root(url: str) -> str:
    return url.split('/api/', 1)[0].rstrip('/')


def ollama_version(url: str) -> str | None:
    try:
        with urlopen(ollama_root(url) + '/api/version', timeout=2) as response:
            return json.loads(response.read()).get('version')
    except Exception:
        return None


def ollama_executable() -> str | None:
    found=shutil.which('ollama')
    if found:return found
    for path in (Path('/Applications/Ollama.app/Contents/Resources/ollama'),Path.home()/'AppData/Local/Programs/Ollama/ollama.exe',Path('C:/Program Files/Ollama/ollama.exe')):
        if path.is_file():return str(path)
    return None


def ensure_ollama(url: str) -> str:
    """Start `ollama serve` if nothing answers yet. Returns the running version."""
    global ollama_server
    version = ollama_version(url)
    if version:
        return version
    executable = ollama_executable()
    if not executable:
        raise RuntimeError('Ollama is not installed. Install the current Ollama app and try again.')
    ollama_server = subprocess.Popen([executable, 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        version = ollama_version(url)
        if version:
            return version
    raise RuntimeError('Ollama did not start. Open the Ollama app and try again.')


def prepare_ollama(url: str, text_model: str) -> None:
    try:
        version = ensure_ollama(url)
        send('log', f'Ollama {version} is running.')
        executable=ollama_executable()
        if not executable:raise RuntimeError('The Ollama service is running, but its command-line tool was not found. Open a terminal and run ollama pull '+text_model+'.')
        send('status', f'Pulling {text_model} into Ollama...')
        run_logged([executable, 'pull', text_model], f'Could not pull {text_model}.')
        send('done', 'Qwen is ready for local photo analysis and chat.')
    except Exception as error:
        send('error', str(error))


def port_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', BACKEND_PORT))
            return True
        except OSError:
            return False


def wait_for_backend() -> None:
    deadline = time.time() + 120
    while time.time() < deadline:
        if backend is None or backend.poll() is not None:
            raise RuntimeError('The backend stopped during startup. See the log above.')
        try:
            with urlopen(f'http://127.0.0.1:{BACKEND_PORT}/api/health', timeout=2) as response:
                if json.loads(response.read()).get('status') == 'ok':
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError('The backend did not become ready within two minutes.')


def unity_editor() -> Path:
    version = ''
    version_file = UNITY_DIR / 'ProjectSettings' / 'ProjectVersion.txt'
    for line in version_file.read_text().splitlines():
        if line.startswith('m_EditorVersion:'):
            version = line.split(':', 1)[1].strip()
    candidates = [
        Path('/Applications/Unity/Hub/Editor') / version / 'Unity.app' / 'Contents' / 'MacOS' / 'Unity',
        Path('C:/Program Files/Unity/Hub/Editor') / version / 'Editor' / 'Unity.exe',
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(f'Unity {version} was not found. Install that version with Unity Hub.')


def unity_already_open() -> bool:
    if sys.platform == 'win32':
        return False
    # Unity Hub passes -projectpath in lower case, the launcher uses -projectPath.
    result = subprocess.run(['pgrep', '-if', f'projectpath {UNITY_DIR}'], capture_output=True, text=True)
    return bool(result.stdout.strip())


def read_backend_output() -> None:
    for line in backend.stdout:
        send('log', line.rstrip())


def start_program(api_key: str, hf_token: str, url: str, text_model: str) -> None:
    global backend
    try:
        if not port_free():
            raise RuntimeError(f'Port {BACKEND_PORT} is already in use. Stop the other backend first.')
        local_ready = models_ready()
        if not local_ready and not api_key:
            raise RuntimeError('The Core + Quality models are missing. Download them for local generation, or enter an OpenAI API key for Online Photo 3D only.')
        if local_ready and os.getenv('META_AVATAR_LOCAL_FACE_ADAPTER', 'none').strip().lower() == 'plus':
            if not all((MODELS_DIR / name).is_file() and (MODELS_DIR / name).stat().st_size > 0 for name in OPTIONAL_FACE_FILES):
                raise RuntimeError('The optional face adapter is missing. Run python prepare_local_models.py --face-adapter in backend_python first.')
        python = python_environment()
        if local_ready:
            try:
                version = ensure_ollama(url)
                send('log', f'Ollama {version} is running.')
            except RuntimeError as error:
                send('log', f'WARNING: {error} Qwen photo analysis and Chat will not work.')
        else:
            send('log', 'Local models are not installed. Only Online Photo 3D generation is available; download the local models for the other generation buttons.')
        send('status', 'Starting the backend...')
        env = os.environ.copy()
        env.update({
            'META_AVATAR_LOCAL_MODELS': str(MODELS_DIR),
            'META_AVATAR_OLLAMA_TEXT_API_URL': url,
            'META_AVATAR_OLLAMA_TEXT_MODEL': text_model,
            'OPENAI_API_KEY': api_key,
            'HF_TOKEN': hf_token,
            'HF_HUB_OFFLINE': '0' if api_key else '1',
            'TRANSFORMERS_OFFLINE': '0' if api_key else '1',
        })
        if api_key:
            env['META_AVATAR_OFFLINE'] = '0'
        tmp = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        backend = subprocess.Popen(native([str(python), str(BACKEND_DIR / 'main.py')]), cwd=BACKEND_DIR, env=env,
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, **tmp)
        threading.Thread(target=read_backend_output, daemon=True).start()
        wait_for_backend()
        if unity_already_open():
            send('running', 'Backend is ready. Unity is already open; press Play there.' + (' Only Online Photo 3D generation is available.' if not local_ready else ''))
            return
        send('status', 'Backend is ready. Opening Unity...')
        subprocess.Popen([str(unity_editor()), '-projectPath', str(UNITY_DIR)], cwd=UNITY_DIR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        send('running', 'Running. Open SampleScene in Unity and press Play. Keep this window open.' + (' Only Online Photo 3D generation is available.' if not local_ready else ''))
    except Exception as error:
        stop_backend(quiet=True)
        send('error', str(error))


def stop_backend(quiet: bool = False) -> None:
    global backend
    if backend is not None and backend.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(backend.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(backend.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                backend.kill()
            else:
                try:
                    os.killpg(backend.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    backend = None
    if not quiet:
        send('stopped', 'Backend stopped.')


def main() -> None:
    window = tk.Tk()
    window.title('Meta Avatar Launcher')
    window.geometry('700x680')
    window.minsize(580, 590)
    frame = tk.Frame(window, padx=18, pady=16)
    frame.pack(fill='both', expand=True)

    def field(label: str, value: str = '', secret: bool = False) -> tk.Entry:
        tk.Label(frame, text=label, anchor='w').pack(fill='x')
        entry = tk.Entry(frame, show='*' if secret else '')
        entry.insert(0, value)
        entry.pack(fill='x', pady=(3, 8), ipady=4)
        return entry

    key_entry = field('OpenAI API key (only for the GPT buttons, not saved)', os.getenv('OPENAI_API_KEY', ''), secret=True)
    hf_entry = field('Hugging Face token (optional for online 3D quota, not saved)', os.getenv('HF_TOKEN', ''), secret=True)
    url_entry = field('Ollama URL', 'http://127.0.0.1:11434/api/generate')
    text_entry = field('Local text, vision and chat model', 'qwen3.5:0.8b')

    setup_row = tk.Frame(frame)
    setup_row.pack(fill='x', pady=(4, 6))
    download_button = tk.Button(setup_row, text='1. Download Core + Quality', height=2)
    download_button.pack(side='left', fill='x', expand=True)
    ollama_button = tk.Button(setup_row, text='2. Prepare Qwen', height=2)
    ollama_button.pack(side='left', fill='x', expand=True, padx=(10, 0))

    run_row = tk.Frame(frame)
    run_row.pack(fill='x')
    start_button = tk.Button(run_row, text='Start Program', height=2)
    start_button.pack(side='left', fill='x', expand=True)
    stop_button = tk.Button(run_row, text='Stop Backend', height=2, state='disabled')
    stop_button.pack(side='left', fill='x', expand=True, padx=(10, 0))

    first_hint = 'Ready. Click Start Program.' if models_ready() else 'Download local models for local generation, or enter an OpenAI key for Online Photo 3D only.'
    status = tk.StringVar(value=first_hint)
    tk.Label(frame, textvariable=status, anchor='w', justify='left', wraplength=650).pack(fill='x', pady=(12, 6))
    log = tk.Text(frame, height=14, state='disabled', wrap='word')
    log.pack(fill='both', expand=True)

    busy_buttons = (download_button, ollama_button, start_button)

    def set_busy(busy: bool) -> None:
        for button in busy_buttons:
            button.config(state='disabled' if busy else 'normal')

    def add_log(text: str) -> None:
        log.config(state='normal')
        log.insert('end', text + '\n')
        log.see('end')
        log.config(state='disabled')

    def ollama_settings() -> tuple[str, str]:
        return url_entry.get().strip(), text_entry.get().strip()

    def in_background(target, *args) -> None:
        set_busy(True)
        status.set('Working...')
        threading.Thread(target=target, args=args, daemon=True).start()

    def start() -> None:
        url, text_model = ollama_settings()
        in_background(start_program, key_entry.get().strip(), hf_entry.get().strip(), url, text_model)

    def stop() -> None:
        stop_button.config(state='disabled')
        threading.Thread(target=stop_backend, daemon=True).start()

    def poll_events() -> None:
        try:
            while True:
                kind, text = events.get_nowait()
                if kind == 'log':
                    add_log(text)
                elif kind == 'status':
                    status.set(text)
                elif kind == 'running':
                    status.set(text)
                    stop_button.config(state='normal')
                elif kind in ('done', 'stopped'):
                    status.set(text)
                    set_busy(False)
                elif kind == 'error':
                    status.set(text)
                    add_log('ERROR: ' + text)
                    set_busy(False)
                    messagebox.showerror('Meta Avatar', text)
        except queue.Empty:
            pass
        window.after(100, poll_events)

    def close() -> None:
        if backend is not None and backend.poll() is None:
            if not messagebox.askyesno('Close launcher', 'Closing the launcher stops the backend. Continue?'):
                return
            stop_backend(quiet=True)
        if ollama_server is not None and ollama_server.poll() is None:
            ollama_server.terminate()
        window.destroy()

    download_button.config(command=lambda: in_background(download_models))
    ollama_button.config(command=lambda: in_background(prepare_ollama, *ollama_settings()))
    start_button.config(command=start)
    stop_button.config(command=stop)
    window.protocol('WM_DELETE_WINDOW', close)
    poll_events()
    window.mainloop()


if __name__ == '__main__':
    main()
