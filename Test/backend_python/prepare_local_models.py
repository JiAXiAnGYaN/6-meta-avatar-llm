import argparse
import os
import time
from pathlib import Path
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
from huggingface_hub import snapshot_download

def getargs():
 a=argparse.ArgumentParser()
 a.add_argument('--dir',default=str(Path(__file__).resolve().parent/'local_models'))
 return a.parse_args()

def ok(path,names):
 return all((path/a).is_file()and(path/a).stat().st_size>0 for a in names)

def gethf(name,path,allow=None,need=None):
 path.mkdir(parents=True,exist_ok=True)
 print('Downloading '+name+'...')
 tmp=None
 for i in range(4):
  try:
   snapshot_download(repo_id=name,local_dir=str(path),allow_patterns=allow,max_workers=2)
   if not need or ok(path,need):return
   raise RuntimeError('Some model files are still missing.')
  except Exception as a:
   tmp=a
   if i<3:print('Connection stopped. Retrying '+str(i+2)+'/4...');time.sleep(2)
 raise tmp

def getcache(name,root,allow=None):
 print('Downloading '+name+'...')
 tmp=None
 for i in range(4):
  try:
   snapshot_download(repo_id=name,cache_dir=str(root/'.cache'/'hub'),allow_patterns=allow,max_workers=2)
   return
  except Exception as a:
   tmp=a
   if i<3:print('Connection stopped. Retrying '+str(i+2)+'/4...');time.sleep(2)
 raise tmp

def getcode(path):
 dst=path/'source'
 if (dst/'tsr'/'system.py').is_file():return
 print('Downloading TripoSR source code...')
 dst.mkdir(parents=True,exist_ok=True)
 tmp=None
 for i in range(4):
  try:
   snapshot_download(repo_id='stabilityai/TripoSR',repo_type='space',local_dir=str(dst),allow_patterns=['tsr/**'],max_workers=2)
   return
  except Exception as a:
   tmp=a
   if i<3:print('Connection stopped. Retrying '+str(i+2)+'/4...');time.sleep(2)
 raise tmp

def getrembg(path):
 print('Downloading the background-removal model...')
 path.mkdir(parents=True,exist_ok=True)
 os.environ['U2NET_HOME']=str(path)
 from rembg import new_session
 new_session('u2netp')

def main():
 a=getargs()
 root=Path(a.dir).expanduser().resolve()
 root.mkdir(parents=True,exist_ok=True)
 os.environ['HF_HOME']=str(root/'.cache')
 gethf('stabilityai/TripoSR',root/'TripoSR'/'model',need=['config.yaml','model.ckpt'])
 getcode(root/'TripoSR')
 tmp=['model_index.json','feature_extractor/*','scheduler/*','tokenizer/*','safety_checker/config.json','safety_checker/model.fp16.safetensors','text_encoder/config.json','text_encoder/model.fp16.safetensors','unet/config.json','unet/diffusion_pytorch_model.fp16.safetensors','vae/config.json','vae/diffusion_pytorch_model.fp16.safetensors']
 tmp2=['model_index.json','feature_extractor/preprocessor_config.json','scheduler/scheduler_config.json','tokenizer/merges.txt','tokenizer/vocab.json','safety_checker/config.json','safety_checker/model.fp16.safetensors','text_encoder/config.json','text_encoder/model.fp16.safetensors','unet/config.json','unet/diffusion_pytorch_model.fp16.safetensors','vae/config.json','vae/diffusion_pytorch_model.fp16.safetensors']
 gethf('stable-diffusion-v1-5/stable-diffusion-v1-5',root/'stable-diffusion-v1-5',tmp,tmp2)
 getcache('facebook/dino-vitb16',root,['config.json'])
 getrembg(root/'u2net')
 if not ok(root/'TripoSR'/'source',['tsr/system.py'])or not ok(root/'u2net',['u2netp.onnx'])or not ok(root/'stable-diffusion-v1-5',tmp2):raise RuntimeError('Some local model files are still missing. Run the download again.')
 (root/'ready.txt').write_text('TripoSR\nstable-diffusion-v1-5\nu2netp\n',encoding='utf-8')
 print('Local models are ready in '+str(root))

if __name__=='__main__':main()
