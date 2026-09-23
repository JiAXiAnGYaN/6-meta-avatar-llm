import argparse
import gc
import hashlib
import inspect
import os
import re
import subprocess
import sys
import threading
import types
from pathlib import Path

tmp1=Path(__file__).resolve()
tmp2=threading.Lock()

class LocalWorkerError(RuntimeError):
 pass

def _call(tmp3:list[str])->None:
 tmp4=int(os.getenv('META_AVATAR_LOCAL_TIMEOUT','7200'))
 with tmp2:
  try:tmp5=subprocess.run([sys.executable,str(tmp1),*tmp3],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=tmp4)
  except subprocess.TimeoutExpired as tmp6:raise LocalWorkerError('Local AI generation timed out.')from tmp6
 if tmp5.returncode!=0:
  tmp6=(tmp5.stderr or tmp5.stdout).strip().splitlines()
  raise LocalWorkerError(tmp6[-1]if tmp6 else'Local AI worker failed.')

def make_image(tmp3:str,tmp4:Path,tmp5:str,tmp6:str)->None:
 _call(['image','--prompt',tmp3,'--output',str(tmp4),'--model',tmp5,'--device',tmp6])

def make_photo(tmp3:str,tmp4:Path,tmp5:Path,tmp6:str,tmp7:str)->None:
 _call(['photo','--prompt',tmp3,'--input',str(tmp4),'--output',str(tmp5),'--model',tmp6,'--device',tmp7])

def make_3d(tmp3:Path,tmp4:Path,tmp5:Path,tmp6:int,tmp7:float,tmp8:str,tmp9:Path|None=None)->None:
 tmp10=['3d','--image',str(tmp3),'--output',str(tmp4),'--root',str(tmp5),'--resolution',str(tmp6),'--ratio',str(tmp7),'--device',tmp8]
 if tmp9 is not None:tmp10+=['--processed',str(tmp9)]
 _call(tmp10)

def _off()->bool:
 return os.getenv('HF_HUB_OFFLINE','').strip().lower()in{'1','true','yes','on'}

def _root(tmp3:str)->Path:
 tmp4=Path(tmp3).expanduser()
 if not tmp4.is_absolute():
  tmp5=tmp1.parent.parent/tmp4 if tmp4.parts and tmp4.parts[0]=='backend_python'else tmp1.parent/tmp4
  tmp4=tmp5
 return tmp4.resolve()

def _env(tmp3:Path)->None:
 tmp4=tmp3.parent/'.cache'
 tmp4.mkdir(parents=True,exist_ok=True)
 os.environ['HF_HOME']=str(tmp4)
 os.environ['HF_HUB_CACHE']=str(tmp4/'hub')
 os.environ['U2NET_HOME']=str(tmp3.parent/'u2net')
 os.environ.setdefault('HF_HUB_DISABLE_XET','1')

def _snap(tmp3:str,tmp4:Path,tmp5:str='model',tmp6:list[str]|None=None)->None:
 if _off():raise LocalWorkerError('Local model files are missing. Turn off offline mode and run once with internet access.')
 try:
  from huggingface_hub import snapshot_download
  tmp4.mkdir(parents=True,exist_ok=True)
  tmp7={'repo_id':tmp3,'local_dir':str(tmp4)}
  if tmp5!='model':tmp7['repo_type']=tmp5
  if tmp6:tmp7['allow_patterns']=tmp6
  snapshot_download(**tmp7)
 except Exception as tmp8:raise LocalWorkerError('Local model download failed. Check the internet connection and free disk space.')from tmp8

