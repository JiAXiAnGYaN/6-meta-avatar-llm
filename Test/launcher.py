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

folder=Path(__file__).resolve().parent
backend=folder/'backend_python'
unityProject=folder/'frontend_unity'
process=None
events=queue.Queue()

def send(kind,text=''):
 events.put((kind,text))

def pythonPath():
 if os.name=='nt':return backend/'.venv'/'Scripts'/'python.exe'
 return backend/'.venv'/'bin'/'python'

def runSetup():
 py=pythonPath()
 if not py.is_file():
  send('status','Creating Python environment...')
  tmp=subprocess.run([sys.executable,'-m','venv',str(backend/'.venv')],cwd=backend,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if tmp.returncode!=0:raise RuntimeError(tmp.stdout.strip()or'Could not create the Python environment.')
 tmp=subprocess.run([str(py),'-c','import fastapi,uvicorn,gradio_client,mediapipe,certifi'],cwd=backend,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 if tmp.returncode!=0:
  send('status','Installing Python packages. This can take a few minutes...')
  tmp=subprocess.run([str(py),'-m','pip','install','-r',str(backend/'requirements.txt')],cwd=backend,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  if tmp.returncode!=0:raise RuntimeError(tmp.stdout.strip()or'Could not install the Python packages.')
 return py

def portIsFree():
 tmp=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
 try:
  tmp.bind(('127.0.0.1',8000))
  return True
 except OSError:
  return False
 finally:
  tmp.close()

def waitForBackend():
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

def unityPath():
 tmp=unityProject/'ProjectSettings'/'ProjectVersion.txt'
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

def readLog():
 if process is None or process.stdout is None:return
 for line in process.stdout:
  send('log',line.rstrip())

def startWork(key):
 global process
 try:
  if not portIsFree():raise RuntimeError('Port 8000 is already in use. Stop the old backend with Ctrl+C, then try again.')
  py=runSetup()
  send('status','Starting backend...')
  env=os.environ.copy()
  env['OPENAI_API_KEY']=key
  env.setdefault('META_AVATAR_OPENAI_IMAGE_TIMEOUT','300')
  env.setdefault('META_AVATAR_OPENAI_IMAGE_ATTEMPTS','2')
  process=subprocess.Popen([str(py),str(backend/'main.py')],cwd=backend,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=1)
  threading.Thread(target=readLog,daemon=True).start()
  waitForBackend()
  send('status','Backend is ready. Opening Unity...')
  subprocess.Popen([str(unityPath()),'-projectPath',str(unityProject)],cwd=unityProject,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  send('running','Program started. Keep this launcher open while using Unity.')
 except Exception as error:
  if process is not None and process.poll()is None:
   process.terminate()
  process=None
  send('error',str(error))

def stopBackend():
 global process
 if process is not None and process.poll()is None:
  process.terminate()
  try:process.wait(timeout=5)
  except subprocess.TimeoutExpired:process.kill()
 process=None
 send('stopped','Backend stopped.')

def main():
 window=tk.Tk()
 window.title('Meta Avatar Launcher')
 window.geometry('680x470')
 window.minsize(560,380)
 frame=tk.Frame(window,padx=18,pady=16)
 frame.pack(fill='both',expand=True)
 tk.Label(frame,text='OpenAI API Key',anchor='w',font=('Arial',14)).pack(fill='x')
 keyEntry=tk.Entry(frame,show='*',font=('Arial',13))
 keyEntry.pack(fill='x',pady=(7,5),ipady=6)
 showKey=tk.BooleanVar(value=False)
 tk.Checkbutton(frame,text='Show API Key',variable=showKey,command=lambda:keyEntry.config(show=''if showKey.get()else'*')).pack(anchor='w')
 tk.Label(frame,text='The key is used only by the backend process and is not saved.',anchor='w').pack(fill='x',pady=(2,12))
 buttons=tk.Frame(frame)
 buttons.pack(fill='x')
 startButton=tk.Button(buttons,text='Start Program',height=2)
 startButton.pack(side='left',fill='x',expand=True)
 stopButton=tk.Button(buttons,text='Stop Backend',height=2,state='disabled')
 stopButton.pack(side='left',fill='x',expand=True,padx=(10,0))
 status=tk.StringVar(value='Enter your API key, then click Start Program.')
 tk.Label(frame,textvariable=status,anchor='w',justify='left',wraplength=640).pack(fill='x',pady=(14,8))
 log=tk.Text(frame,height=13,state='disabled',wrap='word')
 log.pack(fill='both',expand=True)
 def addLog(text):
  log.config(state='normal')
  log.insert('end',text+'\n')
  log.see('end')
  log.config(state='disabled')
 def start():
  key=keyEntry.get().strip()
  if not key:
   messagebox.showerror('Missing API Key','Enter your OpenAI API key first.')
   return
  keyEntry.delete(0,'end')
  startButton.config(state='disabled')
  stopButton.config(state='disabled')
  status.set('Preparing program...')
  threading.Thread(target=startWork,args=(key,),daemon=True).start()
 def stop():
  stopButton.config(state='disabled')
  threading.Thread(target=stopBackend,daemon=True).start()
 def update():
  try:
   while True:
    kind,text=events.get_nowait()
    if kind=='log':addLog(text)
    elif kind=='status':status.set(text)
    elif kind=='running':
     status.set(text);stopButton.config(state='normal')
    elif kind=='error':
     status.set(text);addLog('ERROR: '+text);startButton.config(state='normal');stopButton.config(state='disabled')
     messagebox.showerror('Could not start',text)
    elif kind=='stopped':
     status.set(text);startButton.config(state='normal');stopButton.config(state='disabled')
  except queue.Empty:
   pass
  window.after(100,update)
 def close():
  if process is not None and process.poll()is None:
   if not messagebox.askyesno('Close Launcher','Closing the launcher will stop the backend. Continue?'):return
   stopBackend()
  window.destroy()
 startButton.config(command=start)
 stopButton.config(command=stop)
 window.protocol('WM_DELETE_WINDOW',close)
 keyEntry.focus_set()
 update()
 window.mainloop()

if __name__=='__main__':main()
