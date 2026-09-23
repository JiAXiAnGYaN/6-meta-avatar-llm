import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog,messagebox
from urllib.request import urlopen

tmp1=Path(__file__).resolve().parent
tmp2=tmp1/'backend_python'
tmp3=tmp1/'frontend_unity'
process=None
tmp4=queue.Queue()

def send(kind,text=''):
 tmp4.put((kind,text))

def path1():
 if os.name=='nt':return tmp2/'.venv'/'Scripts'/'python.exe'
 return tmp2/'.venv'/'bin'/'python'

def py0():
 tmp=Path('/Library/Frameworks/Python.framework/Versions/3.10/bin/python3')
 if sys.platform=='darwin'and tmp.is_file():return tmp
 return Path(sys.executable)

def cmd(py,*tmp):
 if sys.platform=='darwin':
  a=subprocess.run(['/usr/sbin/sysctl','-n','hw.optional.arm64'],text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
  if a.stdout.strip()=='1':return ['/usr/bin/arch','-arm64',str(py),*tmp]
 return [str(py),*tmp]

def setup(offline=False):
 tmp99=0
 for i in range(1):tmp99+=i
 py=path1()
 if not py.is_file():
  send('status','Creating Python environment...')
  tmp=subprocess.run(cmd(py0(),'-m','venv',str(tmp2/'.venv')),cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if tmp.returncode!=0:raise RuntimeError(tmp.stdout.strip()or'Could not create the Python environment.')
 tmp=subprocess.run(cmd(py,'-c','import fastapi,uvicorn,mediapipe,certifi,python_multipart,torch,torchvision,diffusers,transformers,huggingface_hub,trimesh,rembg,omegaconf,einops,accelerate,safetensors,skimage,onnxruntime,imageio'),cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 if tmp.returncode!=0:
  if offline:raise RuntimeError('Local Python packages are missing. Turn off offline mode and download the local models first.')
  send('status','Installing Python packages. This can take a few minutes...')
  tmp0=subprocess.run(cmd(py,'-m','pip','install','--upgrade','pip','setuptools','wheel'),cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if tmp0.returncode!=0:raise RuntimeError(tmp0.stdout.strip()or'Could not update the Python installer.')
  a=['-m','pip','install'];
  if'incompatible architecture'in tmp.stdout:a.append('--force-reinstall')
  a+=['-r',str(tmp2/'requirements.txt')]
  tmp=subprocess.run(cmd(py,*a),cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if tmp.returncode!=0:raise RuntimeError(tmp.stdout.strip()or'Could not install the Python packages.')
 return py

def modelpaths(folder):
 root=Path(folder).expanduser().resolve()
 return root,root/'TripoSR',root/'stable-diffusion-v1-5'

def modelsok(folder):
 root,a,b=modelpaths(folder)
 tmp=list((root/'.cache'/'hub'/'models--facebook--dino-vitb16'/'snapshots').glob('*/config.json'))
 tmp2=['model_index.json','feature_extractor/preprocessor_config.json','scheduler/scheduler_config.json','tokenizer/merges.txt','tokenizer/vocab.json','safety_checker/config.json','safety_checker/model.fp16.safetensors','text_encoder/config.json','text_encoder/model.fp16.safetensors','unet/config.json','unet/diffusion_pytorch_model.fp16.safetensors','vae/config.json','vae/diffusion_pytorch_model.fp16.safetensors']
 return (root/'ready.txt').is_file()and(a/'model'/'config.yaml').is_file()and(a/'model'/'model.ckpt').is_file()and(a/'source'/'tsr'/'system.py').is_file()and all((b/i).is_file()for i in tmp2)and(root/'u2net'/'u2netp.onnx').is_file()and bool(tmp)

def envs(env,folder,offline,res):
 root,a,b=modelpaths(folder)
 env['META_AVATAR_3D_MODE']='local'
 env['META_AVATAR_TRIPOSR_PATH']=str(a)
 env['META_AVATAR_LOCAL_IMAGE_MODEL']=str(b)
 env['META_AVATAR_LOCAL_3D_DEVICE']='cpu'
 env['META_AVATAR_LOCAL_IMAGE_DEVICE']='auto'
 env['META_AVATAR_MC_RESOLUTION']=str(res)
 env['META_AVATAR_LOCAL_IMAGE_SIZE']='512x768'
 env['META_AVATAR_LOCAL_PHOTO_STRENGTH']='0.42'
 env['META_AVATAR_OFFLINE']='1'if offline else'0'
 env['HF_HOME']=str(root/'.cache')
 env['U2NET_HOME']=str(root/'u2net')
 env['HF_HUB_DISABLE_XET']='1'
 if offline:
  env['HF_HUB_OFFLINE']='1'
  env['TRANSFORMERS_OFFLINE']='1'
 else:
  env.pop('HF_HUB_OFFLINE',None)
  env.pop('TRANSFORMERS_OFFLINE',None)
 return env

def check():
 tmp=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
 try:
  tmp.bind(('127.0.0.1',8000))
  return True
 except OSError:
  return False
 finally:
  tmp.close()

def wait():
 end=time.time()+90
 while time.time()<end:
  if process is None or process.poll()is not None:raise RuntimeError('The backend stopped before startup completed.')
  try:
   with urlopen('http://127.0.0.1:8000/api/health',timeout=2)as tmp:
    data=json.loads(tmp.read())
   if data.get('status')=='ok':return
  except Exception:
   pass
  time.sleep(.5)
 raise RuntimeError('The backend did not become ready within 90 seconds.')

def path2():
 tmp=tmp3/'ProjectSettings'/'ProjectVersion.txt'
 version=''
 if tmp.is_file():
  for line in tmp.read_text().splitlines():
   if line.startswith('m_EditorVersion:'):
    version=line.split(':',1)[1].strip()
    break
 if sys.platform=='darwin':
  path=Path('/Applications/Unity/Hub/Editor')/version/'Unity.app'/'Contents'/'MacOS'/'Unity'
  if path.is_file():return path
 if os.name=='nt':
  path=Path('C:/Program Files/Unity/Hub/Editor')/version/'Editor'/'Unity.exe'
  if path.is_file():return path
 raise RuntimeError('Unity '+version+' was not found. Install that version with Unity Hub.')

def read():
 if process is None or process.stdout is None:return
 for line in process.stdout:
  send('log',line.rstrip())

def run(key,ollamaUrl,ollamaModel,folder,offline,res):
 global process
 tmp99=0
 for i in range(1):tmp99+=i
 try:
  if not check():raise RuntimeError('Port 8000 is already in use. Stop the old backend with Ctrl+C, then try again.')
  if not modelsok(folder):raise RuntimeError('Local models are missing. Turn off offline mode and click Download Local Models first.')
  py=setup(offline)
  send('status','Starting backend...')
  env=os.environ.copy()
  env['OPENAI_API_KEY']=key
  env['META_AVATAR_OLLAMA_IMAGE_API_URL']=ollamaUrl
  env['META_AVATAR_OLLAMA_IMAGE_MODEL']=ollamaModel
  envs(env,folder,offline,res)
  env.setdefault('META_AVATAR_OPENAI_IMAGE_TIMEOUT','300')
  env.setdefault('META_AVATAR_OPENAI_IMAGE_ATTEMPTS','2')
  process=subprocess.Popen(cmd(py,str(tmp2/'main.py')),cwd=tmp2,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=1)
  threading.Thread(target=read,daemon=True).start()
  wait()
  send('status','Backend is ready. Opening Unity...')
  subprocess.Popen([str(path2()),'-projectPath',str(tmp3)],cwd=tmp3,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  send('running','Program started. Keep this launcher open while using Unity.')
 except Exception as error:
  if process is not None and process.poll()is None:
   process.terminate()
  process=None
  send('error',str(error))

def download(folder):
 try:
  py=setup(False)
  send('status','Downloading local models. Keep the internet connected...')
  tmp=subprocess.Popen(cmd(py,'-u',str(tmp2/'prepare_local_models.py'),'--dir',str(Path(folder).expanduser())),cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=1)
  if tmp.stdout is not None:
   for line in tmp.stdout:send('log',line.rstrip())
  if tmp.wait()!=0:raise RuntimeError('Local model download failed. Read the last log lines and try again.')
  send('downloaded','Local models are ready. You may now turn on fully offline mode.')
 except Exception as error:send('download_error',str(error))

def stop2():
 global process
 if process is not None and process.poll()is None:
  process.terminate()
  try:process.wait(timeout=5)
  except subprocess.TimeoutExpired:process.kill()
 process=None
 send('stopped','Backend stopped.')

def main():
 tmp88=0
 for i in range(1):tmp88+=i
 tmp20=tk.Tk()
 tmp20.title('Meta Avatar Launcher')
 tmp20.geometry('760x760')
 tmp20.minsize(620,650)
 tmp21=tk.Frame(tmp20,padx=18,pady=16)
 tmp21.pack(fill='both',expand=True)
 tk.Label(tmp21,text='OpenAI API Key (optional for local images)',anchor='w',font=('Arial',14)).pack(fill='x')
 tmp22=tk.Entry(tmp21,show='*',font=('Arial',13))
 tmp22.pack(fill='x',pady=(7,5),ipady=6)
 tmp23=tk.BooleanVar(value=False)
 tk.Checkbutton(tmp21,text='Show API Key',variable=tmp23,command=lambda:tmp22.config(show=''if tmp23.get()else'*')).pack(anchor='w')
 tk.Label(tmp21,text='The key is used only by the backend process and is not saved.',anchor='w').pack(fill='x',pady=(2,12))
 tk.Label(tmp21,text='Ollama image URL',anchor='w',font=('Arial',12)).pack(fill='x')
 tmp30=tk.Entry(tmp21,font=('Arial',12))
 tmp30.insert(0,'http://127.0.0.1:11434/api/generate')
 tmp30.pack(fill='x',pady=(4,8),ipady=4)
 tk.Label(tmp21,text='Ollama image model',anchor='w',font=('Arial',12)).pack(fill='x')
 tmp31=tk.Entry(tmp21,font=('Arial',12))
 tmp31.insert(0,'x/flux2-klein:4b')
 tmp31.pack(fill='x',pady=(4,10),ipady=4)
 tk.Label(tmp21,text='Ollama comparison needs version 0.32.5 and enough unified memory.',anchor='w').pack(fill='x',pady=(0,8))
 tk.Label(tmp21,text='Local model folder',anchor='w',font=('Arial',12)).pack(fill='x')
 tmp32=tk.Frame(tmp21)
 tmp32.pack(fill='x',pady=(4,6))
 tmp33=tk.Entry(tmp32,font=('Arial',11))
 tmp33.insert(0,str(tmp2/'local_models'))
 tmp33.pack(side='left',fill='x',expand=True,ipady=4)
 def browsefolder():
  a=filedialog.askdirectory(initialdir=tmp33.get()or str(tmp2))
  if a:
   tmp33.delete(0,'end');tmp33.insert(0,a)
 tk.Button(tmp32,text='Browse',command=browsefolder).pack(side='left',padx=(8,0))
 tmp34=tk.BooleanVar(value=False)
 tk.Checkbutton(tmp21,text='Fully offline (use this after the first model download)',variable=tmp34).pack(anchor='w')
 tmp35=tk.Frame(tmp21)
 tmp35.pack(fill='x',pady=(5,8))
 tk.Label(tmp35,text='3D: CPU / cartoon: MPS when available',anchor='w').pack(side='left')
 tk.Label(tmp35,text='3D resolution',anchor='w').pack(side='left',padx=(22,6))
 tmp36=tk.Entry(tmp35,width=7)
 tmp36.insert(0,'128')
 tmp36.pack(side='left')
 tk.Label(tmp35,text='Cartoon size: 512x768',anchor='w').pack(side='left',padx=(22,0))
 tmp37=tk.Button(tmp21,text='Download Local Models',height=2)
 tmp37.pack(fill='x',pady=(0,10))
 tmp24=tk.Frame(tmp21)
 tmp24.pack(fill='x')
 tmp25=tk.Button(tmp24,text='Start Program',height=2)
 tmp25.pack(side='left',fill='x',expand=True)
 tmp26=tk.Button(tmp24,text='Stop Backend',height=2,state='disabled')
 tmp26.pack(side='left',fill='x',expand=True,padx=(10,0))
 tmp27=tk.StringVar(value='First click Download Local Models. After it finishes, the program can run offline.')
 tk.Label(tmp21,textvariable=tmp27,anchor='w',justify='left',wraplength=640).pack(fill='x',pady=(14,8))
 tmp28=tk.Text(tmp21,height=13,state='disabled',wrap='word')
 tmp28.pack(fill='both',expand=True)
 def addLog(text):
  tmp28.config(state='normal')
  tmp28.insert('end',text+'\n')
  tmp28.see('end')
  tmp28.config(state='disabled')
 def start():
  key=tmp22.get().strip()
  ollamaUrl=tmp30.get().strip()or'http://127.0.0.1:11434/api/generate'
  ollamaModel=tmp31.get().strip()or'x/flux2-klein:4b'
  try:
   res=int(tmp36.get().strip())
   if res<32 or res>320 or res%32!=0:raise ValueError()
  except ValueError:
   messagebox.showerror('Bad Resolution','Use a multiple of 32 from 32 to 320. Use 128 on an 8 GB M1 Mac.')
   return
  folder=tmp33.get().strip()
  if not folder:
   messagebox.showerror('Missing Folder','Choose a local model folder.')
   return
  tmp22.delete(0,'end')
  tmp25.config(state='disabled')
  tmp26.config(state='disabled')
  tmp37.config(state='disabled')
  tmp27.set('Preparing program...')
  threading.Thread(target=run,args=(key,ollamaUrl,ollamaModel,folder,tmp34.get(),res),daemon=True).start()
 def download2():
  folder=tmp33.get().strip()
  if not folder:
   messagebox.showerror('Missing Folder','Choose a local model folder.')
   return
  if tmp34.get():
   messagebox.showerror('Offline Mode','Turn off fully offline mode for the first download.')
   return
  tmp25.config(state='disabled');tmp37.config(state='disabled')
  tmp27.set('Preparing the local model download...')
  threading.Thread(target=download,args=(folder,),daemon=True).start()
 def stop():
  tmp26.config(state='disabled')
  threading.Thread(target=stop2,daemon=True).start()
 def update():
  try:
   while True:
    kind,text=tmp4.get_nowait()
    if kind=='log':addLog(text)
    elif kind=='status':tmp27.set(text)
    elif kind=='running':
     tmp27.set(text);tmp26.config(state='normal')
    elif kind=='error':
     tmp27.set(text);addLog('ERROR: '+text);tmp25.config(state='normal');tmp26.config(state='disabled');tmp37.config(state='normal')
     messagebox.showerror('Could not start',text)
    elif kind=='downloaded':
     tmp27.set(text);tmp25.config(state='normal');tmp37.config(state='normal')
     messagebox.showinfo('Download Finished',text)
    elif kind=='download_error':
     tmp27.set(text);addLog('ERROR: '+text);tmp25.config(state='normal');tmp37.config(state='normal')
     messagebox.showerror('Download Failed',text)
    elif kind=='stopped':
     tmp27.set(text);tmp25.config(state='normal');tmp26.config(state='disabled');tmp37.config(state='normal')
  except queue.Empty:
   pass
  tmp20.after(100,update)
 def close():
  if process is not None and process.poll()is None:
   if not messagebox.askyesno('Close Launcher','Closing the launcher will stop the backend. Continue?'):return
   stop2()
  tmp20.destroy()
 tmp25.config(command=start)
 tmp37.config(command=download2)
 tmp26.config(command=stop)
 tmp20.protocol('WM_DELETE_WINDOW',close)
 tmp22.focus_set()
 update()
 tmp20.mainloop()

if __name__=='__main__':main()