def _mc()->None:
 import numpy as tmp3
 import torch as tmp4
 from skimage.measure import marching_cubes as tmp5
 def run(tmp6,tmp7):
  tmp8=tmp6.detach().float().cpu().numpy()
  try:tmp9,tmp10,_,_=tmp5(tmp8,level=float(tmp7),allow_degenerate=False)
  except Exception as tmp11:raise RuntimeError('The local 3D model did not create a usable surface.')from tmp11
  tmp9=tmp3.ascontiguousarray(tmp9,dtype=tmp3.float32)
  tmp10=tmp3.ascontiguousarray(tmp10,dtype=tmp3.int64)
  return tmp4.from_numpy(tmp9).to(tmp6.device),tmp4.from_numpy(tmp10).to(tmp6.device)
 tmp6=types.ModuleType('torchmcubes')
 tmp6.marching_cubes=run
 sys.modules['torchmcubes']=tmp6

def _device(tmp3:str):
 import torch
 tmp4=tmp3.strip().lower()
 if tmp4=='auto':
  if torch.cuda.is_available():tmp4='cuda'
  elif hasattr(torch.backends,'mps')and torch.backends.mps.is_available():tmp4='mps'
  else:tmp4='cpu'
 if tmp4.startswith('cuda')and not torch.cuda.is_available():raise LocalWorkerError('CUDA was selected but is not available.')
 if tmp4=='mps'and(not hasattr(torch.backends,'mps')or not torch.backends.mps.is_available()):raise LocalWorkerError('Apple Metal was selected but is not available.')
 if tmp4!='cpu'and tmp4!='mps'and not tmp4.startswith('cuda'):raise LocalWorkerError('Local device must be cpu, mps, cuda, or auto.')
 return tmp4

def _image_path(tmp3:str,tmp4:Path)->Path:
 tmp5=Path(tmp3).expanduser()
 if tmp5.is_dir():return tmp5.resolve()
 if tmp5.is_absolute()or tmp3.startswith('.'):
  raise LocalWorkerError('The configured local image model folder does not exist.')
 tmp6=re.sub('[^a-zA-Z0-9._-]+','-',tmp3.rsplit('/',1)[-1]).strip('-')or'image-model'
 tmp7=tmp4.parent/tmp6
 if not(tmp7/'model_index.json').is_file():
  tmp8=['model_index.json','feature_extractor/**','scheduler/**','tokenizer/**','*/config.json','unet/*fp16.safetensors','vae/*fp16.safetensors','text_encoder/*fp16.safetensors','safety_checker/*fp16.safetensors']
  _snap(tmp3,tmp7,tmp6=tmp8)
 return tmp7

def _safe(tmp3,tmp4:Path,tmp5:Path)->None:
 import numpy as tmp6
 import torch
 from diffusers.pipelines.stable_diffusion.safety_checker import StableDiffusionSafetyChecker
 from transformers import CLIPImageProcessor
 tmp7=StableDiffusionSafetyChecker.from_pretrained(str(tmp4/'safety_checker'),dtype=torch.float32,local_files_only=True,variant='fp16')
 tmp8=CLIPImageProcessor.from_pretrained(str(tmp4/'feature_extractor'),local_files_only=True)
 tmp9=tmp8(images=[tmp3],return_tensors='pt')
 tmp10=tmp6.expand_dims(tmp6.asarray(tmp3).astype(tmp6.float32)/255,0)
 with torch.inference_mode():_,tmp11=tmp7(images=tmp10,clip_input=tmp9.pixel_values.float())
 if tmp11[0]:raise LocalWorkerError('The local image model blocked this result.')
 tmp5.parent.mkdir(parents=True,exist_ok=True);tmp3.save(tmp5,format='PNG')

