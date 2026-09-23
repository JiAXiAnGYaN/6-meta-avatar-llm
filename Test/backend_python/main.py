import base64
import hashlib
import io
import json
import logging
import os
import re
import ssl
import struct
import threading
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any ,Literal
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4
import certifi
import uvicorn
from fastapi import FastAPI ,File ,Form ,HTTPException ,Query ,Request ,Response ,UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from local_worker import LocalWorkerError,make_3d,make_image,make_photo
from pydantic import BaseModel
logging.basicConfig (level =os.getenv ('META_AVATAR_LOG_LEVEL','INFO').upper (),format ='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger =logging.getLogger ('meta_avatar')
BASE_DIR =Path (__file__ ).resolve ().parent
MODEL_DIR =Path (os.getenv ('META_AVATAR_OUTPUT_DIR',str (BASE_DIR /'hf_generated_models'))).expanduser ()
MODEL_DIR.mkdir (parents =True ,exist_ok =True )
PUBLIC_BASE_URL =os.getenv ('META_AVATAR_PUBLIC_BASE_URL','').rstrip ('/')
HUGGING_FACE_SPACE ='stabilityai/TripoSR local'
THREE_D_MODE =os.getenv ('META_AVATAR_3D_MODE','local').strip ().lower ()
TRIPOSR_PATH =Path (os.getenv ('META_AVATAR_TRIPOSR_PATH',str (BASE_DIR /'local_models'/'TripoSR'))).expanduser ()
LOCAL_3D_DEVICE =os.getenv ('META_AVATAR_LOCAL_3D_DEVICE','cpu')
LOCAL_IMAGE_DEVICE =os.getenv ('META_AVATAR_LOCAL_IMAGE_DEVICE','auto')
LOCAL_IMAGE_MODEL =os.getenv ('META_AVATAR_LOCAL_IMAGE_MODEL',str (BASE_DIR /'local_models'/'stable-diffusion-v1-5'))
PIPELINE_VERSION ='ai-cartoon-local-v6'
FOREGROUND_RATIO =float (os.getenv ('META_AVATAR_FOREGROUND_RATIO','0.9'))
if not 0.5 <=FOREGROUND_RATIO <=1.0 :
    raise ValueError ('META_AVATAR_FOREGROUND_RATIO must be between 0.5 and 1.0.')
OPENAI_IMAGE_API_URL =os.getenv ('META_AVATAR_OPENAI_IMAGE_API_URL','https://api.openai.com/v1/images/generations')
OPENAI_IMAGE_MODEL =os.getenv ('META_AVATAR_OPENAI_IMAGE_MODEL','gpt-image-2')
OPENAI_IMAGE_SIZE =os.getenv ('META_AVATAR_OPENAI_IMAGE_SIZE','1024x1536')
OPENAI_IMAGE_QUALITY =os.getenv ('META_AVATAR_OPENAI_IMAGE_QUALITY','medium')
OPENAI_IMAGE_TIMEOUT_SECONDS =int (os.getenv ('META_AVATAR_OPENAI_IMAGE_TIMEOUT','300'))
OPENAI_IMAGE_ATTEMPTS =int (os.getenv ('META_AVATAR_OPENAI_IMAGE_ATTEMPTS','2'))
LOCAL_IMAGE_ATTEMPTS =int (os.getenv ('META_AVATAR_LOCAL_IMAGE_ATTEMPTS','4'))
OPENAI_IMAGE_RESPONSE_LIMIT_BYTES =int (os.getenv ('META_AVATAR_OPENAI_IMAGE_RESPONSE_LIMIT_MB','30'))*1024 *1024
LOCAL_IMAGE_LIMIT_BYTES =int (os.getenv ('META_AVATAR_LOCAL_IMAGE_LIMIT_MB','15'))*1024 *1024
OLLAMA_IMAGE_API_URL =os.getenv ('META_AVATAR_OLLAMA_IMAGE_API_URL','http://127.0.0.1:11434/api/generate')
OLLAMA_IMAGE_MODEL =os.getenv ('META_AVATAR_OLLAMA_IMAGE_MODEL','x/flux2-klein:4b')
OLLAMA_IMAGE_SIZE =os.getenv ('META_AVATAR_OLLAMA_IMAGE_SIZE','768x1024')
OLLAMA_IMAGE_TIMEOUT_SECONDS =int (os.getenv ('META_AVATAR_OLLAMA_IMAGE_TIMEOUT','900'))
BATCH_LIMIT =int (os.getenv ('META_AVATAR_BATCH_LIMIT','20'))
BUNDESTAG_URL =os.getenv ('META_AVATAR_BUNDESTAG_URL','https://www.bundestag.de/resource/blob/472878/MdB-Stammdaten.zip')
BUNDESTAG_PERIOD =int (os.getenv ('META_AVATAR_BUNDESTAG_PERIOD','21'))
BUNDESTAG_LIMIT_BYTES =int (os.getenv ('META_AVATAR_BUNDESTAG_LIMIT_MB','30'))*1024 *1024
if OPENAI_IMAGE_TIMEOUT_SECONDS <30 :
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_TIMEOUT must be at least 30.')
if OPENAI_IMAGE_ATTEMPTS <1 or LOCAL_IMAGE_ATTEMPTS <1 :
    raise ValueError ('Image attempts must be positive.')
if OPENAI_IMAGE_RESPONSE_LIMIT_BYTES <1024 *1024 :
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_RESPONSE_LIMIT_MB must be at least 1.')
if LOCAL_IMAGE_LIMIT_BYTES <1024 *1024 :
    raise ValueError ('META_AVATAR_LOCAL_IMAGE_LIMIT_MB must be at least 1.')
if OPENAI_IMAGE_QUALITY not in {'low','medium','high','auto'}:
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_QUALITY must be low, medium, high, or auto.')
if not re.fullmatch ('\\d+x\\d+|auto',OPENAI_IMAGE_SIZE ):
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_SIZE must be WIDTHxHEIGHT or auto.')
if not re.fullmatch ('\\d+x\\d+',OLLAMA_IMAGE_SIZE ):
    raise ValueError ('META_AVATAR_OLLAMA_IMAGE_SIZE must be WIDTHxHEIGHT.')
if OLLAMA_IMAGE_TIMEOUT_SECONDS <30 or BATCH_LIMIT <1 or BATCH_LIMIT >100 :
    raise ValueError ('Ollama timeout or batch limit is invalid.')
if THREE_D_MODE !='local':
    raise ValueError ('META_AVATAR_3D_MODE must be local.')
POSE_MODEL_PATH =Path (os.getenv ('META_AVATAR_POSE_MODEL',str (BASE_DIR /'models'/'pose_landmarker_lite.task'))).expanduser ()
MARCHING_CUBES_RESOLUTION =int (os.getenv ('META_AVATAR_MC_RESOLUTION','128'))
if MARCHING_CUBES_RESOLUTION <32 or MARCHING_CUBES_RESOLUTION >320 or MARCHING_CUBES_RESOLUTION %32 !=0 :
    raise ValueError ('META_AVATAR_MC_RESOLUTION must be a multiple of 32 between 32 and 320.')
_GENERATION_LOCKS :dict [str ,threading.Lock ]={}
_GENERATION_LOCKS_LOCK =threading.Lock ()
_POSE_VALIDATION_LOCK =threading.Lock ()
_POSE_LANDMARKER :Any |None =None
_MDB_LOCK =threading.Lock ()
_MDB_NAMES :list [str ]=[]
_MDB_TIME =0.0
_SSL_CONTEXT =ssl.create_default_context (cafile =certifi.where ())
tmpduui =BASE_DIR /'duui'
tmpxml =(tmpduui /'typesystem.xml').read_text (encoding ='utf-8')
tmplua =(tmpduui /'communication.lua').read_text (encoding ='utf-8')
app =FastAPI (title ='Meta-Avatar AI Cartoon-to-3D API',version ='2.5.0',description ='Makes cartoon images and GLB avatars with local AI, GPT Image, Ollama, or an uploaded full-body image.')
app.mount ('/models',StaticFiles (directory =str (MODEL_DIR )),name ='models')

class AvatarResponse (BaseModel ):
    name :str
    status :Literal ['success','error']
    message :str
    model_url :str =''
    reference_image_url :str =''
    cached :bool =False
    provider :str =''
    image_model :str =''

class CompareResponse (BaseModel ):
    name :str
    status :str
    message :str
    openai :AvatarResponse
    ollama :AvatarResponse

class BatchInput (BaseModel ):
    names :list [str ]=[]
    provider :str ='local'
    force :bool =False

class BatchResponse (BaseModel ):
    status :str
    message :str
    total :int
    success :int
    failed :int
    results :list [AvatarResponse ]=[]

class GermanMembersResponse (BaseModel ):
    period :int
    total :int
    start :int
    names :list [str ]=[]

class HealthResponse (BaseModel ):
    status :Literal ['ok']
    service :str

class TmpInput(BaseModel):
    text:str=''
    name:str=''
    force:bool=False
    include_binary:bool=False

class TmpOutput(BaseModel):
    name:str
    status:str
    message:str
    model_url:str=''
    reference_image_url:str=''
    model_data:str=''
    reference_image_data:str=''
    cached:bool=False

class AvatarGenerationError (RuntimeError ):
    pass

class AvatarImageGenerationError (RuntimeError ):
    pass

class AvatarImageConfigurationError (AvatarImageGenerationError ):
    pass

def normalize_name (name :str )->str :
    return ' '.join (name.split ())

def is_plausible_person_name (name :str )->bool :
    shuju2 ={' ','-',"'",'’','.'}
    return any ((linshi1.isalpha ()for linshi1 in name ))and all ((linshi1.isalpha ()or unicodedata.category (linshi1 ).startswith ('M')or linshi1 in shuju2 for linshi1 in name ))

def model_filename (name :str ,provider :str ='openai')->str :
    jieguo6 =normalize_name (name )
    a3 =unicodedata.normalize ('NFKD',jieguo6 ).encode ('ascii','ignore').decode ('ascii')
    tmp7 =re.sub ('[^a-zA-Z0-9]+','-',a3 ).strip ('-').lower ()
    tmp7 =tmp7 [:48 ]or 'avatar'
    if provider =='ollama':
        b4 =':'.join ((PIPELINE_VERSION ,'ollama',OLLAMA_IMAGE_MODEL ,OLLAMA_IMAGE_SIZE ,jieguo6.casefold ()))
    elif provider =='local':
        b4 =':'.join ((PIPELINE_VERSION ,'local',LOCAL_IMAGE_MODEL ,str (MARCHING_CUBES_RESOLUTION ),jieguo6.casefold ()))
    else :
        b4 =':'.join ((PIPELINE_VERSION ,OPENAI_IMAGE_MODEL ,OPENAI_IMAGE_SIZE ,OPENAI_IMAGE_QUALITY ,jieguo6.casefold ()))
    b4 +=':local3d:'+str (MARCHING_CUBES_RESOLUTION )
    dongxi5 =hashlib.sha256 (b4.encode ('utf-8')).hexdigest ()[:10 ]
    tmp8 ='-ollama'if provider =='ollama'else ('-local-ai'if provider =='local'else '')
    return f'{tmp7}-{PIPELINE_VERSION}{tmp8}-{dongxi5}.glb'

def reference_image_filename (model_name :str )->str :
    if Path (model_name ).name !=model_name or not model_name.endswith ('.glb'):
        raise ValueError ('model_name must be a plain .glb filename')
    return f'{Path(model_name).stem}.reference.png'

def local_model_filename (name :str ,tmp1 :bytes )->str :
    tmp2 =normalize_name (name )
    tmp3 =unicodedata.normalize ('NFKD',tmp2 ).encode ('ascii','ignore').decode ('ascii')
    tmp4 =re.sub ('[^a-zA-Z0-9]+','-',tmp3 ).strip ('-').lower ()[:48 ]or 'avatar'
    tmp5 =hashlib.sha256 ((PIPELINE_VERSION +':upload-cartoon:'+LOCAL_IMAGE_MODEL +':'+os.getenv ('META_AVATAR_LOCAL_PHOTO_STRENGTH','0.42')+':'+os.getenv ('META_AVATAR_LOCAL_IMAGE_STEPS','20')+':'+str (MARCHING_CUBES_RESOLUTION )+':'+tmp2.casefold ()+':').encode ('utf-8')+tmp1 ).hexdigest ()[:10 ]
    return f'{tmp4}-{PIPELINE_VERSION}-upload-{tmp5}.glb'

def _generation_lock (filename :str )->threading.Lock :
    with _GENERATION_LOCKS_LOCK :
        if filename not in _GENERATION_LOCKS:_GENERATION_LOCKS [filename]=threading.Lock ()
        return _GENERATION_LOCKS [filename]

def _get_pose_landmarker ()->Any :
    global _POSE_LANDMARKER
    if _POSE_LANDMARKER is not None :
        return _POSE_LANDMARKER
    if not POSE_MODEL_PATH.is_file ():
        raise AvatarGenerationError (f'Pose validation model is missing: {POSE_MODEL_PATH}')
    shuju9 =BASE_DIR /'.matplotlib-cache'
    shuju9.mkdir (parents =True ,exist_ok =True )
    os.environ.setdefault ('MPLCONFIGDIR',str (shuju9 ))
    import mediapipe as a10
    b11 =a10.tasks.vision.PoseLandmarkerOptions (base_options =a10.tasks.BaseOptions (model_asset_path =str (POSE_MODEL_PATH ),delegate =a10.tasks.BaseOptions.Delegate.CPU ),running_mode =a10.tasks.vision.RunningMode.IMAGE ,num_poses =2 ,min_pose_detection_confidence =0.55 ,min_pose_presence_confidence =0.55 )
    _POSE_LANDMARKER =a10.tasks.vision.PoseLandmarker.create_from_options (b11 )
    return _POSE_LANDMARKER

def _landmark_is_visible (landmark :Any ,threshold :float =0.55 )->bool :
    return float (getattr (landmark ,'visibility',0.0 ))>=threshold and float (getattr (landmark ,'presence',0.0 ))>=threshold and (-0.02 <=float (landmark.x )<=1.02 )and (-0.02 <=float (landmark.y )<=1.02 )

def pose_is_front_full_body (landmarks :Any ,cartoon :bool =False )->bool :
    if not isinstance (landmarks ,(list ,tuple ))or len (landmarks )<33 :
        return False
    b25 =landmarks [0 ]
    b18 =landmarks [2 ]
    linshi29 =landmarks [5 ]
    linshi22 =landmarks [11 ]
    dongxi33 =landmarks [12 ]
    a17 =landmarks [13 ]
    tmp28 =landmarks [14 ]
    shuju23 =landmarks [15 ]
    jieguo34 =landmarks [16 ]
    jieguo20 =landmarks [23 ]
    a31 =landmarks [24 ]
    tmp21 =landmarks [25 ]
    b32 =landmarks [26 ]
    shuju16 =landmarks [27 ]
    jieguo27 =landmarks [28 ]
    dongxi19 =landmarks [31 ]
    shuju30 =landmarks [32 ]
    dongxi26 =(b25 ,b18 ,linshi29 ,linshi22 ,dongxi33 ,a17 ,tmp28 ,shuju23 ,jieguo34 ,jieguo20 ,a31 ,tmp21 ,b32 ,shuju16 ,jieguo27 ,dongxi19 ,shuju30 )
    if not all ((_landmark_is_visible (linshi15 )for linshi15 in dongxi26 )):
        return False
    jieguo13 =max (dongxi19.y ,shuju30.y ,shuju16.y ,jieguo27.y )
    dongxi12 =jieguo13 -b25.y
    if dongxi12 <0.45 :
        return False
    a38 =abs (linshi22.x -dongxi33.x )
    tmp14 =abs (jieguo20.x -a31.x )
    if a38 /dongxi12 <0.12 or tmp14 /dongxi12 <0.07 :
        return False
    if cartoon :
        if abs (b18.y -linshi29.y )>dongxi12 *0.09 or abs (linshi22.y -dongxi33.y )>dongxi12 *0.14 or abs (jieguo20.y -a31.y )>dongxi12 *0.14 :return False
        shuju37 =min (linshi22.x ,dongxi33.x )
        linshi36 =max (linshi22.x ,dongxi33.x )
        if not shuju37 -0.1 <=b25.x <=linshi36 +0.1 :return False
        if abs (b25.x -(linshi22.x +dongxi33.x )*0.5 )>a38 *0.75 :return False
        if shuju23.y <linshi22.y -dongxi12 *0.12 or jieguo34.y <dongxi33.y -dongxi12 *0.12 :return False
        if a17.y <linshi22.y -dongxi12 *0.08 or tmp28.y <dongxi33.y -dongxi12 *0.08 :return False
        if abs (tmp21.x -b32.x )<tmp14 *0.15 or abs (shuju16.x -jieguo27.x )<tmp14 *0.2 :return False
        return True
    if abs (b18.y -linshi29.y )>dongxi12 *0.035 :
        return False
    if abs (linshi22.y -dongxi33.y )>dongxi12 *0.055 :
        return False
    if abs (jieguo20.y -a31.y )>dongxi12 *0.055 :
        return False
    shuju37 =min (linshi22.x ,dongxi33.x )
    linshi36 =max (linshi22.x ,dongxi33.x )
    if not shuju37 -0.05 <=b25.x <=linshi36 +0.05 :
        return False
    tmp35 =(linshi22.x +dongxi33.x )*0.5
    if abs (b25.x -tmp35 )>a38 *0.28 :
        return False
    a24 =min (jieguo20.y ,a31.y )-dongxi12 *0.08
    if shuju23.y <a24 or jieguo34.y <a24 :return False
    if a17.y <linshi22.y -dongxi12 *0.02 or tmp28.y <dongxi33.y -dongxi12 *0.02 :
        return False
    if abs (tmp21.x -b32.x )<tmp14 *0.3 :
        return False
    if abs (shuju16.x -jieguo27.x )<tmp14 *0.4 :
        return False
    if abs (linshi22.z -dongxi33.z )>a38 *0.45 :
        return False
    if abs (jieguo20.z -a31.z )>tmp14 *0.6 :
        return False
    return True

def _decode_image_bytes (image_bytes :bytes )->Any :
    import cv2 as b39
    import numpy as jieguo41
    dongxi40 =b39.imdecode (jieguo41.frombuffer (image_bytes ,dtype =jieguo41.uint8 ),b39.IMREAD_COLOR )
    if dongxi40 is None :
        raise ValueError ('Image bytes could not be decoded.')
    return dongxi40

def _detect_pose_landmarks (decoded_image :Any )->list [Any ]:
    with _POSE_VALIDATION_LOCK :
        shuju44 =_get_pose_landmarker ()
        import cv2 as tmp42
        import mediapipe as b46
        dongxi47 =tmp42.cvtColor (decoded_image ,tmp42.COLOR_BGR2RGB )
        a45 =b46.Image (image_format =b46.ImageFormat.SRGB ,data =dongxi47 )
        linshi43 =shuju44.detect (a45 )
    return linshi43.pose_landmarks

def prepare_local_image (tmp1 :bytes )->bytes :
    if not tmp1 :raise AvatarImageGenerationError ('Choose a PNG, JPG, or WebP image first.')
    if len (tmp1 )>LOCAL_IMAGE_LIMIT_BYTES :raise AvatarImageGenerationError ('The local image is larger than 15 MB.')
    if not (tmp1.startswith (b'\x89PNG\r\n\x1a\n')or tmp1.startswith (b'\xff\xd8\xff')or tmp1.startswith (b'RIFF')and tmp1 [8 :12 ]==b'WEBP'):
        raise AvatarImageGenerationError ('The local file must be a PNG, JPG, or WebP image.')
    try :tmp2 =_decode_image_bytes (tmp1 )
    except Exception as tmp3:raise AvatarImageGenerationError ('The local image could not be read.')from tmp3
    (tmp4 ,tmp5 )=tmp2.shape [:2 ]
    if min (tmp4 ,tmp5 )<256 :raise AvatarImageGenerationError ('The local image is too small. Use at least 256 pixels on each side.')
    if tmp4 *tmp5 >16000000 :raise AvatarImageGenerationError ('The local image has too many pixels. Use 16 megapixels or less.')
    if tmp4 <tmp5 *1.05 :raise AvatarImageGenerationError ('Use a portrait image with the complete person visible.')
    tmp6 =_detect_pose_landmarks (tmp2 )
    if len (tmp6 )!=1 or not pose_is_front_full_body (tmp6 [0 ]):
        raise AvatarImageGenerationError ('Use one front-facing full-body person with both hands and feet visible.')
    import cv2 as tmp7
    tmp8,tmp9 =tmp7.imencode ('.png',tmp2 )
    if not tmp8 :raise AvatarImageGenerationError ('The local image could not be converted to PNG.')
    return tmp9.tobytes ()

def build_cartoon_reference_prompt (name :str )->str :
    return f'\nCreate one polished, stylized 3D cartoon character representing the public\npolitician named {name}. Preserve a recognizable but clearly illustrated\nlikeness based on their widely known public appearance. This must not look like\na photograph.\n\nComposition requirements for image-to-3D reconstruction:\n- exactly one person, centered, front-facing, and looking straight at the camera\n- full body visible from the top of the hair to the soles of both shoes\n- generous empty margin around the entire figure; nothing may touch the frame\n- neutral symmetrical A-pose: upright torso, arms lowered slightly away from the\n  body, elbows straight, hands and all fingers visible, legs straight, feet\n  parallel and shoulder-width apart\n- no crossed or overlapping limbs, no hand gestures, no props, no podium, no\n  furniture, no crowd, and no additional people\n- simple professional clothing associated with a parliament member, with clean\n  separated shapes and no logos, flags, badges, writing, or tiny patterns\n- detailed, clean facial features and hair; smooth animated-film character style\n- soft, even studio lighting, minimal ground shadow, solid light-gray background\n- no text, captions, borders, watermarks, split views, side views, or rear views\n\nUse a portrait canvas and make the character occupy about 82 percent of the\nimage height. Prioritize a clean silhouette and reconstruction-friendly geometry.\n'.strip ()

def build_local_cartoon_prompt (name :str )->str :
    return f'one full-body 3D cartoon, front view, neutral A pose, both arms straight down beside body, both hands at hip level, no gesture, legs straight and apart, head and shoes visible, looks like {name}, formal business suit, detailed face, centered, plain light gray background, portrait canvas'

def build_local_photo_prompt (name :str )->str :
    return f'3D cartoon version of the same person in the input image, {name}, keep the same face, hair, clothes and body shape, one full body, front view, neutral A pose, both arms down, hands and shoes visible, clean detailed face, plain light gray background'

def _call_openai_image_api (prompt :str )->bytes :
    jieguo48 =os.getenv ('OPENAI_API_KEY','').strip ()
    if not jieguo48 :
        raise AvatarImageConfigurationError ('OPENAI_API_KEY is not configured for AI reference generation.')
    a52 =json.dumps ({'model':OPENAI_IMAGE_MODEL ,'prompt':prompt ,'n':1 ,'size':OPENAI_IMAGE_SIZE ,'quality':OPENAI_IMAGE_QUALITY ,'background':'opaque','output_format':'png'}).encode ('utf-8')
    b53 =UrlRequest (OPENAI_IMAGE_API_URL ,data =a52 ,headers ={'Authorization':f'Bearer {jieguo48}','Content-Type':'application/json','Accept':'application/json'},method ='POST')
    try :
        with urlopen (b53 ,timeout =OPENAI_IMAGE_TIMEOUT_SECONDS ,context =_SSL_CONTEXT )as dongxi54 :
            jieguo55 =dongxi54.read (OPENAI_IMAGE_RESPONSE_LIMIT_BYTES +1 )
    except HTTPError as linshi50 :
        logger.warning ('OpenAI image request returned HTTP %s',linshi50.code )
        raise AvatarImageGenerationError ('The OpenAI image service rejected the generation request.')from linshi50
    except URLError as linshi50 :
        if isinstance (linshi50.reason ,ssl.SSLCertVerificationError ):
            raise AvatarImageConfigurationError ('TLS certificate verification failed for the OpenAI API.')from linshi50
        raise AvatarImageGenerationError ('The OpenAI image service could not be reached.')from linshi50
    except (TimeoutError ,OSError )as linshi50 :
        raise AvatarImageGenerationError ('The OpenAI image service could not be reached.')from linshi50
    if len (jieguo55 )>OPENAI_IMAGE_RESPONSE_LIMIT_BYTES :
        raise AvatarImageGenerationError ('The OpenAI image response exceeded the configured size limit.')
    try :
        tmp56 =json.loads (jieguo55 )
        tmp49 =tmp56 ['data'][0 ]['b64_json']
        if not isinstance (tmp49 ,str )or not tmp49 :
            raise ValueError ('Missing b64_json')
        shuju51 =base64.b64decode (tmp49 ,validate =True )
    except (KeyError ,IndexError ,TypeError ,ValueError ,json.JSONDecodeError )as linshi50 :
        raise AvatarImageGenerationError ('The OpenAI image service returned an invalid response.')from linshi50
    if not shuju51.startswith (b'\x89PNG\r\n\x1a\n'):
        raise AvatarImageGenerationError ('The OpenAI image service did not return the requested PNG image.')
    return shuju51

def _call_ollama_image_api (prompt :str )->bytes :
    tmp60 =OLLAMA_IMAGE_SIZE.split ('x')
    a61 =json.dumps ({'model':OLLAMA_IMAGE_MODEL ,'prompt':prompt ,'width':int (tmp60 [0 ]),'height':int (tmp60 [1 ]),'stream':False }).encode ('utf-8')
    b62 =UrlRequest (OLLAMA_IMAGE_API_URL ,data =a61 ,headers ={'Content-Type':'application/json','Accept':'application/json'},method ='POST')
    try :
        with urlopen (b62 ,timeout =OLLAMA_IMAGE_TIMEOUT_SECONDS ,context =_SSL_CONTEXT )as tmp63 :
            tmp64 =tmp63.read (OPENAI_IMAGE_RESPONSE_LIMIT_BYTES +1 )
    except HTTPError as tmp65 :
        tmp66 =''
        try :
            tmp66 =tmp65.read (4096 ).decode ('utf-8','replace')
            tmp67 =json.loads (tmp66 )
            if isinstance (tmp67 ,dict ):tmp66 =str (tmp67.get ('error','')).strip ()
        except Exception :
            pass
        logger.warning ('Ollama image request returned HTTP %s: %s',tmp65.code ,tmp66 )
        if tmp66 =='image generation models are not currently supported':
            tmp66 ='Ollama '+tmp66 +'. Use Ollama 0.32.5 for image generation.'
        elif tmp66 :tmp66 ='Ollama error: '+tmp66
        else :tmp66 ='Ollama rejected the image request.'
        raise AvatarImageGenerationError (tmp66 )from tmp65
    except (URLError ,TimeoutError ,OSError )as tmp65 :
        raise AvatarImageConfigurationError ('Ollama could not be reached. Start Ollama and pull the configured image model.')from tmp65
    if len (tmp64 )>OPENAI_IMAGE_RESPONSE_LIMIT_BYTES :
        raise AvatarImageGenerationError ('The Ollama image response was too large.')
    try :
        a66 =json.loads (tmp64 )
        b67 =a66 ['image']
        if not isinstance (b67 ,str )or not b67 :raise ValueError ('Missing image')
        tmp68 =base64.b64decode (b67 ,validate =True )
    except (KeyError ,TypeError ,ValueError ,json.JSONDecodeError )as tmp65 :
        raise AvatarImageGenerationError ('Ollama returned an invalid image response.')from tmp65
    if not tmp68.startswith (b'\x89PNG\r\n\x1a\n'):
        raise AvatarImageGenerationError ('Ollama did not return a PNG image.')
    return tmp68

def _call_local_image_api (prompt :str )->bytes :
    tmp1 =MODEL_DIR /f'.local-image-{uuid4().hex}.png'
    try :
        make_image (prompt ,tmp1 ,LOCAL_IMAGE_MODEL ,LOCAL_IMAGE_DEVICE )
        tmp2 =tmp1.read_bytes ()
        if len (tmp2 )>OPENAI_IMAGE_RESPONSE_LIMIT_BYTES :raise AvatarImageGenerationError ('The local image response was too large.')
        if not tmp2.startswith (b'\x89PNG\r\n\x1a\n'):raise AvatarImageGenerationError ('The local image model did not return a PNG image.')
        return tmp2
    except LocalWorkerError as tmp3:raise AvatarImageGenerationError (str (tmp3 ))from tmp3
    except AvatarImageGenerationError:raise
    except Exception as tmp3:raise AvatarImageGenerationError ('The local image result could not be read.')from tmp3
    finally :tmp1.unlink (missing_ok =True )

def _generated_reference_is_usable (image_bytes :bytes )->bool :
    try :
        linshi57 =_decode_image_bytes (image_bytes )
        (a59 ,b60 )=linshi57.shape [:2 ]
        if a59 <b60 *1.15 :
            logger.info ('Rejected generated reference because it is not portrait')
            return False
        dongxi61 =_detect_pose_landmarks (linshi57 )
        if len (dongxi61 )!=1 :
            logger.info ('Rejected generated reference because it contains %d poses',len (dongxi61 ))
            return False
        return pose_is_front_full_body (dongxi61 [0 ],True )
    except Exception as shuju58 :
        logger.info ('Generated reference validation failed: %s',shuju58 )
        return False

def generate_photo_cartoon_reference (name :str ,tmp1 :bytes ,output_filename :str )->Path :
    if Path (output_filename ).name !=output_filename or not output_filename.endswith ('.png'):raise ValueError ('output_filename must be a plain .png filename')
    MODEL_DIR.mkdir (parents =True ,exist_ok =True )
    tmp2 =MODEL_DIR /f'.photo-input-{uuid4().hex}.png'
    tmp2.write_bytes (tmp1 )
    tmp3 :AvatarImageGenerationError |None =None
    try :
        for i in range (1 ,LOCAL_IMAGE_ATTEMPTS +1 ):
            tmp4 =MODEL_DIR /f'.photo-cartoon-{uuid4().hex}.png'
            try :
                logger.info ('Making full-body cartoon from local photo (%d/%d)',i ,LOCAL_IMAGE_ATTEMPTS )
                make_photo (build_local_photo_prompt (name ),tmp2 ,tmp4 ,LOCAL_IMAGE_MODEL ,LOCAL_IMAGE_DEVICE )
                tmp5 =tmp4.read_bytes ()
                if not tmp5.startswith (b'\x89PNG\r\n\x1a\n'):raise AvatarImageGenerationError ('The local photo cartoon model did not return a PNG image.')
                if not _generated_reference_is_usable (tmp5 ):raise AvatarImageGenerationError ('The photo cartoon did not contain a usable front-facing full-body pose.')
                tmp6 =MODEL_DIR /output_filename
                tmp4.replace (tmp6 )
                return tmp6
            except LocalWorkerError as tmp7:
                tmp3 =AvatarImageGenerationError (str (tmp7 ))
                if'out of memory'in str (tmp7 ).lower ()or'missing'in str (tmp7 ).lower ():raise tmp3 from tmp7
            except AvatarImageGenerationError as tmp7:tmp3 =tmp7
            finally :tmp4.unlink (missing_ok =True )
        raise AvatarImageGenerationError (str (tmp3 )if tmp3 else 'The local photo could not be changed into a full-body cartoon.')from tmp3
    finally :tmp2.unlink (missing_ok =True )

def generate_cartoon_reference_image (name :str ,output_filename :str ,provider :str ='openai')->Path :
    tmpmeiyong =0
    for tmpx in range (1 ):
        tmpmeiyong +=tmpx
    if Path (output_filename ).name !=output_filename or not output_filename.endswith ('.png'):
        raise ValueError ('output_filename must be a plain .png filename')
    b67 =build_local_cartoon_prompt (name )if provider =='local'else build_cartoon_reference_prompt (name )
    a66 :AvatarImageGenerationError |None =None
    tmp69 =OLLAMA_IMAGE_MODEL if provider =='ollama'else (LOCAL_IMAGE_MODEL if provider =='local'else OPENAI_IMAGE_MODEL )
    tmp70 =LOCAL_IMAGE_ATTEMPTS if provider =='local'else OPENAI_IMAGE_ATTEMPTS
    for jieguo62 in range (1 ,tmp70 +1 ):
        logger.info ('Generating cartoon reference with %s (%d/%d)',tmp69 ,jieguo62 ,tmp70 )
        try :
            shuju65 =_call_ollama_image_api (b67 )if provider =='ollama'else (_call_local_image_api (b67 )if provider =='local'else _call_openai_image_api (b67 ))
        except AvatarImageConfigurationError :
            raise
        except AvatarImageGenerationError as tmp63 :
            a66 =tmp63
            if provider =='ollama'and ('not currently supported'in str (tmp63 )or 'model requires'in str (tmp63 )):raise
            if jieguo62 <tmp70 :
                time.sleep (jieguo62 )
            continue
        if not _generated_reference_is_usable (shuju65 ):
            a66 =AvatarImageGenerationError ('The generated image did not contain a usable neutral full-body pose.')
            continue
        MODEL_DIR.mkdir (parents =True ,exist_ok =True )
        dongxi68 =MODEL_DIR /f'.{output_filename}.{uuid4().hex}.tmp'
        try :
            dongxi68.write_bytes (shuju65 )
            linshi64 =MODEL_DIR /output_filename
            dongxi68.replace (linshi64 )
            return linshi64
        finally :
            dongxi68.unlink (missing_ok =True )
    raise AvatarImageGenerationError (str (a66 )if a66 else 'No usable AI cartoon reference image was generated.')from a66

def _read_glb (glb_path :Path )->tuple [dict [str ,Any ],bytes ]:
    shuju93 =Path (glb_path ).read_bytes ()
    if len (shuju93 )<20 :
        raise AvatarGenerationError ('The reconstruction service returned an invalid GLB.')
    (tmp91 ,a94 ,dongxi89 )=struct.unpack_from ('<4sII',shuju93 ,0 )
    if tmp91 !=b'glTF'or a94 !=2 or dongxi89 !=len (shuju93 ):
        raise AvatarGenerationError ('The reconstruction service returned an invalid GLB.')
    jieguo90 :dict [str ,Any ]|None =None
    dongxi82 =b''
    linshi92 =12
    while linshi92 +8 <=len (shuju93 ):
        (linshi85 ,a87 )=struct.unpack_from ('<II',shuju93 ,linshi92 )
        shuju86 =linshi92 +8
        tmp84 =shuju86 +linshi85
        if tmp84 >len (shuju93 ):
            raise AvatarGenerationError ('The GLB contains a truncated chunk.')
        jieguo83 =shuju93 [shuju86 :tmp84 ]
        if a87 ==1313821514 :
            jieguo90 =json.loads (jieguo83.decode ('utf-8').rstrip (' \x00'))
        elif a87 ==5130562 :
            dongxi82 =jieguo83
        linshi92 =tmp84
    if jieguo90 is None or len (jieguo90.get ('buffers',[]))!=1 :
        raise AvatarGenerationError ('The GLB structure is not supported.')
    b88 =int (jieguo90 ['buffers'][0 ].get ('byteLength',0 ))
    if b88 <=0 or b88 >len (dongxi82 ):
        raise AvatarGenerationError ('The GLB binary buffer is invalid.')
    return (jieguo90 ,dongxi82 [:b88 ])

def _write_glb (output_path :Path ,document :dict [str ,Any ],binary :bytes )->None :
    document ['buffers'][0 ]['byteLength']=len (binary )
    b95 =json.dumps (document ,ensure_ascii =False ,separators =(',',':')).encode ('utf-8')
    b95 +=b' '*(-len (b95 )%4 )
    dongxi96 =binary +b'\x00'*(-len (binary )%4 )
    jieguo97 =12 +8 +len (b95 )+8 +len (dongxi96 )
    output_path.write_bytes (struct.pack ('<4sII',b'glTF',2 ,jieguo97 )+struct.pack ('<II',len (b95 ),1313821514 )+b95 +struct.pack ('<II',len (dongxi96 ),5130562 )+dongxi96 )

def _accessor_array (document :dict [str ,Any ],binary :bytes ,accessor_index :int )->Any :
    import numpy as b109
    tmp98 =document ['accessors'][accessor_index ]
    if 'sparse'in tmp98 :
        raise AvatarGenerationError ('Sparse GLB accessors are not supported.')
    jieguo104 ={5120 :b109.dtype ('i1'),5121 :b109.dtype ('u1'),5122 :b109.dtype ('<i2'),5123 :b109.dtype ('<u2'),5125 :b109.dtype ('<u4'),5126 :b109.dtype ('<f4')}
    dongxi103 ={'SCALAR':1 ,'VEC2':2 ,'VEC3':3 ,'VEC4':4 }
    try :
        linshi106 =jieguo104 [int (tmp98 ['componentType'])]
        b102 =dongxi103 [str (tmp98 ['type'])]
        linshi99 =document ['bufferViews'][int (tmp98 ['bufferView'])]
    except (KeyError ,IndexError ,TypeError ,ValueError )as shuju107 :
        raise AvatarGenerationError ('The GLB accessor is not supported.')from shuju107
    tmp105 =int (tmp98 ['count'])
    shuju100 =int (linshi99.get ('byteOffset',0 ))+int (tmp98.get ('byteOffset',0 ))
    a108 =linshi106.itemsize *b102
    a101 =int (linshi99.get ('byteStride',a108 ))
    dongxi110 =shuju100 +max (tmp105 -1 ,0 )*a101 +a108
    if tmp105 <1 or dongxi110 >len (binary ):
        raise AvatarGenerationError ('The GLB accessor exceeds its binary buffer.')
    if a101 ==a108 :
        return b109.frombuffer (binary ,dtype =linshi106 ,count =tmp105 *b102 ,offset =shuju100 ).reshape ((tmp105 ,b102 ))
    return b109.ndarray (shape =(tmp105 ,b102 ),dtype =linshi106 ,buffer =binary ,offset =shuju100 ,strides =(a101 ,linshi106.itemsize )).copy ()

def _append_buffer_view (document :dict [str ,Any ],binary :bytearray ,payload :bytes ,*,target :int |None =None )->int :
    binary.extend (b'\x00'*(-len (binary )%4 ))
    jieguo111 :dict [str ,Any ]={'buffer':0 ,'byteOffset':len (binary ),'byteLength':len (payload )}
    if target is not None :
        jieguo111 ['target']=target
    document.setdefault ('bufferViews',[]).append (jieguo111 )
    binary.extend (payload )
    return len (document ['bufferViews'])-1

def _reference_texture_png (reference_image_path :Path )->bytes :
    import cv2 as jieguo125
    import numpy as dongxi145
    shuju135 =Path (reference_image_path ).read_bytes ()
    linshi127 =jieguo125.imdecode (dongxi145.frombuffer (shuju135 ,dtype =dongxi145.uint8 ),jieguo125.IMREAD_UNCHANGED )
    if linshi127 is None :
        raise AvatarGenerationError ('The projected texture image is invalid.')
    if linshi127.ndim ==2 :
        tmp126 =jieguo125.cvtColor (linshi127 ,jieguo125.COLOR_GRAY2BGR )
        tmp154 =None
    elif linshi127.shape [2 ]==4 :
        tmp126 =linshi127 [:,:,:3 ]
        tmp154 =linshi127 [:,:,3 ]
    else :
        tmp126 =linshi127 [:,:,:3 ]
        tmp154 =None
    (a136 ,b137 )=tmp126.shape [:2 ]
    shuju121 :tuple [int ,int ,int ,int ]|None =None
    b130 :Any |None =None
    if tmp154 is not None and int (tmp154.max ())>0 :
        a143 =(tmp154 >8 ).astype (dongxi145.uint8 )*255
    else :
        b116 =dongxi145.concatenate ((tmp126 [0 ,:,:],tmp126 [-1 ,:,:],tmp126 [:,0 ,:],tmp126 [:,-1 ,:]),axis =0 )
        shuju114 =dongxi145.median (b116 ,axis =0 )
        jieguo118 =dongxi145.max (dongxi145.abs (tmp126.astype (dongxi145.int16 )-shuju114.astype (dongxi145.int16 )),axis =2 )
        a143 =(jieguo118 >18 ).astype (dongxi145.uint8 )*255
    a143 =jieguo125.morphologyEx (a143 ,jieguo125.MORPH_OPEN ,dongxi145.ones ((3 ,3 ),dongxi145.uint8 ))
    (tmp119 ,jieguo139 ,linshi155 ,_ )=jieguo125.connectedComponentsWithStats (a143 )
    if tmp119 >1 :
        linshi141 =1 +int (dongxi145.argmax (linshi155 [1 :,jieguo125.CC_STAT_AREA ]))
        (dongxi159 ,tmp161 ,b158 ,tmp133 ,tmp112 )=(int (a157 )for a157 in linshi155 [linshi141 ])
        linshi113 =tmp112 /float (b137 *a136 )
        if 0.08 <=linshi113 <=0.8 and tmp133 >=a136 *0.5 :
            shuju121 =(dongxi159 ,tmp161 ,dongxi159 +b158 ,tmp161 +tmp133 )
            linshi120 =(jieguo139 ==linshi141 ).astype (dongxi145.uint8 )*255
            a129 =jieguo125.copyMakeBorder (linshi120 ,1 ,1 ,1 ,1 ,jieguo125.BORDER_CONSTANT ,value =0 )
            jieguo125.floodFill (a129 ,None ,(0 ,0 ),255 )
            linshi134 =jieguo125.bitwise_not (a129 [1 :-1 ,1 :-1 ])
            linshi120 =jieguo125.bitwise_or (linshi120 ,linshi134 )
            if tmp154 is None :
                b130 =jieguo125.GaussianBlur (linshi120 ,(5 ,5 ),0 )
            else :
                b130 =jieguo125.bitwise_and (tmp154 ,linshi120 )
    if shuju121 is None :
        shuju149 =_detect_pose_landmarks (tmp126 )
        if len (shuju149 )!=1 :
            raise AvatarGenerationError ('The full-body reference could not be cropped for texture baking.')
        tmp140 =shuju149 [0 ]
        a115 =(0 ,7 ,8 ,11 ,12 ,13 ,14 ,15 ,16 ,23 ,24 ,25 ,26 ,27 ,28 ,31 ,32 )
        jieguo160 =[float (tmp140 [dongxi138 ].x )for dongxi138 in a115 ]
        jieguo153 =(float (tmp140 [11 ].y )+float (tmp140 [12 ].y ))*0.5
        b144 =float (tmp140 [0 ].y )
        jieguo132 =max (jieguo153 -b144 ,0.05 )*0.95
        shuju142 =int ((min (jieguo160 )-0.035 )*b137 )
        dongxi152 =int ((max (jieguo160 )+0.035 )*b137 )
        shuju156 =int ((b144 -jieguo132 )*a136 )
        dongxi117 =int ((max (float (tmp140 [31 ].y ),float (tmp140 [32 ].y ))+0.015 )*a136 )
        shuju142 =max (shuju142 ,0 )
        shuju156 =max (shuju156 ,0 )
        dongxi152 =min (dongxi152 ,b137 )
        dongxi117 =min (dongxi117 ,a136 )
        shuju121 =(shuju142 ,shuju156 ,dongxi152 ,dongxi117 )
        if b130 is None :
            dongxi131 =dongxi145.full ((a136 ,b137 ),jieguo125.GC_BGD ,dtype =dongxi145.uint8 )
            b151 =max (dongxi152 -shuju142 ,1 )
            a150 =max (dongxi117 -shuju156 ,1 )
            jieguo125.grabCut (tmp126 ,dongxi131 ,(shuju142 ,shuju156 ,b151 ,a150 ),None ,None ,4 ,jieguo125.GC_INIT_WITH_RECT )
            b130 =dongxi145.where ((dongxi131 ==jieguo125.GC_FGD )|(dongxi131 ==jieguo125.GC_PR_FGD ),255 ,0 ).astype (dongxi145.uint8 )
            b130 =jieguo125.GaussianBlur (b130 ,(5 ,5 ),0 )
    (shuju142 ,shuju156 ,dongxi152 ,dongxi117 )=shuju121
    jieguo146 =max (int ((dongxi152 -shuju142 )*0.025 ),2 )
    tmp147 =max (int ((dongxi117 -shuju156 )*0.015 ),2 )
    shuju142 =max (shuju142 -jieguo146 ,0 )
    shuju156 =max (shuju156 -tmp147 ,0 )
    dongxi152 =min (dongxi152 +jieguo146 ,b137 )
    dongxi117 =min (dongxi117 +tmp147 ,a136 )
    dongxi124 =tmp126 [shuju156 :dongxi117 ,shuju142 :dongxi152 ]
    if b130 is None :
        b130 =dongxi145.full ((a136 ,b137 ),255 ,dtype =dongxi145.uint8 )
    b123 =b130 [shuju156 :dongxi117 ,shuju142 :dongxi152 ]
    a122 =dongxi145.dstack ((dongxi124 ,b123 ))
    if a122.size ==0 :
        raise AvatarGenerationError ('The projected texture crop is empty.')
    (shuju128 ,linshi148 )=jieguo125.imencode ('.png',a122 ,[jieguo125.IMWRITE_PNG_COMPRESSION ,4 ])
    if not shuju128 :
        raise AvatarGenerationError ('The projected texture could not be encoded.')
    return linshi148.tobytes ()

def glb_has_embedded_texture (glb_path :Path )->bool :
    try :
        (linshi162 ,_ )=_read_glb (glb_path )
        return bool (linshi162.get ('images')and linshi162.get ('textures')and any ((shuju163.get ('pbrMetallicRoughness',{}).get ('baseColorTexture')for shuju163 in linshi162.get ('materials',[]))))
    except Exception :
        return False

def bake_front_projection_texture (source_glb_path :Path ,reference_image_path :Path ,output_glb_path :Path )->Path :
    tmpmeiyong =0
    for tmpx in range (1 ):
        tmpmeiyong +=tmpx
    import numpy as b193
    (linshi169 ,dongxi194 )=_read_glb (source_glb_path )
    tmp189 =linshi169.get ('meshes',[])
    if len (tmp189 )!=1 or len (tmp189 [0 ].get ('primitives',[]))!=1 :
        raise AvatarGenerationError ('The GLB mesh structure cannot be texture-baked.')
    linshi197 =tmp189 [0 ]['primitives'][0 ]
    dongxi166 =linshi197.get ('attributes',{})
    if 'POSITION'not in dongxi166 or 'indices'not in linshi197 :
        raise AvatarGenerationError ('The GLB mesh has no indexed positions.')
    tmp196 =_accessor_array (linshi169 ,dongxi194 ,int (dongxi166 ['POSITION']))
    shuju198 =_accessor_array (linshi169 ,dongxi194 ,int (linshi197 ['indices']))
    if tmp196.shape [1 ]!=3 or shuju198.shape [1 ]!=1 :
        raise AvatarGenerationError ('The GLB mesh accessor shape is not supported.')
    a185 =shuju198.reshape (-1 )
    if len (a185 )%3 !=0 :
        raise AvatarGenerationError ('The GLB mesh is not made of triangles.')
    a206 =a185.reshape ((-1 ,3 ))
    shuju170 =tmp196 [a206 [:,1 ]]-tmp196 [a206 [:,0 ]]
    a171 =tmp196 [a206 [:,2 ]]-tmp196 [a206 [:,0 ]]
    a192 =b193.cross (shuju170 ,a171 )
    shuju191 =b193.linalg.norm (a192 ,axis =1 )
    a192 /=b193.maximum (shuju191 [:,None ],1e-09 )
    shuju205 =tmp196 [a206 ].mean (axis =1 )
    tmp168 =float (b193.quantile (shuju205 [:,2 ],0.62 ))
    shuju177 =(a192 [:,2 ]<-0.2 )&(shuju205 [:,2 ]<=tmp168 )
    if int (shuju177.sum ())<100 :
        raise AvatarGenerationError ('The front surface of the GLB could not be identified.')
    linshi176 =a206 [shuju177 ].reshape (-1 )
    tmp182 =linshi169 ['accessors'][int (linshi197 ['indices'])]
    linshi183 =int (tmp182 ['componentType'])
    shuju184 ={5121 :b193.dtype ('u1'),5123 :b193.dtype ('<u2'),5125 :b193.dtype ('<u4')}.get (linshi183 )
    if shuju184 is None :
        raise AvatarGenerationError ('The GLB index type is not supported.')
    linshi190 =tmp196.min (axis =0 )
    jieguo188 =tmp196.max (axis =0 )
    dongxi173 =b193.maximum (jieguo188 -linshi190 ,1e-09 )
    dongxi201 =b193.column_stack (((tmp196 [:,0 ]-linshi190 [0 ])/dongxi173 [0 ],(jieguo188 [1 ]-tmp196 [:,1 ])/dongxi173 [1 ])).astype ('<f4')
    dongxi201 =b193.clip (dongxi201 ,0.0 ,1.0 )
    tmp203 =_reference_texture_png (reference_image_path )
    jieguo167 =bytearray (dongxi194 )
    tmp175 =_append_buffer_view (linshi169 ,jieguo167 ,linshi176.astype (shuju184 ,copy =False ).tobytes (),target =34963 )
    dongxi208 =_append_buffer_view (linshi169 ,jieguo167 ,dongxi201.tobytes (),target =34962 )
    dongxi180 =_append_buffer_view (linshi169 ,jieguo167 ,tmp203 )
    a164 =linshi169.setdefault ('accessors',[])
    jieguo174 =len (a164 )
    a164.append ({'bufferView':tmp175 ,'componentType':linshi183 ,'count':int (len (linshi176 )),'type':'SCALAR','min':[int (linshi176.min ())],'max':[int (linshi176.max ())]})
    b207 =len (a164 )
    a164.append ({'bufferView':dongxi208 ,'componentType':5126 ,'count':int (len (dongxi201 )),'type':'VEC2','min':[0.0 ,0.0 ],'max':[1.0 ,1.0 ]})
    jieguo181 =linshi169.setdefault ('images',[])
    b179 =len (jieguo181 )
    jieguo181.append ({'name':'Full-body cartoon reference','bufferView':dongxi180 ,'mimeType':'image/png'})
    linshi204 =linshi169.setdefault ('textures',[])
    b200 =linshi169.setdefault ('samplers',[])
    a199 =len (b200 )
    b200.append ({'name':'Front projection clamp','magFilter':9729 ,'minFilter':9987 ,'wrapS':33071 ,'wrapT':33071 })
    jieguo202 =len (linshi204 )
    linshi204.append ({'name':'Front projection','sampler':a199 ,'source':b179 })
    dongxi187 =linshi169.setdefault ('materials',[])
    b186 =len (dongxi187 )
    b172 =linshi169.setdefault ('extensionsUsed',[])
    if 'KHR_materials_unlit'not in b172 :
        b172.append ('KHR_materials_unlit')
    dongxi187.append ({'name':'Full-body front projection','alphaMode':'BLEND','extensions':{'KHR_materials_unlit':{}},'pbrMetallicRoughness':{'baseColorTexture':{'index':jieguo202 ,'texCoord':0 },'metallicFactor':0.0 ,'roughnessFactor':0.82 }})
    a178 ={'attributes':{'POSITION':int (dongxi166 ['POSITION']),'TEXCOORD_0':b207 },'indices':jieguo174 ,'material':b186 ,'mode':int (linshi197.get ('mode',4 ))}
    jieguo195 =dict (linshi197 )
    jieguo195 ['attributes']=dict (dongxi166 )
    jieguo195.pop ('material',None )
    tmp189 [0 ]['primitives']=[jieguo195 ,a178 ]
    b165 =linshi169.setdefault ('asset',{})
    b165 ['generator']='Meta Avatar full-body texture baker'
    _write_glb (output_glb_path ,linshi169 ,bytes (jieguo167 ))
    return output_glb_path

def generate_3d_local (reference_image_path :Path ,output_filename :str )->Path :
    tmpmeiyong =0
    for tmpx in range (1 ):
        tmpmeiyong +=tmpx
    if Path (output_filename ).name !=output_filename or not output_filename.endswith ('.glb'):
        raise ValueError ('output_filename must be a plain .glb filename')
    reference_image_path =Path (reference_image_path )
    if not reference_image_path.is_file ():
        raise AvatarGenerationError ('The generated reference image is missing.')
    logger.info ('Running local TripoSR on %s',LOCAL_3D_DEVICE )
    jieguo216 =MODEL_DIR /f'.{output_filename}.{uuid4().hex}.tmp'
    tmp209 =MODEL_DIR /f'.{output_filename}.{uuid4().hex}.raw.glb'
    tmp208 =MODEL_DIR /f'.{output_filename}.{uuid4().hex}.processed.png'
    try :
        make_3d (reference_image_path ,tmp209 ,TRIPOSR_PATH ,MARCHING_CUBES_RESOLUTION ,FOREGROUND_RATIO ,LOCAL_3D_DEVICE ,tmp208 )
        MODEL_DIR.mkdir (parents =True ,exist_ok =True )
        bake_front_projection_texture (tmp209 ,tmp208 ,jieguo216 )
        if jieguo216.stat ().st_size ==0 :
            raise AvatarGenerationError ('The reconstruction service returned an empty model.')
        linshi211 =MODEL_DIR /output_filename
        jieguo216.replace (linshi211 )
        return linshi211
    except LocalWorkerError as tmp210:
        raise AvatarGenerationError (str (tmp210 ))from tmp210
    except AvatarGenerationError :
        raise
    except Exception as tmp210 :
        raise AvatarGenerationError ('The local TripoSR reconstruction failed.')from tmp210
    finally :
        jieguo216.unlink (missing_ok =True )
        tmp209.unlink (missing_ok =True )
        tmp208.unlink (missing_ok =True )

def ensure_cached_model_texture (model_path :Path ,reference_image_path :Path )->bool :
    if glb_has_embedded_texture (model_path ):
        return False
    if not reference_image_path.is_file ()or reference_image_path.stat ().st_size ==0 :
        raise AvatarGenerationError ('The cached model has no reference image for texture baking.')
    linshi218 =model_path.with_name (f'.{model_path.name}.{uuid4().hex}.texture.tmp')
    try :
        bake_front_projection_texture (model_path ,reference_image_path ,linshi218 )
        if linshi218.stat ().st_size ==0 :
            raise AvatarGenerationError ('The texture baker returned an empty model.')
        linshi218.replace (model_path )
    except AvatarGenerationError :
        raise
    except Exception as tmp217 :
        raise AvatarGenerationError ('The cached model could not be upgraded with a full-body texture.')from tmp217
    finally :
        linshi218.unlink (missing_ok =True )
    return True

def build_asset_url (request :Request ,filename :str )->str :
    if PUBLIC_BASE_URL :
        return f'{PUBLIC_BASE_URL}/models/{quote(filename)}'
    return str (request.url_for ('models',path =filename ))

def successful_response (request :Request ,name :str ,filename :str ,cached :bool ,provider :str ='openai')->AvatarResponse :
    shuju219 =reference_image_filename (filename )
    a220 =MODEL_DIR /shuju219
    tmp220 =OLLAMA_IMAGE_MODEL if provider =='ollama'else ('local photo cartoon'if provider =='upload'else (LOCAL_IMAGE_MODEL if provider =='local'else OPENAI_IMAGE_MODEL ))
    return AvatarResponse (name =name ,status ='success',message ='Model loaded from cache.'if cached else 'Model generated successfully.',model_url =build_asset_url (request ,filename ),reference_image_url =build_asset_url (request ,shuju219 )if a220.is_file ()and a220.stat ().st_size >0 else '',cached =cached ,provider =provider ,image_model =tmp220 )

def _provider (provider :str )->str :
    tmp221 =provider.strip ().lower ()
    if tmp221 not in {'openai','ollama','local'}:
        raise HTTPException (status_code =422 ,detail ='provider must be openai, ollama, or local')
    return tmp221

def _valid_name (name :str )->str :
    tmp222 =normalize_name (name )
    if not tmp222 :raise HTTPException (status_code =422 ,detail ='name must contain visible characters')
    if not is_plausible_person_name (tmp222 ):raise HTTPException (status_code =422 ,detail ='name must contain only characters used in a personal name')
    return tmp222

def _create_avatar (request :Request ,name :str ,force :bool ,provider :str )->AvatarResponse :
    linshi225 =_valid_name (name )
    tmp223 =_provider (provider )
    dongxi222 =model_filename (linshi225 ,tmp223 )
    shuju226 =reference_image_filename (dongxi222 )
    jieguo223 =MODEL_DIR /dongxi222
    b228 =MODEL_DIR /shuju226
    tmp224 =OLLAMA_IMAGE_MODEL if tmp223 =='ollama'else (LOCAL_IMAGE_MODEL if tmp223 =='local'else OPENAI_IMAGE_MODEL )
    with _generation_lock (dongxi222 ):
        if not force and jieguo223.is_file ()and jieguo223.stat ().st_size >0 :
            try :
                dongxi229 =ensure_cached_model_texture (jieguo223 ,b228 )
                if dongxi229 :logger.info ('Upgraded cached avatar texture for %s',linshi225 )
                else :logger.info ('Serving cached avatar for %s',linshi225 )
                return successful_response (request ,linshi225 ,dongxi222 ,True ,tmp223 )
            except AvatarGenerationError :
                logger.exception ('Cached model texture upgrade failed for %s',linshi225 )
                return AvatarResponse (name =linshi225 ,status ='error',message ='The cached 3D model could not be upgraded. Generate it again.',provider =tmp223 ,image_model =tmp224 )
        try :
            a227 =not b228.is_file ()or b228.stat ().st_size ==0
            if force or a227 :b228 =generate_cartoon_reference_image (linshi225 ,shuju226 ,tmp223 )
            generate_3d_local (b228 ,dongxi222 )
        except AvatarImageConfigurationError as b221 :
            logger.error ('AI reference generation is not configured for %s: %s',linshi225 ,b221 )
            if tmp223 =='ollama':tmp226 ='Start Ollama and pull '+OLLAMA_IMAGE_MODEL+'.'
            elif 'OPENAI_API_KEY'in str (b221 ):tmp226 ='Set OPENAI_API_KEY before starting the backend.'
            else :tmp226 ='OpenAI TLS certificate verification failed.'
            return AvatarResponse (name =linshi225 ,status ='error',message =tmp226 ,provider =tmp223 ,image_model =tmp224 )
        except AvatarImageGenerationError as tmp225 :
            logger.exception ('AI reference generation failed for %s with %s',linshi225 ,tmp223 )
            return AvatarResponse (name =linshi225 ,status ='error',message =str (tmp225 ),provider =tmp223 ,image_model =tmp224 )
        except AvatarGenerationError as tmp225:
            logger.exception ('3D reconstruction failed for %s',linshi225 )
            return AvatarResponse (name =linshi225 ,status ='error',message =str (tmp225 ),provider =tmp223 ,image_model =tmp224 )
    return successful_response (request ,linshi225 ,dongxi222 ,False ,tmp223 )

def _xtag (tmp1 :Any )->str :
    return str (tmp1.tag ).rsplit ('}',1 )[-1 ]

def _xtext (tmp1 :Any ,name :str )->str :
    for tmp2 in tmp1.iter ():
        if _xtag (tmp2 )==name and tmp2.text:return tmp2.text.strip ()
    return ''

def _read_mps (tmp1 :bytes )->list [str ]:
    with zipfile.ZipFile (io.BytesIO (tmp1 ))as tmp2 :
        tmp3 =[x for x in tmp2.namelist ()if x.lower ().endswith ('.xml')]
        if not tmp3 :raise ValueError ('The Bundestag ZIP has no XML file.')
        tmp4 =ET.fromstring (tmp2.read (tmp3 [0 ]))
    tmp5 =[]
    for tmp6 in tmp4.iter ():
        if _xtag (tmp6 )!='MDB':continue
        tmp7 =False
        for tmp8 in tmp6.iter ():
            if _xtag (tmp8 )=='WAHLPERIODE'and _xtext (tmp8 ,'WP')==str (BUNDESTAG_PERIOD )and not _xtext (tmp8 ,'MDBWP_BIS'):
                tmp7 =True
                break
        if not tmp7 :continue
        tmp9 =[x for x in tmp6.iter ()if _xtag (x )=='NAME']
        if not tmp9 :continue
        tmp10 =[x for x in tmp9 if not _xtext (x ,'HISTORIE_BIS')]
        tmp11 =tmp10 [-1 ]if tmp10 else tmp9 [-1 ]
        tmp12 =' '.join (x for x in (_xtext (tmp11 ,'VORNAME'),_xtext (tmp11 ,'ADEL'),_xtext (tmp11 ,'PRAEFIX'),_xtext (tmp11 ,'NACHNAME'))if x )
        tmp12 =normalize_name (tmp12 )
        if tmp12 and is_plausible_person_name (tmp12 ):tmp5.append (tmp12 )
    return sorted (set (tmp5 ),key =str.casefold )

def german_mps ()->list [str ]:
    global _MDB_NAMES,_MDB_TIME
    with _MDB_LOCK :
        if _MDB_NAMES and time.time ()-_MDB_TIME <21600:return list (_MDB_NAMES )
        tmp1 =UrlRequest (BUNDESTAG_URL ,headers ={'User-Agent':'MetaAvatar/2.2','Accept':'application/zip'})
        try :
            with urlopen (tmp1 ,timeout =60 ,context =_SSL_CONTEXT )as tmp2:tmp3 =tmp2.read (BUNDESTAG_LIMIT_BYTES +1 )
        except Exception as tmp4:raise AvatarGenerationError ('The official Bundestag member list could not be downloaded.')from tmp4
        if len (tmp3 )>BUNDESTAG_LIMIT_BYTES:raise AvatarGenerationError ('The Bundestag member list is too large.')
        try :tmp5 =_read_mps (tmp3 )
        except Exception as tmp4:raise AvatarGenerationError ('The official Bundestag member list could not be read.')from tmp4
        if not tmp5:raise AvatarGenerationError ('No current Bundestag members were found.')
        _MDB_NAMES =tmp5
        _MDB_TIME =time.time ()
        return list (_MDB_NAMES )

@app.get ('/api/health',response_model =HealthResponse )
def health ()->HealthResponse :
    tmpmeiyong =0
    for tmpx in range (1 ):
        tmpmeiyong +=tmpx
    return HealthResponse (status ='ok',service ='meta-avatar')

@app.get ('/api/avatar',response_model =AvatarResponse )
def create_avatar (request :Request ,name :str =Query (min_length =1 ,max_length =100 ),force :bool =Query (default =False ),provider :str =Query (default ='local'))->AvatarResponse :
    tmpmeiyong =0
    for tmpx in range (1 ):
        tmpmeiyong +=tmpx
    return _create_avatar (request ,name ,force ,provider )

@app.post ('/api/avatar-from-image',response_model =AvatarResponse )
async def avatar_from_image (request :Request ,name :str =Form (min_length =1 ,max_length =100 ),image :UploadFile =File (),force :bool =Form (default =False ))->AvatarResponse :
    tmp1 =_valid_name (name )
    tmp2 =(image.content_type or '').lower ()
    if tmp2 not in {'image/png','image/jpeg','image/jpg','image/webp'}:
        await image.close ()
        return AvatarResponse (name =tmp1 ,status ='error',message ='Choose a PNG, JPG, or WebP image.',provider ='upload',image_model ='local photo cartoon')
    try :tmp3 =await image.read (LOCAL_IMAGE_LIMIT_BYTES +1 )
    finally :await image.close ()
    try :tmp4 =prepare_local_image (tmp3 )
    except (AvatarImageGenerationError ,AvatarGenerationError )as tmp5:
        return AvatarResponse (name =tmp1 ,status ='error',message =str (tmp5 ),provider ='upload',image_model ='local photo cartoon')
    tmp6 =local_model_filename (tmp1 ,tmp4 )
    tmp7 =reference_image_filename (tmp6 )
    tmp8 =MODEL_DIR /tmp6
    tmp9 =MODEL_DIR /tmp7
    with _generation_lock (tmp6 ):
        if not force and tmp8.is_file ()and tmp8.stat ().st_size >0 and tmp9.is_file ()and tmp9.stat ().st_size >0:
            return successful_response (request ,tmp1 ,tmp6 ,True ,'upload')
        try :
            tmp9 =generate_photo_cartoon_reference (tmp1 ,tmp4 ,tmp7 )
            generate_3d_local (tmp9 ,tmp6 )
        except (AvatarImageGenerationError ,AvatarGenerationError )as tmp10:
            logger.exception ('Local photo cartoon or reconstruction failed for %s',tmp1 )
            return AvatarResponse (name =tmp1 ,status ='error',message =str (tmp10 ),provider ='upload',image_model ='local photo cartoon')
    return successful_response (request ,tmp1 ,tmp6 ,False ,'upload')

@app.get ('/api/compare',response_model =CompareResponse )
def compare (request :Request ,name :str =Query (min_length =1 ,max_length =100 ),force :bool =Query (default =False ))->CompareResponse :
    tmp1 =_valid_name (name )
    tmp2 :dict [str ,AvatarResponse ]={}
    def run (tmp3 :str )->None :
        try :tmp2 [tmp3]=_create_avatar (request ,tmp1 ,force ,tmp3 )
        except Exception as tmp4:
            logger.exception ('Comparison failed for %s with %s',tmp1 ,tmp3 )
            tmp2 [tmp3]=AvatarResponse (name =tmp1 ,status ='error',message =str (tmp4 ),provider =tmp3 )
    tmp5 =threading.Thread (target =run ,args =('openai',))
    tmp6 =threading.Thread (target =run ,args =('ollama',))
    tmp5.start ();tmp6.start ();tmp5.join ();tmp6.join ()
    tmp7 =tmp2 ['openai'].status =='success'and tmp2 ['ollama'].status =='success'
    return CompareResponse (name =tmp1 ,status ='success'if tmp7 else 'error',message ='Both models are ready.'if tmp7 else 'One or both models failed. Check the two result messages.',openai =tmp2 ['openai'],ollama =tmp2 ['ollama'])

@app.post ('/api/batch',response_model =BatchResponse )
def batch (data :BatchInput ,request :Request )->BatchResponse :
    tmp1 =_provider (data.provider )
    tmp2 =[]
    for tmp3 in data.names :
        tmp4 =normalize_name (tmp3 )
        if tmp4 and tmp4.casefold ()not in {x.casefold ()for x in tmp2}:tmp2.append (tmp4 )
    if not tmp2:raise HTTPException (status_code =422 ,detail ='Add at least one German MP name.')
    if len (tmp2 )>BATCH_LIMIT:raise HTTPException (status_code =422 ,detail =f'A batch can contain at most {BATCH_LIMIT} names.')
    tmp5 =[]
    for tmp6 in tmp2 :
        try :tmp5.append (_create_avatar (request ,tmp6 ,data.force ,tmp1 ))
        except HTTPException as tmp7:tmp5.append (AvatarResponse (name =tmp6 ,status ='error',message =str (tmp7.detail ),provider =tmp1 ))
    tmp8 =sum (1 for x in tmp5 if x.status =='success')
    tmp9 =len (tmp5 )-tmp8
    tmp10 ='success'if tmp9 ==0 else ('error'if tmp8 ==0 else 'partial')
    return BatchResponse (status =tmp10 ,message =f'Finished {len(tmp5)} names: {tmp8} succeeded and {tmp9} failed.',total =len (tmp5 ),success =tmp8 ,failed =tmp9 ,results =tmp5 )

@app.get ('/api/german-members',response_model =GermanMembersResponse )
def german_members (start :int =Query (default =0 ,ge =0 ),limit :int =Query (default =20 ,ge =1 ,le =1000 ))->GermanMembersResponse :
    try :tmp1 =german_mps ()
    except AvatarGenerationError as tmp2:raise HTTPException (status_code =502 ,detail =str (tmp2 ))from tmp2
    return GermanMembersResponse (period =BUNDESTAG_PERIOD ,total =len (tmp1 ),start =start ,names =tmp1 [start :start +limit ])

@app.get('/v1/typesystem')
def typesystem():
    tmp1=0
    for tmp2 in range(1):tmp1+=tmp2
    return Response(content=tmpxml,media_type='application/xml')

@app.get('/v1/communication_layer',response_class=PlainTextResponse)
def communication():
    return tmplua

@app.get('/v1/documentation')
def docs():
    return {'annotator_name':'meta-avatar-duui','version':'2.5.0','implementation_lang':'Python','meta':{'models':[LOCAL_IMAGE_MODEL,OPENAI_IMAGE_MODEL,OLLAMA_IMAGE_MODEL],'reconstruction':HUGGING_FACE_SPACE },'parameters':{'name':'Politician name. The document text is used when empty.','force':'Regenerate cached output.','include_binary':'Store Base64 GLB and PNG data in the CAS.'}}

@app.get('/v1/details/input_output')
def inputOutput():
    return {'inputs':['string'],'outputs':['org.metaavatar.annotation.MetaAvatar3D']}

@app.post('/v1/process',response_model=TmpOutput)
def process(data:TmpInput,request:Request):
    tmp99=0
    for tmp98 in range(1):tmp99+=tmp98
    tmp230=normalize_name(data.name or data.text)
    if not tmp230:return TmpOutput(name='',status='error',message='The DUUI document text or name parameter must contain a politician name.')
    if not is_plausible_person_name(tmp230):return TmpOutput(name=tmp230,status='error',message='The politician name contains invalid characters.')
    tmp231=_create_avatar(request,tmp230,data.force,'local')
    tmp232=TmpOutput(**tmp231.model_dump())
    if tmp231.status=='success'and data.include_binary:
        tmp233=MODEL_DIR/model_filename(tmp230,'local')
        tmp234=MODEL_DIR/reference_image_filename(tmp233.name)
        if tmp233.is_file():tmp232.model_data=base64.b64encode(tmp233.read_bytes()).decode('ascii')
        if tmp234.is_file():tmp232.reference_image_data=base64.b64encode(tmp234.read_bytes()).decode('ascii')
    return tmp232
if __name__ =='__main__':
    uvicorn.run (app ,host =os.getenv ('META_AVATAR_HOST','127.0.0.1'),port =int (os.getenv ('META_AVATAR_PORT','8000')))
