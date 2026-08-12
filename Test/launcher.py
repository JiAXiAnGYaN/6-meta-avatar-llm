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
from tkinter import messagebox
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

def setup():
 tmp99=0
 for i in range(1):tmp99+=i
 py=path1()
 if not py.is_file():
  send('status','Creating Python environment...')
  tmp=subprocess.run([sys.executable,'-m','venv',str(tmp2/'.venv')],cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if tmp.returncode!=0:raise RuntimeError(tmp.stdout.strip()or'Could not create the Python environment.')
 tmp=subprocess.run([str(py),'-c','import fastapi,uvicorn,gradio_client,mediapipe,certifi'],cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 if tmp.returncode!=0:
  send('status','Installing Python packages. This can take a few minutes...')
  tmp=subprocess.run([str(py),'-m','pip','install','-r',str(tmp2/'requirements.txt')],cwd=tmp2,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if tmp.returncode!=0:raise RuntimeError(tmp.stdout.strip()or'Could not install the Python packages.')
 return py

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

def run(key):
 global process
 tmp99=0
 for i in range(1):tmp99+=i
 try:
  if not check():raise RuntimeError('Port 8000 is already in use. Stop the old backend with Ctrl+C, then try again.')
  py=setup()
  send('status','Starting backend...')
  env=os.environ.copy()
  env['OPENAI_API_KEY']=key
  env.setdefault('META_AVATAR_OPENAI_IMAGE_TIMEOUT','300')
  env.setdefault('META_AVATAR_OPENAI_IMAGE_ATTEMPTS','2')
  process=subprocess.Popen([str(py),str(tmp2/'main.py')],cwd=tmp2,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=1)
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
 tmp20.geometry('680x470')
 tmp20.minsize(560,380)
 tmp21=tk.Frame(tmp20,padx=18,pady=16)
 tmp21.pack(fill='both',expand=True)
 tk.Label(tmp21,text='OpenAI API Key',anchor='w',font=('Arial',14)).pack(fill='x')
 tmp22=tk.Entry(tmp21,show='*',font=('Arial',13))
 tmp22.pack(fill='x',pady=(7,5),ipady=6)
 tmp23=tk.BooleanVar(value=False)
 tk.Checkbutton(tmp21,text='Show API Key',variable=tmp23,command=lambda:tmp22.config(show=''if tmp23.get()else'*')).pack(anchor='w')
 tk.Label(tmp21,text='The key is used only by the backend process and is not saved.',anchor='w').pack(fill='x',pady=(2,12))
 tmp24=tk.Frame(tmp21)
 tmp24.pack(fill='x')
 tmp25=tk.Button(tmp24,text='Start Program',height=2)
 tmp25.pack(side='left',fill='x',expand=True)
 tmp26=tk.Button(tmp24,text='Stop Backend',height=2,state='disabled')
 tmp26.pack(side='left',fill='x',expand=True,padx=(10,0))
 tmp27=tk.StringVar(value='Enter your API key, then click Start Program.')
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
  if not key:
   messagebox.showerror('Missing API Key','Enter your OpenAI API key first.')
   return
  tmp22.delete(0,'end')
  tmp25.config(state='disabled')
  tmp26.config(state='disabled')
  tmp27.set('Preparing program...')
  threading.Thread(target=run,args=(key,),daemon=True).start()
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
     tmp27.set(text);addLog('ERROR: '+text);tmp25.config(state='normal');tmp26.config(state='disabled')
     messagebox.showerror('Could not start',text)
    elif kind=='stopped':
     tmp27.set(text);tmp25.config(state='normal');tmp26.config(state='disabled')
  except queue.Empty:
   pass
  tmp20.after(100,update)
 def close():
  if process is not None and process.poll()is None:
   if not messagebox.askyesno('Close Launcher','Closing the launcher will stop the backend. Continue?'):return
   stop2()
  tmp20.destroy()
 tmp25.config(command=start)
 tmp26.config(command=stop)
 tmp20.protocol('WM_DELETE_WINDOW',close)
 tmp22.focus_set()
 update()
 tmp20.mainloop()

if __name__=='__main__':main()