def _image(tmp3)->None:
 tmp4=_root(os.getenv('META_AVATAR_TRIPOSR_PATH',str(tmp1.parent/'local_models'/'TripoSR')))
 _env(tmp4)
 tmp5=_image_path(tmp3.model,tmp4)
 try:
  import torch
  from diffusers import StableDiffusionPipeline
  tmp6=_device(tmp3.device)
  tmp7=torch.float16 if tmp6!='cpu'else torch.float32
  tmp14={'torch_dtype':tmp7,'local_files_only':True,'safety_checker':None,'requires_safety_checker':False}
  if(tmp5/'unet'/'diffusion_pytorch_model.fp16.safetensors').is_file():tmp14.update({'variant':'fp16','use_safetensors':True})
  tmp8=StableDiffusionPipeline.from_pretrained(str(tmp5),**tmp14)
  tmp8.enable_attention_slicing()
  if hasattr(tmp8,'vae')and hasattr(tmp8.vae,'enable_slicing'):tmp8.vae.enable_slicing()
  tmp8=tmp8.to(tmp6)
  tmp9=int(hashlib.sha256((tmp3.prompt+str(os.getpid())).encode('utf-8')).hexdigest()[:8],16)
  tmp10=torch.Generator(device='cpu').manual_seed(tmp9)
  tmp11='photo, realistic photo, cropped body, close-up, side view, back view, two people, duplicate person, group, crowd, extra person, extra arms, extra legs, raised arm, raised hand, waving, hand gesture, action pose, crossed limbs, sitting, object, text, watermark, blurry face'
  tmp15=os.getenv('META_AVATAR_LOCAL_IMAGE_SIZE','512x768').lower().split('x')
  try:tmp16,tmp17=int(tmp15[0]),int(tmp15[1])
  except Exception as tmp18:raise LocalWorkerError('Local image size must look like 512x768.')from tmp18
  if tmp16<256 or tmp17<256 or tmp16>1024 or tmp17>1024 or tmp16%8 or tmp17%8:raise LocalWorkerError('Local image size must use multiples of 8 from 256 to 1024.')
  with torch.inference_mode():tmp12=tmp8(tmp3.prompt,negative_prompt=tmp11,width=tmp16,height=tmp17,num_inference_steps=int(os.getenv('META_AVATAR_LOCAL_IMAGE_STEPS','20')),guidance_scale=7.5,generator=tmp10)
  tmp13=tmp12.images[0]
  del tmp8,tmp12
  if tmp6=='mps'and hasattr(torch,'mps'):torch.mps.empty_cache()
  gc.collect()
  _safe(tmp13,tmp5,Path(tmp3.output))
 except LocalWorkerError:raise
 except Exception as tmp14:
  tmp15=str(tmp14).lower()
  if'out of memory'in tmp15 or'cannot allocate memory'in tmp15:raise LocalWorkerError('The local image model ran out of memory. Close other programs and try again.')from tmp14
  raise LocalWorkerError('Local cartoon generation failed: '+str(tmp14))from tmp14
 finally:
  gc.collect()

