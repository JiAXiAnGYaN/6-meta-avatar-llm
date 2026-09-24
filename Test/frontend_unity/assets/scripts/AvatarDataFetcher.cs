using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using GLTFast;
using GLTFast.Logging;
using TMPro;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
[Serializable]
public class Data{
 public string name;
 public string status;
 public string message;
 public string model_url;
 public string reference_image_url;
 public bool cached;
 public string provider;
 public string image_model;
}
[Serializable]
public class CompareData{
 public string name;
 public string status;
 public string message;
 public Data openai;
 public Data ollama;
}
[Serializable]
public class MembersData{
 public int period;
 public int total;
 public int start;
 public string[] names;
}
public class AvatarDataFetcher:MonoBehaviour{
 public TMP_InputField nameInput;
 public TextMeshProUGUI statusText;
 public string backendUrl="http://127.0.0.1:8000/api/avatar";
 public int timeout=1800;
 public Transform spawnPoint;
 public AvatarOrbitCamera orbitCamera;
 GameObject tmp1;
 GltfImport tmp2;
 bool tmp3;
 bool tmp4;
 GameObject tmp20;
 GltfImport tmp21;
 Camera tmp22;
 int tmp23=-1;
 GameObject tmp40;
 bool walking;
 TMP_InputField photoPathInput;
 const long PhotoLimitBytes=15L*1024*1024;
 bool tmp41;
 bool tmp42;
 string[] tmp43=Array.Empty<string>();
 bool[] tmp44=Array.Empty<bool>();
 Vector2 tmp45;
 string tmp46="";
 bool tmp47;
 int tmp48;
 bool tmp49;
 bool tmp50;
 int tmp51;
 void Start(){
  int tmp99=0;for(int j=0;j<1;j++){tmp99+=j;}
  Button tmp24=FindAnyObjectByType<Button>();
  if(tmp24!=null){
   makeButton(tmp24,"CompareButton","Compare GPT / Ollama",new Vector2(460,-20),new Vector2(210,44),Compare);
   makeButton(tmp24,"BatchButton","Choose German MPs",new Vector2(680,-20),new Vector2(250,44),Batch);
   makeButton(tmp24,"BrowsePhotoButton","Browse",new Vector2(560,-74),new Vector2(110,44),BrowsePhoto);
   makeButton(tmp24,"PhotoButton","Photo to 3D",new Vector2(680,-74),new Vector2(250,44),PhotoTo3D);
   makeButton(tmp24,"PlainButton","Plain",new Vector2(20,-128),new Vector2(130,38),()=>scene(0));
   makeButton(tmp24,"ParliamentButton","Parliament Speech",new Vector2(160,-128),new Vector2(190,38),()=>scene(1));
   makeButton(tmp24,"PressButton","Press Room",new Vector2(360,-128),new Vector2(150,38),()=>scene(2));
   makeButton(tmp24,"ElectionButton","Election Stage",new Vector2(520,-128),new Vector2(170,38),()=>scene(3));
   makeButton(tmp24,"WalkButton","Walk",new Vector2(700,-128),new Vector2(110,38),walk);
  }
  if(nameInput!=null&&nameInput.placeholder is TMP_Text tmp25)tmp25.text="One name, or MP names separated by commas...";
  if(nameInput!=null){
   // A second copy of the name field holds the photo path, so it looks the same.
   photoPathInput=Instantiate(nameInput,nameInput.transform.parent);photoPathInput.name="PhotoPathInput";photoPathInput.text="";
   RectTransform photoRect=photoPathInput.GetComponent<RectTransform>();photoRect.anchoredPosition=new Vector2(20,-74);photoRect.sizeDelta=new Vector2(530,44);
   if(photoPathInput.placeholder is TMP_Text photoHint)photoHint.text="Front full-body photo (PNG, JPG or WebP)...";
  }
  if(statusText!=null){RectTransform tmp37=statusText.GetComponent<RectTransform>();tmp37.anchoredPosition=new Vector2(20,-178);tmp37.sizeDelta=new Vector2(920,42);statusText.fontSize=20;}
  scene(0);
 }
 void makeButton(Button tmp24,string tmp25,string tmp26,Vector2 tmp27,Vector2 tmp28,UnityEngine.Events.UnityAction tmp29){
  GameObject tmp30=new GameObject(tmp25,typeof(RectTransform),typeof(CanvasRenderer),typeof(Image),typeof(Button));
  tmp30.transform.SetParent(tmp24.transform.parent,false);
  RectTransform tmp31=tmp30.GetComponent<RectTransform>();
  tmp31.anchorMin=new Vector2(0,1);tmp31.anchorMax=new Vector2(0,1);tmp31.pivot=new Vector2(0,1);tmp31.anchoredPosition=tmp27;tmp31.sizeDelta=tmp28;
  Image tmp32=tmp30.GetComponent<Image>();tmp32.sprite=tmp24.GetComponent<Image>().sprite;tmp32.type=Image.Type.Sliced;
  Button tmp33=tmp30.GetComponent<Button>();tmp33.targetGraphic=tmp32;tmp33.onClick.AddListener(tmp29);
  GameObject tmp34=new GameObject("Text (TMP)",typeof(RectTransform),typeof(CanvasRenderer),typeof(TextMeshProUGUI));
  tmp34.transform.SetParent(tmp30.transform,false);
  RectTransform tmp35=tmp34.GetComponent<RectTransform>();tmp35.anchorMin=Vector2.zero;tmp35.anchorMax=Vector2.one;tmp35.sizeDelta=Vector2.zero;
  TextMeshProUGUI tmp36=tmp34.GetComponent<TextMeshProUGUI>();tmp36.text=tmp26;tmp36.fontSize=17;tmp36.alignment=TextAlignmentOptions.Center;tmp36.color=new Color(.2f,.2f,.2f,1);
  if(statusText!=null)tmp36.font=statusText.font;
 }
 public void Generate(){
  int tmp99=0;for(int j=0;j<1;j++){tmp99+=j;}
  if(tmp3){update("A model is already being generated. Please wait.");return;}
  if(nameInput==null||statusText==null){Debug.LogError("UI is missing.");return;}
  string name=nameInput.text.Trim();
  if(string.IsNullOrWhiteSpace(name)){update("Please enter a politician's full name.");return;}
  if(name.IndexOfAny(new[]{',',';','\n','\r'})>=0){update("Use Generate MP List when you enter several names.");return;}
  string tmp5=backendUrl.TrimEnd('/');
  if(!good(tmp5)){update("Please configure a valid HTTP backend URL.");return;}
  StartCoroutine(create(name,tmp5));
 }
 public void Compare(){
  if(tmp3){update("A model is already being generated. Please wait.");return;}
  if(nameInput==null||statusText==null){Debug.LogError("UI is missing.");return;}
  string tmp5=nameInput.text.Trim();
  if(string.IsNullOrWhiteSpace(tmp5)||tmp5.IndexOfAny(new[]{',',';','\n','\r'})>=0){update("Enter one politician name for comparison.");return;}
  string tmp6=backendUrl.TrimEnd('/');
  if(!good(tmp6)){update("Please configure a valid HTTP backend URL.");return;}
  StartCoroutine(compare(tmp5,root(tmp6)));
 }
 public void Batch(){
  if(tmp3){update("A model is already being generated. Please wait.");return;}
  if(nameInput==null||statusText==null){Debug.LogError("UI is missing.");return;}
  string tmp9=backendUrl.TrimEnd('/');
  if(!good(tmp9)){update("Please configure a valid HTTP backend URL.");return;}
  tmp41=true;tmp47=false;
  if(tmp43.Length==0&&!tmp42)StartCoroutine(members(root(tmp9)));
  else chooseTyped();
 }
 public void BrowsePhoto(){
#if UNITY_EDITOR
  string path=UnityEditor.EditorUtility.OpenFilePanelWithFilters("Choose a front full-body photo","",new[]{"Images","png,jpg,jpeg,webp"});
  if(!string.IsNullOrEmpty(path)&&photoPathInput!=null)photoPathInput.text=path;
#else
  update("Paste the full path of the photo into the photo field.");
#endif
 }
 public void PhotoTo3D(){
  if(tmp3){update("A model is already being generated. Please wait.");return;}
  if(nameInput==null||photoPathInput==null||statusText==null){Debug.LogError("Photo UI is missing.");return;}
  string name=nameInput.text.Trim();
  string path=photoPathInput.text.Trim().Trim('"');
  if(string.IsNullOrWhiteSpace(name)||name.IndexOfAny(new[]{',',';','\n','\r'})>=0){update("Enter one name for the person in the photo.");return;}
  if(string.IsNullOrWhiteSpace(path)||!File.Exists(path)){update("Choose an existing photo first.");return;}
  string extension=Path.GetExtension(path).ToLowerInvariant();
  if(extension!=".png"&&extension!=".jpg"&&extension!=".jpeg"&&extension!=".webp"){update("Choose a PNG, JPG or WebP photo.");return;}
  if(new FileInfo(path).Length>PhotoLimitBytes){update("The photo must be 15 MB or smaller.");return;}
  string server=root(backendUrl.TrimEnd('/'));
  if(!good(server)){update("Please configure a valid HTTP backend URL.");return;}
  StartCoroutine(createFromPhoto(name,path,server));
 }
 IEnumerator createFromPhoto(string name,string path,string server){
  tmp3=true;update("Turning the photo into a cartoon, then reconstructing the 3D model...");
  byte[] photo;
  try{photo=File.ReadAllBytes(path);}
  catch(Exception e){update("The photo could not be read.");Debug.LogException(e);tmp3=false;yield break;}
  string extension=Path.GetExtension(path).ToLowerInvariant();
  string mime=extension==".png"?"image/png":extension==".webp"?"image/webp":"image/jpeg";
  List<IMultipartFormSection> form=new List<IMultipartFormSection>{
   new MultipartFormDataSection("name",name),
   new MultipartFormFileSection("image",photo,Path.GetFileName(path),mime)
  };
  using(UnityWebRequest request=UnityWebRequest.Post(server+"/api/avatar-from-image",form)){
   request.timeout=timeout;yield return request.SendWebRequest();
   if(request.result!=UnityWebRequest.Result.Success){
    update($"Backend request failed (HTTP {request.responseCode}).");Debug.LogError(request.downloadHandler.text);tmp3=false;yield break;
   }
   Data result;
   try{result=JsonUtility.FromJson<Data>(request.downloadHandler.text);}
   catch(Exception e){update("The backend returned an invalid response.");Debug.LogException(e);tmp3=false;yield break;}
   if(result==null||result.status!="success"){update(string.IsNullOrWhiteSpace(result?.message)?"Photo avatar failed.":result.message);tmp3=false;yield break;}
   if(!Uri.TryCreate(result.model_url,UriKind.Absolute,out Uri modelUrl)){update("The backend returned an invalid model URL.");tmp3=false;yield break;}
   update(result.cached?"Using the cached photo model...":"Photo model generated. Loading it into the scene...");_=load(modelUrl.ToString());
  }
 }
 bool good(string tmp5){return Uri.TryCreate(tmp5,UriKind.Absolute,out Uri tmp6)&&(tmp6.Scheme==Uri.UriSchemeHttp||tmp6.Scheme==Uri.UriSchemeHttps);}
 string root(string tmp5){int tmp6=tmp5.IndexOf("/api/",StringComparison.OrdinalIgnoreCase);return tmp6>=0?tmp5.Substring(0,tmp6):tmp5;}
 IEnumerator create(string name,string tmp5){
  tmp3=true;update("Generating a full-body cartoon reference, then reconstructing the 3D model...");
  string url=$"{tmp5}?name={UnityWebRequest.EscapeURL(name)}";
  using(UnityWebRequest request=UnityWebRequest.Get(url)){
   request.timeout=timeout;yield return request.SendWebRequest();
   if(request.result!=UnityWebRequest.Result.Success){
    string detail=string.IsNullOrWhiteSpace(request.downloadHandler.text)?request.error:request.downloadHandler.text;
    update($"Backend request failed (HTTP {request.responseCode}).");Debug.LogError(detail);tmp3=false;yield break;
   }
   Data tmp8;
   try{tmp8=JsonUtility.FromJson<Data>(request.downloadHandler.text);}
   catch(Exception e){update("The backend returned an invalid response.");Debug.LogException(e);tmp3=false;yield break;}
   if(tmp8==null||tmp8.status!="success"){update(string.IsNullOrWhiteSpace(tmp8?.message)?"Avatar generation failed.":tmp8.message);tmp3=false;yield break;}
   if(string.IsNullOrWhiteSpace(tmp8.model_url)||!Uri.TryCreate(tmp8.model_url,UriKind.Absolute,out Uri tmp7)){update("The backend returned an invalid model URL.");tmp3=false;yield break;}
   update(tmp8.cached?"Using the cached model...":"3D model generated. Loading it into the scene...");_=load(tmp7.ToString());
  }
 }
 IEnumerator compare(string name,string tmp5){
  tmp3=true;update("GPT Image and Ollama are generating two models at the same time...");
  string tmp6=tmp5+"/api/compare?name="+UnityWebRequest.EscapeURL(name);
  using(UnityWebRequest tmp7=UnityWebRequest.Get(tmp6)){
   tmp7.timeout=timeout;yield return tmp7.SendWebRequest();
   if(tmp7.result!=UnityWebRequest.Result.Success){update("Comparison request failed.");Debug.LogError(tmp7.downloadHandler.text);tmp3=false;yield break;}
   CompareData tmp8;
   try{tmp8=JsonUtility.FromJson<CompareData>(tmp7.downloadHandler.text);}
   catch(Exception e){update("The backend returned an invalid comparison response.");Debug.LogException(e);tmp3=false;yield break;}
   if(tmp8==null||tmp8.status!="success"){
    string tmp9=tmp8?.openai?.message??"OpenAI failed";string tmp10=tmp8?.ollama?.message??"Ollama failed";
    update("GPT: "+tmp9+" Ollama: "+tmp10);tmp3=false;yield break;
   }
   update("Both 3D models are ready. Loading the split screen...");_=load2(tmp8.openai.model_url,tmp8.ollama.model_url,tmp8.openai.image_model,tmp8.ollama.image_model);
  }
 }
 IEnumerator batch(List<string> tmp5,string tmp6){
  tmp3=true;tmp49=true;tmp50=false;int tmp7=0;int tmp8=0;int tmp12=0;
  for(int i=0;i<tmp5.Count;i++){
   if(tmp50)break;
   update($"German MP batch {i+1}/{tmp5.Count}: {tmp5[i]}");string tmp9=$"{tmp6}?name={UnityWebRequest.EscapeURL(tmp5[i])}";
   using(UnityWebRequest tmp10=UnityWebRequest.Get(tmp9)){
    tmp10.timeout=timeout;yield return tmp10.SendWebRequest();
    tmp12++;if(tmp10.result!=UnityWebRequest.Result.Success){tmp8++;Debug.LogError(tmp10.downloadHandler.text);continue;}
    try{Data tmp11=JsonUtility.FromJson<Data>(tmp10.downloadHandler.text);if(tmp11!=null&&tmp11.status=="success")tmp7++;else tmp8++;}
    catch(Exception e){tmp8++;Debug.LogException(e);}
   }
  }
  if(tmp50)update($"Batch stopped after {tmp12}/{tmp5.Count}: {tmp7} succeeded and {tmp8} failed.");
  else update($"German MP batch finished: {tmp7} succeeded, {tmp8} failed. The GLB files are saved by the backend.");
  tmp3=false;tmp49=false;tmp50=false;
 }
 IEnumerator members(string tmp5){
  tmp42=true;update("Loading the official German Bundestag member list...");
  using(UnityWebRequest tmp6=UnityWebRequest.Get(tmp5+"/api/german-members?start=0&limit=1000")){
   tmp6.timeout=90;yield return tmp6.SendWebRequest();
   if(tmp6.result!=UnityWebRequest.Result.Success){update("The German MP list could not be loaded.");Debug.LogError(tmp6.downloadHandler.text);tmp41=false;tmp42=false;yield break;}
   try{
    MembersData tmp7=JsonUtility.FromJson<MembersData>(tmp6.downloadHandler.text);
    if(tmp7==null||tmp7.names==null||tmp7.names.Length==0)throw new Exception("Empty MP list");
    tmp43=tmp7.names;tmp44=new bool[tmp43.Length];tmp48=tmp7.period;chooseTyped();update($"Loaded {tmp43.Length} German MPs. Choose some names or generate all.");
   }catch(Exception e){update("The German MP list response was invalid.");Debug.LogException(e);tmp41=false;}
  }
  tmp42=false;
 }
 void chooseTyped(){
  if(nameInput==null||string.IsNullOrWhiteSpace(nameInput.text)||tmp43.Length==0)return;
  for(int i=0;i<tmp44.Length;i++)tmp44[i]=false;
  string[] tmp5=nameInput.text.Split(new[]{',',';','\n','\r'},StringSplitOptions.RemoveEmptyEntries);
  foreach(string tmp6 in tmp5){string tmp7=tmp6.Trim();for(int i=0;i<tmp43.Length;i++)if(string.Equals(tmp43[i],tmp7,StringComparison.OrdinalIgnoreCase))tmp44[i]=true;}
 }
 int picked(){int tmp5=0;for(int i=0;i<tmp44.Length;i++)if(tmp44[i])tmp5++;return tmp5;}
 bool showName(string tmp5){return string.IsNullOrWhiteSpace(tmp46)||tmp5.IndexOf(tmp46,StringComparison.OrdinalIgnoreCase)>=0;}
 void selected(){
  List<string> tmp5=new List<string>();for(int i=0;i<tmp43.Length;i++)if(tmp44[i])tmp5.Add(tmp43[i]);
  if(tmp5.Count==0){update("Choose at least one German MP.");return;}
  tmp41=false;StartCoroutine(batch(tmp5,backendUrl.TrimEnd('/')));
 }
 void all(){tmp47=false;tmp41=false;StartCoroutine(batch(new List<string>(tmp43),backendUrl.TrimEnd('/')));}
 void OnGUI(){
  if(tmp49&&GUI.Button(new Rect(Screen.width-170,Screen.height-54,155,40),"Stop MP Batch")){tmp50=true;update("Stopping after the current MP finishes...");}
  if(!tmp41)return;
  float tmp5=Mathf.Min(560,Screen.width-30);float tmp6=Mathf.Max(300,Screen.height-150);Rect tmp7=new Rect(15,110,tmp5,tmp6);
  GUI.Box(tmp7,"");GUILayout.BeginArea(new Rect(tmp7.x+12,tmp7.y+10,tmp7.width-24,tmp7.height-20));
  GUILayout.Label(tmp42?"Loading German MPs...":$"German Bundestag period {tmp48}: {tmp43.Length} names");
  GUILayout.BeginHorizontal();GUILayout.Label("Search",GUILayout.Width(52));tmp46=GUILayout.TextField(tmp46);GUILayout.EndHorizontal();
  GUILayout.BeginHorizontal();
  if(GUILayout.Button("Select shown"))for(int i=0;i<tmp44.Length;i++)if(showName(tmp43[i]))tmp44[i]=true;
  if(GUILayout.Button("Clear"))for(int i=0;i<tmp44.Length;i++)tmp44[i]=false;
  if(GUILayout.Button("Close")){tmp41=false;tmp47=false;}
  GUILayout.EndHorizontal();
  tmp45=GUILayout.BeginScrollView(tmp45,GUILayout.Height(Mathf.Max(110,tmp7.height-190)));
  for(int i=0;i<tmp43.Length;i++)if(showName(tmp43[i]))tmp44[i]=GUILayout.Toggle(tmp44[i],tmp43[i]);
  GUILayout.EndScrollView();
  if(!tmp47){
   GUILayout.BeginHorizontal();if(GUILayout.Button("Generate selected ("+picked()+")"))selected();if(GUILayout.Button("Generate all ("+tmp43.Length+")"))tmp47=true;GUILayout.EndHorizontal();
  }else{
   GUILayout.Label("This can use many paid API calls and take many hours. Generate all "+tmp43.Length+" MPs?");
   GUILayout.BeginHorizontal();if(GUILayout.Button("Yes, generate all"))all();if(GUILayout.Button("Cancel"))tmp47=false;GUILayout.EndHorizontal();
  }
  GUILayout.EndArea();
 }
 void scene(int tmp5){
  tmp51=tmp5;if(tmp40!=null)Destroy(tmp40);tmp40=new GameObject("Simple Scene");Color tmp6=new Color(.45f,.46f,.48f);Color tmp7=new Color(.2f,.32f,.5f);
  thing(PrimitiveType.Cube,"Floor",new Vector3(0,-.16f,1),new Vector3(14,.3f,12),tmp6);
  if(tmp5==1){
   tmp40.name="Parliament Speech";tmp7=new Color(.28f,.23f,.19f);thing(PrimitiveType.Cube,"Wall",new Vector3(0,2.5f,3.8f),new Vector3(12,5,.25f),new Color(.82f,.78f,.67f));
   thing(PrimitiveType.Cube,"Podium",new Vector3(0,.65f,-.72f),new Vector3(1.35f,1.3f,.65f),new Color(.25f,.12f,.06f));thing(PrimitiveType.Cube,"Podium Top",new Vector3(0,1.34f,-.74f),new Vector3(1.55f,.12f,.82f),new Color(.14f,.07f,.03f));
   for(int i=-2;i<=2;i++)thing(PrimitiveType.Cube,"Seat",new Vector3(i*2.2f,.38f,2),new Vector3(1.75f,.75f,1),new Color(.22f,.14f,.08f));
   thing(PrimitiveType.Cube,"Black",new Vector3(3,2.95f,3.62f),new Vector3(1.4f,.28f,.06f),new Color(.03f,.03f,.03f));thing(PrimitiveType.Cube,"Red",new Vector3(3,2.65f,3.62f),new Vector3(1.4f,.28f,.06f),new Color(.7f,.02f,.03f));thing(PrimitiveType.Cube,"Gold",new Vector3(3,2.35f,3.62f),new Vector3(1.4f,.28f,.06f),new Color(.95f,.67f,.05f));
  }else if(tmp5==2){
   tmp40.name="Press Room";tmp7=new Color(.08f,.18f,.35f);thing(PrimitiveType.Cube,"Blue Wall",new Vector3(0,2.3f,3.5f),new Vector3(12,4.6f,.25f),new Color(.06f,.18f,.4f));
   thing(PrimitiveType.Cube,"Press Podium",new Vector3(0,.62f,-.65f),new Vector3(1.2f,1.25f,.55f),new Color(.12f,.2f,.3f));
   thing(PrimitiveType.Cube,"Sign",new Vector3(0,.78f,-.94f),new Vector3(.7f,.32f,.04f),new Color(.82f,.85f,.9f));
   for(int i=-1;i<=1;i++){GameObject tmp8=thing(PrimitiveType.Cylinder,"Microphone",new Vector3(i*.22f,1.56f,-.7f),new Vector3(.025f,.42f,.025f),new Color(.04f,.04f,.04f));tmp8.transform.rotation=Quaternion.Euler(18,0,i*8);thing(PrimitiveType.Sphere,"Mic",new Vector3(i*.22f,1.96f,-.82f),new Vector3(.1f,.1f,.1f),new Color(.03f,.03f,.03f));}
  }else if(tmp5==3){
   tmp40.name="Election Stage";tmp7=new Color(.18f,.12f,.32f);thing(PrimitiveType.Cube,"Stage",new Vector3(0,.04f,.5f),new Vector3(8,.22f,5),new Color(.16f,.16f,.2f));thing(PrimitiveType.Cube,"Stage Wall",new Vector3(0,2.5f,3.2f),new Vector3(10,5,.2f),new Color(.14f,.08f,.28f));
   for(int i=-3;i<=3;i++)thing(PrimitiveType.Cube,"Light Bar",new Vector3(i*1.25f,3.6f,3.05f),new Vector3(.5f,.12f,.08f),i%2==0?new Color(.95f,.3f,.12f):new Color(.2f,.5f,1));
   thing(PrimitiveType.Cube,"Small Podium",new Vector3(0,.5f,-.7f),new Vector3(1.1f,1,.5f),new Color(.08f,.08f,.12f));
  }
  Camera tmp9=camera()==null?null:camera().GetComponent<Camera>();if(tmp9!=null){tmp9.clearFlags=CameraClearFlags.SolidColor;tmp9.backgroundColor=tmp7;}if(tmp22!=null){tmp22.clearFlags=CameraClearFlags.SolidColor;tmp22.backgroundColor=tmp7;}
  if(tmp1!=null){place(tmp1);if(get(tmp1,out Bounds tmp12))camera()?.Focus(tmp12);}if(tmp20!=null){place(tmp20);if(get(tmp20,out Bounds tmp13)&&tmp22!=null)tmp22.GetComponent<AvatarOrbitCamera>()?.Focus(tmp13);}
  update("Scene: "+tmp40.name+". You can generate or load an avatar now.");
 }
 GameObject thing(PrimitiveType tmp5,string tmp6,Vector3 tmp7,Vector3 tmp8,Color tmp9){
  GameObject tmp10=GameObject.CreatePrimitive(tmp5);tmp10.name=tmp6;tmp10.transform.SetParent(tmp40.transform);tmp10.transform.position=tmp7;tmp10.transform.localScale=tmp8;Renderer tmp11=tmp10.GetComponent<Renderer>();if(tmp11!=null)tmp11.material.color=tmp9;return tmp10;
 }
 async Task load(string tmp8){
  GltfImport tmp9=new GltfImport(logger:new ConsoleLogger());GameObject tmp10=null;
  try{
   bool loaded=await tmp9.Load(tmp8);if(!loaded){update2("The generated GLB could not be downloaded.");return;}
   tmp10=new GameObject("Generated_Avatar");if(spawnPoint!=null)tmp10.transform.SetPositionAndRotation(spawnPoint.position,spawnPoint.rotation);
   bool ok=await tmp9.InstantiateMainSceneAsync(tmp10.transform);if(!ok||tmp4){update2("The generated GLB could not be added to the scene.");return;}
   clear();tmp1=tmp10;tmp2=tmp9;tmp10=null;tmp9=null;place(tmp1);rig(tmp1);
   if(get(tmp1,out Bounds tmp11))camera()?.Focus(tmp11);update2("Ready — drag a body part to move it, drag the background to orbit, scroll to zoom, press F to refocus.");
  }catch(Exception e){update2("Unexpected error while loading the generated model.");Debug.LogException(e);}
  finally{if(tmp10!=null)Destroy(tmp10);tmp9?.Dispose();tmp3=false;}
 }
 async Task load2(string tmp5,string tmp6,string tmp7,string tmp8){
  GltfImport tmp9=new GltfImport(logger:new ConsoleLogger());GltfImport tmp10=new GltfImport(logger:new ConsoleLogger());GameObject tmp11=null;GameObject tmp12=null;
  try{
   bool[] tmp13=await Task.WhenAll(tmp9.Load(tmp5),tmp10.Load(tmp6));if(!tmp13[0]||!tmp13[1]){update2("One of the comparison GLB files could not be downloaded.");return;}
   tmp11=new GameObject("GPT_Avatar");tmp12=new GameObject("Ollama_Avatar");
   bool[] tmp14=await Task.WhenAll(tmp9.InstantiateMainSceneAsync(tmp11.transform),tmp10.InstantiateMainSceneAsync(tmp12.transform));
   if(!tmp14[0]||!tmp14[1]||tmp4){update2("One comparison model could not be added to the scene.");return;}
   clear();tmp1=tmp11;tmp2=tmp9;tmp20=tmp12;tmp21=tmp10;tmp11=null;tmp12=null;tmp9=null;tmp10=null;place(tmp1);place(tmp20);rig(tmp1);rig(tmp20);
   if(get(tmp1,out Bounds tmp15)&&get(tmp20,out Bounds tmp16))split(tmp15,tmp16);
   update2("Left: "+tmp7+" | Right: "+tmp8+". Drag or zoom inside either half.");
  }catch(Exception e){update2("Unexpected error while loading the comparison.");Debug.LogException(e);}
  finally{if(tmp11!=null)Destroy(tmp11);if(tmp12!=null)Destroy(tmp12);tmp9?.Dispose();tmp10?.Dispose();tmp3=false;}
 }
 void split(Bounds tmp5,Bounds tmp6){
  AvatarOrbitCamera tmp7=camera();Camera tmp8=tmp7.GetComponent<Camera>();if(tmp23<0)tmp23=tmp8.cullingMask;
  setLayer(tmp1,8);setLayer(tmp20,9);if(tmp22!=null)Destroy(tmp22.gameObject);
  GameObject tmp9=new GameObject("Ollama Comparison Camera");tmp22=tmp9.AddComponent<Camera>();tmp22.CopyFrom(tmp8);tmp22.tag="Untagged";
  AvatarOrbitCamera tmp10=tmp9.AddComponent<AvatarOrbitCamera>();
  tmp8.rect=new Rect(0,0,.5f,1);tmp22.rect=new Rect(.5f,0,.5f,1);tmp22.depth=tmp8.depth+1;
  tmp8.cullingMask=(tmp23&~(1<<9))|(1<<8);tmp22.cullingMask=(tmp23&~(1<<8))|(1<<9);
  tmp7.ownScreen=true;tmp10.ownScreen=true;tmp7.Focus(tmp5);tmp10.Focus(tmp6);
 }
 void rig(GameObject avatar){
  if(AvatarRig.Build(avatar)==null)return;
  if(avatar.GetComponent<AvatarIdleMotion>()==null)avatar.AddComponent<AvatarIdleMotion>();
  if(avatar.GetComponent<AvatarWalkCycle>()==null)avatar.AddComponent<AvatarWalkCycle>();
  if(GetComponent<AvatarPartInteractor>()==null)gameObject.AddComponent<AvatarPartInteractor>();
  motion(avatar);
 }
 // Idle and walking drive the same bones, so exactly one of them may be enabled at a time.
 void motion(GameObject avatar){
  if(avatar==null)return;
  AvatarIdleMotion idle=avatar.GetComponent<AvatarIdleMotion>();
  AvatarWalkCycle step=avatar.GetComponent<AvatarWalkCycle>();
  if(idle!=null)idle.enabled=!walking;
  if(step!=null)step.enabled=walking;
 }
 public void walk(){
  walking=!walking;motion(tmp1);motion(tmp20);
  update(walking?"Walking on the spot. Press Walk again to stand still.":"Standing still.");
 }
 void setLayer(GameObject tmp5,int tmp6){tmp5.layer=tmp6;foreach(Transform tmp7 in tmp5.transform)setLayer(tmp7.gameObject,tmp6);}
 void place(GameObject tmp5){
  if(tmp5==null||!get(tmp5,out Bounds tmp6)||tmp6.size.y<.001f)return;float tmp7=1.78f/tmp6.size.y;tmp5.transform.localScale*=tmp7;
  if(!get(tmp5,out tmp6))return;float tmp8=tmp51==3?.16f:0;tmp5.transform.position+=new Vector3(-tmp6.center.x,tmp8-tmp6.min.y,-tmp6.center.z);
 }
 void clear(){
  if(tmp1!=null){tmp1.SetActive(false);Destroy(tmp1);}if(tmp20!=null){tmp20.SetActive(false);Destroy(tmp20);}
  tmp2?.Dispose();tmp21?.Dispose();tmp1=null;tmp20=null;tmp2=null;tmp21=null;
  AvatarOrbitCamera tmp5=camera();Camera tmp6=tmp5==null?null:tmp5.GetComponent<Camera>();
  if(tmp6!=null){tmp6.rect=new Rect(0,0,1,1);if(tmp23>=0)tmp6.cullingMask=tmp23;tmp5.ownScreen=false;}
  if(tmp22!=null){Destroy(tmp22.gameObject);tmp22=null;}
 }
 void update(string text){if(statusText!=null)statusText.text=text;}
 AvatarOrbitCamera camera(){
  if(orbitCamera!=null)return orbitCamera;Camera tmp12=Camera.main;if(tmp12==null)return null;
  orbitCamera=tmp12.GetComponent<AvatarOrbitCamera>();if(orbitCamera==null)orbitCamera=tmp12.gameObject.AddComponent<AvatarOrbitCamera>();return orbitCamera;
 }
 static bool get(GameObject obj,out Bounds tmp32){
  Renderer[] tmp33=obj.GetComponentsInChildren<Renderer>(true);if(tmp33.Length==0){tmp32=default;return false;}
  tmp32=tmp33[0].bounds;for(int i=1;i<tmp33.Length;i++)tmp32.Encapsulate(tmp33[i].bounds);return tmp32.size.sqrMagnitude>Mathf.Epsilon;
 }
 void update2(string text){if(!tmp4)update(text);}
 void OnDestroy(){tmp4=true;clear();if(tmp40!=null)Destroy(tmp40);}
}
