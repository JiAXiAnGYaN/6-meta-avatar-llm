"""Small window that prepares and starts the Meta Avatar demo.

1. Download Local Models  - TripoSR, u2net and Stable Diffusion (once, online)
2. Prepare Ollama Models  - pulls Flux and Qwen into Ollama (once, online)
3. Start Program          - starts the backend and opens the Unity project

Everything except the GPT buttons works offline after steps 1 and 2.
"""

from __future__ import annotations

import json
import os
import queue
import re
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
# Ollama removed image generation after 0.32.5. Newer versions still run
# Qwen, but Flux fails and the photo buttons fall back to Stable Diffusion.
LAST_OLLAMA_WITH_IMAGES = (0, 32, 5)
REQUIRED_MODEL_FILES = [
    'TripoSR/model/model.ckpt',
    'TripoSR/source/tsr/system.py',
    'u2net/u2net.onnx',
    'stable-diffusion-v1-5/unet/diffusion_pytorch_model.fp16.safetensors',
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
    check = subprocess.run(native([str(python), '-c', 'import fastapi, multipart, mediapipe, torch, diffusers, rembg, trimesh, skimage']),
                           cwd=BACKEND_DIR, capture_output=True, text=True)
    if check.returncode != 0:
        send('status', 'Installing Python packages. The first time takes several minutes...')
        run_logged([str(python), '-m', 'pip', 'install', '-r', str(BACKEND_DIR / 'requirements.txt')],
                   'Could not install the Python packages. See the log above.')
    return python


def models_ready() -> bool:
    return all((MODELS_DIR / name).is_file() for name in REQUIRED_MODEL_FILES)


def download_models() -> None:
    try:
        python = python_environment()
        send('status', 'Downloading local models (about 5 GB). Keep this window open...')
        run_logged([str(python), '-u', str(BACKEND_DIR / 'prepare_local_models.py'), '--dir', str(MODELS_DIR)],
                   'The model download stopped. Check the internet connection and click the button again.')
        send('done', 'Local models are ready.')
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


def ensure_ollama(url: str) -> str:
    """Start `ollama serve` if nothing answers yet. Returns the running version."""
    global ollama_server
    version = ollama_version(url)
    if version:
        return version
    executable = shutil.which('ollama')
    if not executable:
        raise RuntimeError('Ollama is not installed. Install Ollama 0.32.5 from github.com/ollama/ollama/releases.')
    ollama_server = subprocess.Popen([executable, 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        version = ollama_version(url)
        if version:
            return version
    raise RuntimeError('Ollama did not start. Open the Ollama app and try again.')


def version_warning(version: str) -> str:
    numbers = tuple(int(part) for part in re.findall(r'\d+', version)[:3])
    if numbers > LAST_OLLAMA_WITH_IMAGES:
        return (f'Ollama {version} cannot generate images. Flux needs Ollama 0.32.5; '
                'until then the photo buttons use Stable Diffusion instead.')
    return ''


def prepare_ollama(url: str, image_model: str, text_model: str) -> None:
    try:
        version = ensure_ollama(url)
        warning = version_warning(version)
        if warning:
            send('log', 'WARNING: ' + warning)
        for model in (text_model, image_model):
            send('status', f'Pulling {model} into Ollama...')
            run_logged([shutil.which('ollama'), 'pull', model], f'Could not pull {model}.')
        send('done', 'Ollama models are ready.' + (' ' + warning if warning else ''))
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


def start_program(api_key: str, url: str, image_model: str, text_model: str) -> None:
    global backend
    try:
        if not port_free():
            raise RuntimeError(f'Port {BACKEND_PORT} is already in use. Stop the other backend first.')
        if not models_ready():
            raise RuntimeError('The local models are missing. Click "Download Local Models" once while online.')
        python = python_environment()
        try:
            warning = version_warning(ensure_ollama(url))
            if warning:
                send('log', 'WARNING: ' + warning)
        except RuntimeError as error:
            send('log', f'WARNING: {error} The Ollama buttons will not work.')
        send('status', 'Starting the backend...')
        env = os.environ.copy()
        env.update({
            'META_AVATAR_LOCAL_MODELS': str(MODELS_DIR),
            'META_AVATAR_OLLAMA_IMAGE_API_URL': url,
            'META_AVATAR_OLLAMA_TEXT_API_URL': url,
            'META_AVATAR_OLLAMA_IMAGE_MODEL': image_model,
            'META_AVATAR_OLLAMA_TEXT_MODEL': text_model,
            # Everything is on disk already; skip the online checks.
            'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1',
        })
        if api_key:
            env['OPENAI_API_KEY'] = api_key
        backend = subprocess.Popen(native([str(python), str(BACKEND_DIR / 'main.py')]), cwd=BACKEND_DIR, env=env,
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        threading.Thread(target=read_backend_output, daemon=True).start()
        wait_for_backend()
        if unity_already_open():
            send('running', 'Backend is ready. Unity is already open; press Play there.')
            return
        send('status', 'Backend is ready. Opening Unity...')
        subprocess.Popen([str(unity_editor()), '-projectPath', str(UNITY_DIR)], cwd=UNITY_DIR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        send('running', 'Running. Open SampleScene in Unity and press Play. Keep this window open.')
    except Exception as error:
        stop_backend(quiet=True)
        send('error', str(error))


def stop_backend(quiet: bool = False) -> None:
    global backend
    if backend is not None and backend.poll() is None:
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
    backend = None
    if not quiet:
        send('stopped', 'Backend stopped.')


def main() -> None:
    window = tk.Tk()
    window.title('Meta Avatar Launcher')
    window.geometry('700x640')
    window.minsize(580, 560)
    frame = tk.Frame(window, padx=18, pady=16)
    frame.pack(fill='both', expand=True)

    def field(label: str, value: str = '', secret: bool = False) -> tk.Entry:
        tk.Label(frame, text=label, anchor='w').pack(fill='x')
        entry = tk.Entry(frame, show='*' if secret else '')
        entry.insert(0, value)
        entry.pack(fill='x', pady=(3, 8), ipady=4)
        return entry

    key_entry = field('OpenAI API key (only for the GPT buttons, not saved)', os.getenv('OPENAI_API_KEY', ''), secret=True)
    url_entry = field('Ollama URL', 'http://127.0.0.1:11434/api/generate')
    image_entry = field('Ollama image model', 'x/flux2-klein:4b')
    text_entry = field('Ollama text and vision model', 'qwen3.5:4b')

    setup_row = tk.Frame(frame)
    setup_row.pack(fill='x', pady=(4, 6))
    download_button = tk.Button(setup_row, text='1. Download Local Models', height=2)
    download_button.pack(side='left', fill='x', expand=True)
    ollama_button = tk.Button(setup_row, text='2. Prepare Ollama Models', height=2)
    ollama_button.pack(side='left', fill='x', expand=True, padx=(10, 0))

    run_row = tk.Frame(frame)
    run_row.pack(fill='x')
    start_button = tk.Button(run_row, text='Start Program', height=2)
    start_button.pack(side='left', fill='x', expand=True)
    stop_button = tk.Button(run_row, text='Stop Backend', height=2, state='disabled')
    stop_button.pack(side='left', fill='x', expand=True, padx=(10, 0))

    first_hint = 'Ready. Click Start Program.' if models_ready() else 'First time: click 1 and 2 while online, then Start Program.'
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

    def ollama_settings() -> tuple[str, str, str]:
        return url_entry.get().strip(), image_entry.get().strip(), text_entry.get().strip()

    def in_background(target, *args) -> None:
        set_busy(True)
        status.set('Working...')
        threading.Thread(target=target, args=args, daemon=True).start()

    def start() -> None:
        url, image_model, text_model = ollama_settings()
        in_background(start_program, key_entry.get().strip(), url, image_model, text_model)

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