def _photo(tmp3)->None:
 tmp4=_root(os.getenv('META_AVATAR_TRIPOSR_PATH',str(tmp1.parent/'local_models'/'TripoSR')))
 _env(tmp4)
 tmp5=_image_path(tmp3.model,tmp4)
 try:
  import rembg
  import torch
  from diffusers import StableDiffusionImg2ImgPipeline
  from PIL import Image,ImageOps
  tmp6=_device(tmp3.device)
  tmp7=torch.float16 if tmp6!='cpu'else torch.float32
  tmp8={'torch_dtype':tmp7,'local_files_only':True,'safety_checker':None,'requires_safety_checker':False}
  if(tmp5/'unet'/'diffusion_pytorch_model.fp16.safetensors').is_file():tmp8.update({'variant':'fp16','use_safetensors':True})
  tmp9=StableDiffusionImg2ImgPipeline.from_pretrained(str(tmp5),**tmp8)
  tmp9.enable_attention_slicing()
  if hasattr(tmp9,'vae')and hasattr(tmp9.vae,'enable_slicing'):tmp9.vae.enable_slicing()
  tmp9=tmp9.to(tmp6)
  tmp10=Image.open(tmp3.input).convert('RGB')
  try:tmp11=rembg.new_session('u2netp');tmp10=rembg.remove(tmp10,session=tmp11).convert('RGBA')
  except Exception as tmp12:
   if _off():raise LocalWorkerError('The local background removal model is missing.')from tmp12
   raise LocalWorkerError('The background removal model could not be downloaded.')from tmp12
  tmp13=os.getenv('META_AVATAR_LOCAL_IMAGE_SIZE','512x768').lower().split('x')
  try:tmp14,tmp15=int(tmp13[0]),int(tmp13[1])
  except Exception as tmp16:raise LocalWorkerError('Local image size must look like 512x768.')from tmp16
  if tmp14<256 or tmp15<256 or tmp14>1024 or tmp15>1024 or tmp14%8 or tmp15%8:raise LocalWorkerError('Local image size must use multiples of 8 from 256 to 1024.')
  tmp10=ImageOps.contain(tmp10,(tmp14,tmp15),Image.Resampling.LANCZOS)
  tmp17=Image.new('RGBA',(tmp14,tmp15),(190,190,190,255));tmp17.paste(tmp10,((tmp14-tmp10.width)//2,(tmp15-tmp10.height)//2),tmp10);tmp17=tmp17.convert('RGB')
  tmp18=float(os.getenv('META_AVATAR_LOCAL_PHOTO_STRENGTH','0.42'))
  if tmp18<0.2 or tmp18>0.75:raise LocalWorkerError('Local photo strength must be from 0.2 to 0.75.')
  tmp19=int(hashlib.sha256(tmp3.prompt.encode('utf-8')+Path(tmp3.input).read_bytes()+str(os.getpid()).encode('utf-8')).hexdigest()[:8],16)
  tmp20=torch.Generator(device='cpu').manual_seed(tmp19)
  tmp21='photo, realistic photo, cropped body, close-up, side view, back view, two people, duplicate person, group, crowd, extra person, extra arms, extra legs, raised arm, raised hand, waving, hand gesture, action pose, crossed limbs, sitting, object, text, watermark, blurry face'
  with torch.inference_mode():tmp22=tmp9(prompt=tmp3.prompt,negative_prompt=tmp21,image=tmp17,strength=tmp18,num_inference_steps=int(os.getenv('META_AVATAR_LOCAL_IMAGE_STEPS','20')),guidance_scale=7.5,generator=tmp20)
  tmp23=tmp22.images[0]
  del tmp9,tmp22
  if tmp6=='mps'and hasattr(torch,'mps'):torch.mps.empty_cache()
  gc.collect();_safe(tmp23,tmp5,Path(tmp3.output))
 except LocalWorkerError:raise
 except Exception as tmp24:
  tmp25=str(tmp24).lower()
  if'out of memory'in tmp25 or'cannot allocate memory'in tmp25:raise LocalWorkerError('Local photo cartoon generation ran out of memory. Close other programs and try again.')from tmp24
  raise LocalWorkerError('Local photo cartoon generation failed: '+str(tmp24))from tmp24
 finally:
  gc.collect()

def _tripo_files(tmp3:Path)->tuple[Path,Path]:
 tmp4=tmp3/'source';tmp5=tmp3/'model'
 if not(tmp4/'tsr'/'system.py').is_file():_snap('stabilityai/TripoSR',tmp4,'space',['tsr/**'])
 if not(tmp5/'config.yaml').is_file()or not(tmp5/'model.ckpt').is_file():_snap('stabilityai/TripoSR',tmp5)
 try:
  from huggingface_hub import snapshot_download
  if _off():snapshot_download('facebook/dino-vitb16',allow_patterns=['config.json'],local_files_only=True)
  else:snapshot_download('facebook/dino-vitb16',allow_patterns=['config.json'])
 except Exception as tmp6:
  if _off():raise LocalWorkerError('The local DINO files are missing. Turn off offline mode and run once with internet access.')from tmp6
  raise LocalWorkerError('The DINO model download failed.')from tmp6
 return tmp4,tmp5

def _fill(tmp3):
 import numpy as tmp4
 from PIL import Image
 tmp5=tmp4.array(tmp3).astype(tmp4.float32)/255
 tmp5=tmp5[:,:,:3]*tmp5[:,:,3:4]+(1-tmp5[:,:,3:4])*.5
 return Image.fromarray((tmp5*255).astype(tmp4.uint8))

def _three(tmp3)->None:
 tmp4=_root(tmp3.root);_env(tmp4)
 tmp5,tmp6=_tripo_files(tmp4)
 sys.path.insert(0,str(tmp5));_mc()
 try:
  import rembg
  import torch
  from PIL import Image
  from tsr.system import TSR
  from tsr.utils import remove_background,resize_foreground,to_gradio_3d_orientation
  tmp7=_device(tmp3.device)
  if tmp7=='cpu':torch.set_num_threads(max(1,min(4,os.cpu_count()or 1)))
  tmp8=Image.open(tmp3.image).convert('RGB')
  try:tmp9=rembg.new_session('u2netp')
  except Exception as tmp10:
   if _off():raise LocalWorkerError('The local background removal model is missing. Turn off offline mode and run once with internet access.')from tmp10
   raise LocalWorkerError('The background removal model could not be downloaded.')from tmp10
  tmp8=remove_background(tmp8,tmp9)
  tmp8=resize_foreground(tmp8,float(tmp3.ratio))
  tmp8=_fill(tmp8)
  if tmp3.processed:
   tmp15=Path(tmp3.processed);tmp15.parent.mkdir(parents=True,exist_ok=True);tmp8.save(tmp15,format='PNG')
  tmp10=TSR.from_pretrained(str(tmp6),config_name='config.yaml',weight_name='model.ckpt')
  tmp10.renderer.set_chunk_size(int(os.getenv('META_AVATAR_LOCAL_CHUNK_SIZE','4096')))
  tmp10.to(tmp7)
  with torch.inference_mode():tmp11=tmp10([tmp8],device=tmp7)
  if'has_vertex_color'in inspect.signature(tmp10.extract_mesh).parameters:tmp12=tmp10.extract_mesh(tmp11,True,resolution=int(tmp3.resolution))[0]
  else:tmp12=tmp10.extract_mesh(tmp11,resolution=int(tmp3.resolution))[0]
  tmp12=to_gradio_3d_orientation(tmp12)
  try:tmp12.fix_normals()
  except Exception:pass
  tmp13=Path(tmp3.output);tmp13.parent.mkdir(parents=True,exist_ok=True);tmp12.export(tmp13)
  if not tmp13.is_file()or tmp13.stat().st_size==0:raise LocalWorkerError('The local 3D model returned an empty GLB file.')
 except LocalWorkerError:raise
 except Exception as tmp14:
  tmp15=str(tmp14).lower()
  if'out of memory'in tmp15 or'cannot allocate memory'in tmp15:raise LocalWorkerError('Local TripoSR ran out of memory. Close other programs and try again.')from tmp14
  raise LocalWorkerError('Local TripoSR failed: '+str(tmp14))from tmp14
 finally:
  gc.collect()

def main()->None:
 tmp3=argparse.ArgumentParser()
 tmp4=tmp3.add_subparsers(dest='mode',required=True)
 tmp5=tmp4.add_parser('image');tmp5.add_argument('--prompt',required=True);tmp5.add_argument('--output',required=True);tmp5.add_argument('--model',required=True);tmp5.add_argument('--device',required=True)
 tmp6=tmp4.add_parser('photo');tmp6.add_argument('--prompt',required=True);tmp6.add_argument('--input',required=True);tmp6.add_argument('--output',required=True);tmp6.add_argument('--model',required=True);tmp6.add_argument('--device',required=True)
 tmp9=tmp4.add_parser('3d');tmp9.add_argument('--image',required=True);tmp9.add_argument('--output',required=True);tmp9.add_argument('--root',required=True);tmp9.add_argument('--resolution',type=int,required=True);tmp9.add_argument('--ratio',type=float,required=True);tmp9.add_argument('--device',required=True);tmp9.add_argument('--processed')
 tmp7=tmp3.parse_args()
 try:
  if tmp7.mode=='image':_image(tmp7)
  elif tmp7.mode=='photo':_photo(tmp7)
  else:_three(tmp7)
 except Exception as tmp8:
  print(str(tmp8),file=sys.stderr)
  raise SystemExit(1)

if __name__=='__main__':main()
