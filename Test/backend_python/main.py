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
from pydantic import BaseModel
from local_worker import LocalWorkerError ,ResultFlagged ,run_photo_cartoon ,run_triposr
logging.basicConfig (level =os.getenv ('META_AVATAR_LOG_LEVEL','INFO').upper (),format ='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger =logging.getLogger ('meta_avatar')
BASE_DIR =Path (__file__ ).resolve ().parent
MODEL_DIR =Path (os.getenv ('META_AVATAR_OUTPUT_DIR',str (BASE_DIR /'hf_generated_models'))).expanduser ()
MODEL_DIR.mkdir (parents =True ,exist_ok =True )
PUBLIC_BASE_URL =os.getenv ('META_AVATAR_PUBLIC_BASE_URL','').rstrip ('/')
LOCAL_MODELS_DIR =Path (os.getenv ('META_AVATAR_LOCAL_MODELS',str (BASE_DIR /'local_models'))).expanduser ()
LOCAL_3D_DEVICE =os.getenv ('META_AVATAR_LOCAL_3D_DEVICE','cpu')
LOCAL_IMAGE_DEVICE =os.getenv ('META_AVATAR_LOCAL_IMAGE_DEVICE','auto')
LOCAL_PHOTO_STRENGTH =float (os.getenv ('META_AVATAR_LOCAL_PHOTO_STRENGTH','0.42'))
LOCAL_IMAGE_ATTEMPTS =int (os.getenv ('META_AVATAR_LOCAL_IMAGE_ATTEMPTS','3'))
UPLOAD_LIMIT_BYTES =int (os.getenv ('META_AVATAR_UPLOAD_LIMIT_MB','15'))*1024 *1024
PIPELINE_VERSION ='ai-cartoon-v1'
FOREGROUND_RATIO =float (os.getenv ('META_AVATAR_FOREGROUND_RATIO','0.9'))
if not 0.5 <=FOREGROUND_RATIO <=1.0 :
    raise ValueError ('META_AVATAR_FOREGROUND_RATIO must be between 0.5 and 1.0.')
OPENAI_IMAGE_API_URL =os.getenv ('META_AVATAR_OPENAI_IMAGE_API_URL','https://api.openai.com/v1/images/generations')
OPENAI_IMAGE_MODEL =os.getenv ('META_AVATAR_OPENAI_IMAGE_MODEL','gpt-image-2')
OPENAI_IMAGE_SIZE =os.getenv ('META_AVATAR_OPENAI_IMAGE_SIZE','1024x1536')
OPENAI_IMAGE_QUALITY =os.getenv ('META_AVATAR_OPENAI_IMAGE_QUALITY','medium')
OPENAI_IMAGE_TIMEOUT_SECONDS =int (os.getenv ('META_AVATAR_OPENAI_IMAGE_TIMEOUT','300'))
OPENAI_IMAGE_ATTEMPTS =int (os.getenv ('META_AVATAR_OPENAI_IMAGE_ATTEMPTS','2'))
OPENAI_IMAGE_RESPONSE_LIMIT_BYTES =int (os.getenv ('META_AVATAR_OPENAI_IMAGE_RESPONSE_LIMIT_MB','30'))*1024 *1024
OLLAMA_IMAGE_API_URL =os.getenv ('META_AVATAR_OLLAMA_IMAGE_API_URL','http://127.0.0.1:11434/api/generate')
OLLAMA_IMAGE_MODEL =os.getenv ('META_AVATAR_OLLAMA_IMAGE_MODEL','x/flux2-klein:4b')
OLLAMA_IMAGE_SIZE =os.getenv ('META_AVATAR_OLLAMA_IMAGE_SIZE','768x1024')
OLLAMA_IMAGE_TIMEOUT_SECONDS =int (os.getenv ('META_AVATAR_OLLAMA_IMAGE_TIMEOUT','900'))
OLLAMA_IMAGE_STEPS =int (os.getenv ('META_AVATAR_OLLAMA_IMAGE_STEPS','4'))
OLLAMA_TEXT_API_URL =os.getenv ('META_AVATAR_OLLAMA_TEXT_API_URL',OLLAMA_IMAGE_API_URL )
OLLAMA_TEXT_MODEL =os.getenv ('META_AVATAR_OLLAMA_TEXT_MODEL','qwen3.5:4b')
BATCH_LIMIT =int (os.getenv ('META_AVATAR_BATCH_LIMIT','20'))
BUNDESTAG_URL =os.getenv ('META_AVATAR_BUNDESTAG_URL','https://www.bundestag.de/resource/blob/472878/MdB-Stammdaten.zip')
BUNDESTAG_PERIOD =int (os.getenv ('META_AVATAR_BUNDESTAG_PERIOD','21'))
BUNDESTAG_LIMIT_BYTES =int (os.getenv ('META_AVATAR_BUNDESTAG_LIMIT_MB','30'))*1024 *1024
if OPENAI_IMAGE_TIMEOUT_SECONDS <30 :
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_TIMEOUT must be at least 30.')
if OPENAI_IMAGE_ATTEMPTS <1 :
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_ATTEMPTS must be positive.')
if OPENAI_IMAGE_RESPONSE_LIMIT_BYTES <1024 *1024 :
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_RESPONSE_LIMIT_MB must be at least 1.')
if OPENAI_IMAGE_QUALITY not in {'low','medium','high','auto'}:
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_QUALITY must be low, medium, high, or auto.')
if not re.fullmatch ('\\d+x\\d+|auto',OPENAI_IMAGE_SIZE ):
    raise ValueError ('META_AVATAR_OPENAI_IMAGE_SIZE must be WIDTHxHEIGHT or auto.')
if not re.fullmatch ('\\d+x\\d+',OLLAMA_IMAGE_SIZE ):
    raise ValueError ('META_AVATAR_OLLAMA_IMAGE_SIZE must be WIDTHxHEIGHT.')
if OLLAMA_IMAGE_TIMEOUT_SECONDS <30 or BATCH_LIMIT <1 or BATCH_LIMIT >100 :
    raise ValueError ('Ollama timeout or batch limit is invalid.')
POSE_MODEL_PATH =Path (os.getenv ('META_AVATAR_POSE_MODEL',str (BASE_DIR /'models'/'pose_landmarker_lite.task'))).expanduser ()
MARCHING_CUBES_RESOLUTION =int (os.getenv ('META_AVATAR_MC_RESOLUTION','256'))
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
app =FastAPI (title ='Meta-Avatar AI Cartoon-to-3D API',version ='2.3.0',description ='Generates full-body cartoon references with GPT Image or Ollama and reconstructs them as GLB models.')
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
    notice :str =''

class CompareResponse (BaseModel ):
    name :str
    status :str
    message :str
    openai :AvatarResponse
    ollama :AvatarResponse

class PhotoCompareResponse (BaseModel ):
    name :str
    status :str
    message :str
    left :AvatarResponse
    right :AvatarResponse

class DialogueResponse (BaseModel ):
    status :Literal ['success','error']
    message :str
    left :str =''
    right :str =''
    model :str =''

class BatchInput (BaseModel ):
    names :list [str ]=[]
    provider :str ='openai'
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
    else :
        b4 =':'.join ((PIPELINE_VERSION ,OPENAI_IMAGE_MODEL ,OPENAI_IMAGE_SIZE ,OPENAI_IMAGE_QUALITY ,jieguo6.casefold ()))
    dongxi5 =hashlib.sha256 (b4.encode ('utf-8')).hexdigest ()[:10 ]
    tmp8 ='-ollama'if provider =='ollama'else ''
    return f'{tmp7}-{PIPELINE_VERSION}{tmp8}-{dongxi5}.glb'

def reference_image_filename (model_name :str )->str :
    if Path (model_name ).name !=model_name or not model_name.endswith ('.glb'):
        raise ValueError ('model_name must be a plain .glb filename')
    return f'{Path(model_name).stem}.reference.png'

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

def pose_is_front_full_body (landmarks :Any ,strict :bool =True )->bool :
    """Check for one upright person facing the camera, head to shoes, arms down.

    strict is for photos and GPT/Flux references. Stable Diffusion rarely
    draws a perfectly level A-pose, so its output gets looser limits that
    still rule out raised arms, crossed legs and side views.
    """
    if not isinstance (landmarks ,(list ,tuple ))or len (landmarks )<33 :
        return False
    (nose ,left_eye ,right_eye ,left_shoulder ,right_shoulder ,left_elbow ,right_elbow ,left_wrist ,right_wrist ,
     left_hip ,right_hip ,left_knee ,right_knee ,left_ankle ,right_ankle ,left_foot ,right_foot )=(
        landmarks [index ]for index in (0 ,2 ,5 ,11 ,12 ,13 ,14 ,15 ,16 ,23 ,24 ,25 ,26 ,27 ,28 ,31 ,32 ))
    required =(nose ,left_eye ,right_eye ,left_shoulder ,right_shoulder ,left_elbow ,right_elbow ,left_wrist ,right_wrist ,
               left_hip ,right_hip ,left_knee ,right_knee ,left_ankle ,right_ankle ,left_foot ,right_foot )
    if not all (_landmark_is_visible (point )for point in required ):
        return False
    body_height =max (left_foot.y ,right_foot.y ,left_ankle.y ,right_ankle.y )-nose.y
    if body_height <0.45 :
        return False
    shoulder_width =abs (left_shoulder.x -right_shoulder.x )
    hip_width =abs (left_hip.x -right_hip.x )
    if shoulder_width /body_height <0.12 or hip_width /body_height <0.07 :
        return False
    shoulder_centre =(left_shoulder.x +right_shoulder.x )*0.5
    if strict :
        eye_tilt ,shoulder_tilt ,hip_tilt =0.035 ,0.055 ,0.055
        nose_margin ,nose_offset =0.05 ,0.28
        knee_gap ,ankle_gap =0.3 ,0.4
    else :
        eye_tilt ,shoulder_tilt ,hip_tilt =0.09 ,0.14 ,0.14
        nose_margin ,nose_offset =0.1 ,0.75
        knee_gap ,ankle_gap =0.15 ,0.2
    if abs (left_eye.y -right_eye.y )>body_height *eye_tilt :
        return False
    if abs (left_shoulder.y -right_shoulder.y )>body_height *shoulder_tilt :
        return False
    if abs (left_hip.y -right_hip.y )>body_height *hip_tilt :
        return False
    if not min (left_shoulder.x ,right_shoulder.x )-nose_margin <=nose.x <=max (left_shoulder.x ,right_shoulder.x )+nose_margin :
        return False
    if abs (nose.x -shoulder_centre )>shoulder_width *nose_offset :
        return False
    if abs (left_knee.x -right_knee.x )<hip_width *knee_gap or abs (left_ankle.x -right_ankle.x )<hip_width *ankle_gap :
        return False
    if not strict :
        # Hands and elbows must not be lifted above the shoulders.
        if left_wrist.y <left_shoulder.y -body_height *0.12 or right_wrist.y <right_shoulder.y -body_height *0.12 :
            return False
        return left_elbow.y >=left_shoulder.y -body_height *0.08 and right_elbow.y >=right_shoulder.y -body_height *0.08
    # Strict: hands hang near the hips, elbows below the shoulders, and the
    # body is not turned, judged by the depth difference between both sides.
    wrist_limit =min (left_hip.y ,right_hip.y )-body_height *0.08
    if left_wrist.y <wrist_limit or right_wrist.y <wrist_limit :
        return False
    if left_elbow.y <left_shoulder.y -body_height *0.02 or right_elbow.y <right_shoulder.y -body_height *0.02 :
        return False
    if abs (left_shoulder.z -right_shoulder.z )>shoulder_width *0.45 :
        return False
    return abs (left_hip.z -right_hip.z )<=hip_width *0.6

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

def build_cartoon_reference_prompt (name :str )->str :
    return f'\nCreate one polished, stylized 3D cartoon character representing the public\npolitician named {name}. Preserve a recognizable but clearly illustrated\nlikeness based on their widely known public appearance. This must not look like\na photograph.\n\nComposition requirements for image-to-3D reconstruction:\n- exactly one person, centered, front-facing, and looking straight at the camera\n- full body visible from the top of the hair to the soles of both shoes\n- generous empty margin around the entire figure; nothing may touch the frame\n- neutral symmetrical A-pose: upright torso, arms lowered slightly away from the\n  body, elbows straight, hands and all fingers visible, legs straight, feet\n  parallel and shoulder-width apart\n- no crossed or overlapping limbs, no hand gestures, no props, no podium, no\n  furniture, no crowd, and no additional people\n- simple professional clothing associated with a parliament member, with clean\n  separated shapes and no logos, flags, badges, writing, or tiny patterns\n- detailed, clean facial features and hair; smooth animated-film character style\n- soft, even studio lighting, minimal ground shadow, solid light-gray background\n- no text, captions, borders, watermarks, split views, side views, or rear views\n\nUse a portrait canvas and make the character occupy about 82 percent of the\nimage height. Prioritize a clean silhouette and reconstruction-friendly geometry.\n'.strip ()

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

def _ollama_request (url :str ,body :dict [str ,Any ],limit :int ,what :str )->dict [str ,Any ]:
    request =UrlRequest (url ,data =json.dumps (body ).encode ('utf-8'),headers ={'Content-Type':'application/json','Accept':'application/json'},method ='POST')
    try :
        with urlopen (request ,timeout =OLLAMA_IMAGE_TIMEOUT_SECONDS ,context =_SSL_CONTEXT )as response :
            payload =response.read (limit +1 )
    except HTTPError as error :
        detail =''
        try :
            detail =str (json.loads (error.read (4096 ).decode ('utf-8','replace')).get ('error','')).strip ()
        except Exception :
            pass
        logger.warning ('Ollama %s request returned HTTP %s: %s',what ,error.code ,detail )
        if detail =='image generation models are not currently supported':
            raise AvatarImageConfigurationError ('This Ollama version cannot generate images. Use Ollama 0.32.5.')from error
        if 'not found'in detail :
            raise AvatarImageConfigurationError (f'Ollama does not have {body ["model"]} yet. Run: ollama pull {body ["model"]}')from error
        raise AvatarImageGenerationError (f'Ollama {what} error: {detail or error.code }')from error
    except (URLError ,TimeoutError ,OSError )as error :
        raise AvatarImageConfigurationError ('Ollama is not running. Start the Ollama app or run: ollama serve')from error
    if len (payload )>limit :
        raise AvatarImageGenerationError (f'The Ollama {what} response was too large.')
    try :
        return json.loads (payload )
    except json.JSONDecodeError as error :
        raise AvatarImageGenerationError (f'Ollama returned an invalid {what} response.')from error

def _call_ollama_image_api (prompt :str ,reference_png :bytes |None =None )->bytes :
    """Generate one image with Flux. With reference_png Flux redraws that picture."""
    width ,height =(int (part )for part in OLLAMA_IMAGE_SIZE.split ('x'))
    # keep_alive 0 unloads Flux straight away so TripoSR gets the memory back.
    body ={'model':OLLAMA_IMAGE_MODEL ,'prompt':prompt ,'width':width ,'height':height ,'steps':OLLAMA_IMAGE_STEPS ,'stream':False ,'keep_alive':0 }
    if reference_png :
        body ['images']=[base64.b64encode (reference_png ).decode ('ascii')]
    result =_ollama_request (OLLAMA_IMAGE_API_URL ,body ,OPENAI_IMAGE_RESPONSE_LIMIT_BYTES ,'image')
    try :
        image =base64.b64decode (result ['image'],validate =True )
    except (KeyError ,TypeError ,ValueError )as error :
        raise AvatarImageGenerationError ('Ollama returned no image.')from error
    if not image.startswith (b'\x89PNG\r\n\x1a\n'):
        raise AvatarImageGenerationError ('Ollama did not return a PNG image.')
    return image

def _call_ollama_text_api (prompt :str ,image_png :bytes |None =None ,json_mode :bool =False )->str :
    body ={'model':OLLAMA_TEXT_MODEL ,'prompt':prompt ,'stream':False ,'think':False ,'keep_alive':0 ,'options':{'temperature':0 }}
    if image_png :
        body ['images']=[base64.b64encode (image_png ).decode ('ascii')]
    if json_mode :
        body ['format']='json'
    text =_ollama_request (OLLAMA_TEXT_API_URL ,body ,2 *1024 *1024 ,'text').get ('response','')
    if not isinstance (text ,str )or not text.strip ():
        raise AvatarImageGenerationError ('Qwen returned an empty answer.')
    return re.sub ('<think>.*?</think>','',text ,flags =re.DOTALL ).strip ()

APPEARANCE_QUESTION ="""Look at the person in the image and answer in JSON. Only describe what is visible; never guess identity, age, ethnicity, health or opinions.
{"bald_on_top": is the top of the head bald or mostly bald? true or false,
 "hair_colour": colour of the visible hair, or "none",
 "hair_length": "none" | "short" | "medium" | "long",
 "glasses": true or false,
 "facial_hair": "none" | "stubble" | "moustache" | "beard",
 "jacket": colour word or "none",
 "shirt": colour word,
 "tie": colour word or "none",
 "trousers": colour word,
 "shoes": colour word}"""

def _clean_word (value :Any ,fallback :str ='')->str :
    """Keep a short colour or style word from the model and drop anything else."""
    text =re.sub ('[^a-zA-Z -]','',str (value or '')).strip ().lower ()
    return ' '.join (text.split ()[:3 ])or fallback

def describe_visible_appearance (photo_png :bytes )->dict [str ,Any ]:
    """Ask Qwen to fill a fixed form about what the photo shows.

    A small vision model is far more reliable answering fixed yes/no and
    colour questions than writing free text, and the code then turns the
    answers into a prompt it controls.
    """
    answer =_call_ollama_text_api (APPEARANCE_QUESTION ,photo_png ,json_mode =True )
    try :
        raw =json.loads (answer )
    except json.JSONDecodeError as error :
        raise AvatarImageGenerationError ('Qwen did not return valid JSON.')from error
    if not isinstance (raw ,dict ):
        raise AvatarImageGenerationError ('Qwen did not return a JSON object.')
    return {
    'bald_on_top':raw.get ('bald_on_top')is True ,
    'hair_colour':_clean_word (raw.get ('hair_colour'),'none'),
    'hair_length':_clean_word (raw.get ('hair_length'),'short'),
    'glasses':raw.get ('glasses')is True ,
    'facial_hair':_clean_word (raw.get ('facial_hair'),'none'),
    'jacket':_clean_word (raw.get ('jacket'),'none'),
    'shirt':_clean_word (raw.get ('shirt'),'white'),
    'tie':_clean_word (raw.get ('tie'),'none'),
    'trousers':_clean_word (raw.get ('trousers'),'dark'),
    'shoes':_clean_word (raw.get ('shoes'),'black'),
    }

def appearance_phrase (traits :dict [str ,Any ])->str :
    hair_colour =traits ['hair_colour']
    if traits ['bald_on_top']:
        hair ='bald on top'+(f' with short {hair_colour } hair on the sides'if hair_colour !='none'else '')
    elif traits ['hair_length']=='none':
        hair ='shaved head'
    else :
        hair =f'{traits ["hair_length"]} {hair_colour } hair'.replace (' none ',' ')
    parts =[hair ,'wearing glasses'if traits ['glasses']else 'no glasses']
    parts .append ('clean-shaven'if traits ['facial_hair']=='none'else traits ['facial_hair'])
    clothes =[]
    if traits ['jacket']!='none':
        clothes .append (f'{traits ["jacket"]} suit jacket')
    clothes .append (f'{traits ["shirt"]} shirt')
    if traits ['tie']!='none':
        clothes .append (f'{traits ["tie"]} tie')
    clothes +=[f'{traits ["trousers"]} trousers',f'{traits ["shoes"]} shoes']
    return ', '.join (parts )+', '+', '.join (clothes )

def build_flux_photo_prompt (traits :dict [str ,Any ]|None )->str :
    look =f' The person has: {appearance_phrase (traits )}.'if traits else ''
    return ('Redraw the person in the input image as a polished 3D animated-film cartoon character.'
            +look +
            ' Keep the same face and body shape. One person, full body from head to shoes, front view, '
            'neutral A-pose with both arms straight down, hands and shoes visible, plain light gray background.')

def _generated_reference_is_usable (image_bytes :bytes ,strict :bool =True )->bool :
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
        return pose_is_front_full_body (dongxi61 [0 ],strict )
    except Exception as shuju58 :
        logger.info ('Generated reference validation failed: %s',shuju58 )
        return False

def generate_cartoon_reference_image (name :str ,output_filename :str ,provider :str ='openai')->Path :
    tmpmeiyong =0
    for tmpx in range (1 ):
        tmpmeiyong +=tmpx
    if Path (output_filename ).name !=output_filename or not output_filename.endswith ('.png'):
        raise ValueError ('output_filename must be a plain .png filename')
    b67 =build_cartoon_reference_prompt (name )
    a66 :AvatarImageGenerationError |None =None
    tmp69 =OLLAMA_IMAGE_MODEL if provider =='ollama'else OPENAI_IMAGE_MODEL
    for jieguo62 in range (1 ,OPENAI_IMAGE_ATTEMPTS +1 ):
        logger.info ('Generating cartoon reference with %s (%d/%d)',tmp69 ,jieguo62 ,OPENAI_IMAGE_ATTEMPTS )
        try :
            shuju65 =_call_ollama_image_api (b67 )if provider =='ollama'else _call_openai_image_api (b67 )
        except AvatarImageConfigurationError :
            raise
        except AvatarImageGenerationError as tmp63 :
            a66 =tmp63
            if jieguo62 <OPENAI_IMAGE_ATTEMPTS :
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

def photo_model_filename (name :str ,photo_png :bytes ,provider :str ='local')->str :
    """Cache key for a photo avatar: same name, same photo, same settings, same file."""
    clean_name =normalize_name (name )
    slug =unicodedata.normalize ('NFKD',clean_name ).encode ('ascii','ignore').decode ('ascii')
    slug =re.sub ('[^a-zA-Z0-9]+','-',slug ).strip ('-').lower ()[:48 ]or 'avatar'
    if provider =='ollama':
        recipe =('ollama',OLLAMA_TEXT_MODEL ,OLLAMA_IMAGE_MODEL ,OLLAMA_IMAGE_SIZE ,str (OLLAMA_IMAGE_STEPS ))
    else :
        recipe =('local-sd',str (LOCAL_PHOTO_STRENGTH ))
    settings =':'.join ((PIPELINE_VERSION ,'photo',*recipe ,str (MARCHING_CUBES_RESOLUTION ),clean_name.casefold ()))
    digest =hashlib.sha256 (settings.encode ('utf-8')+b':'+photo_png ).hexdigest ()[:10 ]
    suffix ='-ollama'if provider =='ollama'else ''
    return f'{slug}-{PIPELINE_VERSION}-photo{suffix}-{digest}.glb'

def prepare_uploaded_photo (photo :bytes )->bytes :
    """Validate an uploaded photo and return it as PNG bytes."""
    if not photo :
        raise AvatarImageGenerationError ('Choose a PNG, JPG or WebP image first.')
    if len (photo )>UPLOAD_LIMIT_BYTES :
        raise AvatarImageGenerationError (f'The image is larger than {UPLOAD_LIMIT_BYTES //(1024 *1024 )} MB.')
    is_png =photo.startswith (b'\x89PNG\r\n\x1a\n')
    is_jpeg =photo.startswith (b'\xff\xd8\xff')
    is_webp =photo.startswith (b'RIFF')and photo [8 :12 ]==b'WEBP'
    if not (is_png or is_jpeg or is_webp ):
        raise AvatarImageGenerationError ('The file must be a PNG, JPG or WebP image.')
    try :
        decoded =_decode_image_bytes (photo )
    except Exception as error :
        raise AvatarImageGenerationError ('The image could not be read.')from error
    height ,width =decoded.shape [:2 ]
    if min (height ,width )<256 :
        raise AvatarImageGenerationError ('The image is too small. Use at least 256 pixels on each side.')
    if height *width >16_000_000 :
        raise AvatarImageGenerationError ('The image has too many pixels. Use 16 megapixels or less.')
    if height <width *1.05 :
        raise AvatarImageGenerationError ('Use a portrait image that shows the whole person.')
    poses =_detect_pose_landmarks (decoded )
    if len (poses )!=1 or not pose_is_front_full_body (poses [0 ]):
        raise AvatarImageGenerationError ('Use a photo of one person facing the camera, head to shoes, arms hanging down, hands and feet visible.')
    import cv2
    encoded ,png =cv2.imencode ('.png',decoded )
    if not encoded :
        raise AvatarImageGenerationError ('The image could not be converted to PNG.')
    return png.tobytes ()

def build_photo_cartoon_prompt (name :str ,traits :dict [str ,Any ]|None =None )->str :
    return (f'3D cartoon version of the same person in the input image, {name}, keep the same face, hair, clothes '
            'and body shape, one full body, front view, neutral A pose, both arms down, hands and shoes visible, '
            'clean detailed face, plain light gray background'+(', '+appearance_phrase (traits )if traits else ''))

def generate_photo_cartoon (name :str ,photo_png :bytes ,output_filename :str ,traits :dict [str ,Any ]|None =None )->Path :
    """Turn the photo into a cartoon reference, retrying until the pose check passes."""
    if Path (output_filename ).name !=output_filename or not output_filename.endswith ('.png'):
        raise ValueError ('output_filename must be a plain .png filename')
    MODEL_DIR.mkdir (parents =True ,exist_ok =True )
    photo_path =MODEL_DIR /f'.photo-{uuid4().hex}.png'
    photo_path.write_bytes (photo_png )
    base_seed =int (hashlib.sha256 (photo_png ).hexdigest ()[:8 ],16 )
    last_error :Exception |None =None
    try :
        for attempt in range (1 ,LOCAL_IMAGE_ATTEMPTS +1 ):
            candidate =MODEL_DIR /f'.photo-cartoon-{uuid4().hex}.png'
            try :
                logger.info ('Turning uploaded photo into a cartoon (%d/%d)',attempt ,LOCAL_IMAGE_ATTEMPTS )
                run_photo_cartoon (photo_path ,candidate ,build_photo_cartoon_prompt (name ,traits ),models_dir =LOCAL_MODELS_DIR ,device =LOCAL_IMAGE_DEVICE ,strength =LOCAL_PHOTO_STRENGTH ,seed =base_seed +attempt )
                if _generated_reference_is_usable (candidate.read_bytes (),strict =False ):
                    final_path =MODEL_DIR /output_filename
                    candidate.replace (final_path )
                    return final_path
                last_error =AvatarImageGenerationError ('The cartoon lost the front full-body pose. Try a photo with a plainer background.')
            except ResultFlagged :
                logger.info ('Safety checker rejected cartoon attempt %d, trying another seed',attempt )
                last_error =AvatarImageGenerationError ('The image model kept flagging the cartoon. Try another photo.')
            except LocalWorkerError as error :
                # Missing models or memory problems will not fix themselves on a retry.
                raise AvatarImageGenerationError (str (error ))from error
            finally :
                candidate.unlink (missing_ok =True )
        raise AvatarImageGenerationError (str (last_error ))
    finally :
        photo_path.unlink (missing_ok =True )

def generate_ollama_photo_cartoon (name :str ,photo_png :bytes ,output_filename :str )->tuple [Path ,str ,str ]:
    """Qwen reads the photo, Flux redraws it. Returns (image, model used, notice).

    When Flux cannot run (Ollama missing, wrong version, model not pulled)
    local Stable Diffusion takes over, and the notice says so, so the user
    always knows which model made the picture.
    """
    if Path (output_filename ).name !=output_filename or not output_filename.endswith ('.png'):
        raise ValueError ('output_filename must be a plain .png filename')
    traits :dict [str ,Any ]|None =None
    try :
        traits =describe_visible_appearance (photo_png )
        logger.info ('Qwen sees: %s',appearance_phrase (traits ))
    except (AvatarImageConfigurationError ,AvatarImageGenerationError )as error :
        logger.warning ('Qwen could not describe the photo: %s',error )
    prompt =build_flux_photo_prompt (traits )
    last_error :Exception |None =None
    for attempt in range (1 ,LOCAL_IMAGE_ATTEMPTS +1 ):
        logger.info ('Redrawing uploaded photo with %s (%d/%d)',OLLAMA_IMAGE_MODEL ,attempt ,LOCAL_IMAGE_ATTEMPTS )
        try :
            cartoon =_call_ollama_image_api (prompt ,photo_png )
        except AvatarImageConfigurationError as error :
            logger.warning ('Flux is not available, using local Stable Diffusion: %s',error )
            path =generate_photo_cartoon (name ,photo_png ,output_filename ,traits )
            return path ,'Stable Diffusion 1.5 img2img',f'Flux was not available, so local Stable Diffusion made the cartoon. Reason: {error }'
        except AvatarImageGenerationError as error :
            last_error =error
            continue
        if not _generated_reference_is_usable (cartoon ,strict =False ):
            last_error =AvatarImageGenerationError ('Flux lost the front full-body pose. Try a photo with a plainer background.')
            continue
        final_path =MODEL_DIR /output_filename
        temporary =MODEL_DIR /f'.{output_filename}.{uuid4().hex}.tmp'
        temporary.write_bytes (cartoon )
        temporary.replace (final_path )
        model =f'{OLLAMA_TEXT_MODEL} + {OLLAMA_IMAGE_MODEL}'if traits else OLLAMA_IMAGE_MODEL
        notice ='' if traits else 'Qwen could not read the photo, so Flux worked from the image alone.'
        return final_path ,model ,notice
    raise AvatarImageGenerationError (str (last_error )if last_error else 'Flux could not redraw the photo.')

def generate_3d_local (reference_image_path :Path ,output_filename :str )->Path :
    if Path (output_filename ).name !=output_filename or not output_filename.endswith ('.glb'):
        raise ValueError ('output_filename must be a plain .glb filename')
    reference_image_path =Path (reference_image_path )
    if not reference_image_path.is_file ():
        raise AvatarGenerationError ('The generated reference image is missing.')
    logger.info ('Running local TripoSR on %s at resolution %d',LOCAL_3D_DEVICE ,MARCHING_CUBES_RESOLUTION )
    MODEL_DIR.mkdir (parents =True ,exist_ok =True )
    job =uuid4 ().hex
    raw_model =MODEL_DIR /f'.{output_filename}.{job}.raw.glb'
    processed_image =MODEL_DIR /f'.{output_filename}.{job}.processed.png'
    textured_model =MODEL_DIR /f'.{output_filename}.{job}.tmp'
    try :
        run_triposr (reference_image_path ,raw_model ,processed_image ,models_dir =LOCAL_MODELS_DIR ,resolution =MARCHING_CUBES_RESOLUTION ,foreground_ratio =FOREGROUND_RATIO ,device =LOCAL_3D_DEVICE )
        bake_front_projection_texture (raw_model ,processed_image ,textured_model )
        if textured_model.stat ().st_size ==0 :
            raise AvatarGenerationError ('The texture baker returned an empty model.')
        final_model =MODEL_DIR /output_filename
        textured_model.replace (final_model )
        return final_model
    except LocalWorkerError as error :
        raise AvatarGenerationError (str (error ))from error
    except AvatarGenerationError :
        raise
    except Exception as error :
        raise AvatarGenerationError ('The local 3D reconstruction failed.')from error
    finally :
        for leftover in (raw_model ,processed_image ,textured_model ):
            leftover.unlink (missing_ok =True )

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
    tmp220 =OLLAMA_IMAGE_MODEL if provider =='ollama'else OPENAI_IMAGE_MODEL
    return AvatarResponse (name =name ,status ='success',message ='Model loaded from cache.'if cached else 'Model generated successfully.',model_url =build_asset_url (request ,filename ),reference_image_url =build_asset_url (request ,shuju219 )if a220.is_file ()and a220.stat ().st_size >0 else '',cached =cached ,provider =provider ,image_model =tmp220 )

def _provider (provider :str )->str :
    tmp221 =provider.strip ().lower ()
    if tmp221 not in {'openai','ollama'}:
        raise HTTPException (status_code =422 ,detail ='provider must be openai or ollama')
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
    tmp224 =OLLAMA_IMAGE_MODEL if tmp223 =='ollama'else OPENAI_IMAGE_MODEL
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
            if tmp223 =='ollama':tmp226 =str (b221 )
            elif 'OPENAI_API_KEY'in str (b221 ):tmp226 ='Set OPENAI_API_KEY before starting the backend.'
            else :tmp226 ='OpenAI TLS certificate verification failed.'
            return AvatarResponse (name =linshi225 ,status ='error',message =tmp226 ,provider =tmp223 ,image_model =tmp224 )
        except AvatarImageGenerationError as tmp225 :
            logger.exception ('AI reference generation failed for %s with %s',linshi225 ,tmp223 )
            return AvatarResponse (name =linshi225 ,status ='error',message =str (tmp225 ),provider =tmp223 ,image_model =tmp224 )
        except AvatarGenerationError as reconstruction_error :
            logger.exception ('3D reconstruction failed for %s',linshi225 )
            return AvatarResponse (name =linshi225 ,status ='error',message =str (reconstruction_error ),provider =tmp223 ,image_model =tmp224 )
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
def create_avatar (request :Request ,name :str =Query (min_length =1 ,max_length =100 ),force :bool =Query (default =False ),provider :str =Query (default ='openai'))->AvatarResponse :
    tmpmeiyong =0
    for tmpx in range (1 ):
        tmpmeiyong +=tmpx
    return _create_avatar (request ,name ,force ,provider )

async def _read_upload (image :UploadFile )->bytes :
    try :
        return await image.read (UPLOAD_LIMIT_BYTES +1 )
    finally :
        await image.close ()

def _create_photo_avatar (request :Request ,clean_name :str ,photo_png :bytes ,provider :str ,force :bool )->AvatarResponse :
    label ='photo-ollama'if provider =='ollama'else 'photo'
    image_model =f'{OLLAMA_TEXT_MODEL} + {OLLAMA_IMAGE_MODEL}'if provider =='ollama'else 'Stable Diffusion 1.5 img2img'
    filename =photo_model_filename (clean_name ,photo_png ,provider )
    model_path =MODEL_DIR /filename
    reference_path =MODEL_DIR /reference_image_filename (filename )
    notice =''
    with _generation_lock (filename ):
        cached =not force and model_path.is_file ()and model_path.stat ().st_size >0 and reference_path.is_file ()
        if cached :
            logger.info ('Serving cached %s avatar for %s',label ,clean_name )
        else :
            try :
                if provider =='ollama':
                    _ ,image_model ,notice =generate_ollama_photo_cartoon (clean_name ,photo_png ,reference_path.name )
                else :
                    generate_photo_cartoon (clean_name ,photo_png ,reference_path.name )
                generate_3d_local (reference_path ,filename )
            except (AvatarImageGenerationError ,AvatarGenerationError )as error :
                logger.exception ('Photo avatar failed for %s with %s',clean_name ,provider )
                return AvatarResponse (name =clean_name ,status ='error',message =str (error ),provider =label ,image_model =image_model )
    response =successful_response (request ,clean_name ,filename ,cached ,label )
    return response.model_copy (update ={'image_model':image_model ,'notice':notice })

@app.post ('/api/avatar-from-image',response_model =AvatarResponse )
async def avatar_from_image (request :Request ,name :str =Form (min_length =1 ,max_length =100 ),image :UploadFile =File (),force :bool =Form (default =False ),provider :str =Form (default ='local'))->AvatarResponse :
    clean_name =_valid_name (name )
    provider =provider.strip ().lower ()
    if provider not in {'local','ollama'}:
        await image.close ()
        raise HTTPException (status_code =422 ,detail ='provider must be local or ollama')
    try :
        photo_png =prepare_uploaded_photo (await _read_upload (image ))
    except AvatarImageGenerationError as error :
        return AvatarResponse (name =clean_name ,status ='error',message =str (error ),provider ='photo')
    return _create_photo_avatar (request ,clean_name ,photo_png ,provider ,force )

@app.post ('/api/compare-photo',response_model =PhotoCompareResponse )
async def compare_photo (request :Request ,name :str =Form (min_length =1 ,max_length =100 ),image :UploadFile =File (),force :bool =Form (default =False ))->PhotoCompareResponse :
    """Same photo, two pipelines: local Stable Diffusion on the left, Qwen + Flux on the right.

    The two run one after the other; Stable Diffusion and Flux together do
    not fit in 16 GB next to Unity.
    """
    clean_name =_valid_name (name )
    try :
        photo_png =prepare_uploaded_photo (await _read_upload (image ))
    except AvatarImageGenerationError as error :
        failed =AvatarResponse (name =clean_name ,status ='error',message =str (error ))
        return PhotoCompareResponse (name =clean_name ,status ='error',message =str (error ),left =failed ,right =failed )
    left =_create_photo_avatar (request ,clean_name ,photo_png ,'local',force )
    right =_create_photo_avatar (request ,clean_name ,photo_png ,'ollama',force )
    both =left.status =='success'and right.status =='success'
    return PhotoCompareResponse (name =clean_name ,status ='success'if both else 'error',message ='Both models are ready.'if both else 'One or both models failed. Check the two result messages.',left =left ,right =right )

DIALOGUE_PROMPT ="""Two cartoon avatars stand side by side in a VR demo scene. The demo topic is: {topic}.
Write one short, friendly first-person English line for each avatar, at most 140 characters each.
They may welcome the audience, name the topic, say what the scene will be about, or mention their own cartoon look.
They must not state any political opinion, claim, promise or quote, and must not speak as a real person.
Return JSON: {{"left": "...", "right": "..."}}"""

@app.get ('/api/dialogue',response_model =DialogueResponse )
def dialogue (topic :str =Query (default ='German parliament and public policy',min_length =1 ,max_length =200 ))->DialogueResponse :
    """Two speech bubble lines for the comparison view, written by the local Qwen.

    The avatars look like real politicians, so the lines are kept to
    welcoming the audience and naming the topic. Qwen is told never to
    voice an opinion or quote anyone.
    """
    topic =' '.join (topic.split ())
    try :
        answer =json.loads (_call_ollama_text_api (DIALOGUE_PROMPT.format (topic =topic ),json_mode =True ))
        left =' '.join (str (answer ['left']).split ())[:180 ]
        right =' '.join (str (answer ['right']).split ())[:180 ]
        if not left or not right :
            raise ValueError ('empty line')
    except (AvatarImageConfigurationError ,AvatarImageGenerationError )as error :
        return DialogueResponse (status ='error',message =str (error ),model =OLLAMA_TEXT_MODEL )
    except (KeyError ,TypeError ,ValueError ,json.JSONDecodeError ):
        return DialogueResponse (status ='error',message ='Qwen did not return two lines. Try again.',model =OLLAMA_TEXT_MODEL )
    return DialogueResponse (status ='success',message ='Dialogue ready.',left =left ,right =right ,model =OLLAMA_TEXT_MODEL )

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
    return {'annotator_name':'meta-avatar-duui','version':'2.3.0','implementation_lang':'Python','meta':{'models':[OPENAI_IMAGE_MODEL,OLLAMA_IMAGE_MODEL,OLLAMA_TEXT_MODEL],'reconstruction':'TripoSR (local)' },'parameters':{'name':'Politician name. The document text is used when empty.','force':'Regenerate cached output.','include_binary':'Store Base64 GLB and PNG data in the CAS.'}}

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
    tmp231=_create_avatar(request,tmp230,data.force,'openai')
    tmp232=TmpOutput(**tmp231.model_dump())
    if tmp231.status=='success'and data.include_binary:
        tmp233=MODEL_DIR/model_filename(tmp230)
        tmp234=MODEL_DIR/reference_image_filename(tmp233.name)
        if tmp233.is_file():tmp232.model_data=base64.b64encode(tmp233.read_bytes()).decode('ascii')
        if tmp234.is_file():tmp232.reference_image_data=base64.b64encode(tmp234.read_bytes()).decode('ascii')
    return tmp232
if __name__ =='__main__':
    uvicorn.run (app ,host =os.getenv ('META_AVATAR_HOST','127.0.0.1'),port =int (os.getenv ('META_AVATAR_PORT','8000')))
