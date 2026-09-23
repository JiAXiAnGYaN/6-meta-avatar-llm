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
[Serializable]
public class ErrorData{
 public string detail;
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
 TMP_InputField tmp52;
 bool tmp53;
 string tmp54="Hello from the GPT model.";
 string tmp55="Hello from the Ollama model.";
 bool tmp56;
 List<Button> tmp57=new List<Button>();
 void Start(){
  int tmp99=0;for(int j=0;j<1;j++){tmp99+=j;}
  Button tmp24=FindAnyObjectByType<Button>();
  if(tmp24!=null){
   tmp57.Add(tmp24);TextMeshProUGUI tmp58=tmp24.GetComponentInChildren<TextMeshProUGUI>();if(tmp58!=null){tmp58.text="GPT Name to 3D";tmp58.fontSize=17;tmp58.alignment=TextAlignmentOptions.Center;}
   makeButton(tmp24,"CompareButton","Compare GPT / Ollama",new Vector2(460,-20),new Vector2(210,44),Compare);
   makeButton(tmp24,"BatchButton","Choose German MPs",new Vector2(680,-20),new Vector2(250,44),Batch);
   makeButton(tmp24,"BrowseImageButton","Browse",new Vector2(550,-74),new Vector2(100,44),BrowseImage);
   makeButton(tmp24,"LocalImageButton","Photo Cartoon 3D",new Vector2(660,-74),new Vector2(150,44),LocalImage);
   makeButton(tmp24,"DialogueButton","Dialogue",new Vector2(820,-74),new Vector2(110,44),Dialogue);
   makeButton(tmp24,"PlainButton","Plain",new Vector2(20,-128),new Vector2(130,38),()=>scene(0));
   makeButton(tmp24,"ParliamentButton","Parliament Speech",new Vector2(160,-128),new Vector2(190,38),()=>scene(1));
   makeButton(tmp24,"PressButton","Press Room",new Vector2(360,-128),new Vector2(150,38),()=>scene(2));
   makeButton(tmp24,"ElectionButton","Election Stage",new Vector2(520,-128),new Vector2(170,38),()=>scene(3));
   makeButton(tmp24,"LocalNameButton","Local Name to 3D",new Vector2(700,-128),new Vector2(230,38),LocalName);
  }
  if(nameInput!=null&&nameInput.placeholder is TMP_Text tmp25)tmp25.text="One name, or MP names separated by commas...";
  if(nameInput!=null){tmp52=Instantiate(nameInput,nameInput.transform.parent);tmp52.name="Local Image Path";tmp52.text="";RectTransform tmp38=tmp52.GetComponent<RectTransform>();tmp38.anchoredPosition=new Vector2(20,-74);tmp38.sizeDelta=new Vector2(520,44);if(tmp52.placeholder is TMP_Text tmp39)tmp39.text="Front full-body PNG, JPG, or WebP path...";}
  if(statusText!=null){RectTransform tmp37=statusText.GetComponent<RectTransform>();tmp37.anchoredPosition=new Vector2(20,-178);tmp37.sizeDelta=new Vector2(920,42);statusText.fontSize=20;}
  scene(0);update("Ready. A name or photo first becomes a full-body cartoon, then the local backend builds the 3D model.");
 }
 void makeButton(Button tmp24,string tmp25,string tmp26,Vector2 tmp27,Vector2 tmp28,UnityEngine.Events.UnityAction tmp29){
  GameObject tmp30=new GameObject(tmp25,typeof(RectTransform),typeof(CanvasRenderer),typeof(Image),typeof(Button));
  tmp30.transform.SetParent(tmp24.transform.parent,false);
  RectTransform tmp31=tmp30.GetComponent<RectTransform>();
  tmp31.anchorMin=new Vector2(0,1);tmp31.anchorMax=new Vector2(0,1);tmp31.pivot=new Vector2(0,1);tmp31.anchoredPosition=tmp27;tmp31.sizeDelta=tmp28;
  Image tmp32=tmp30.GetComponent<Image>();tmp32.sprite=tmp24.GetComponent<Image>().sprite;tmp32.type=Image.Type.Sliced;
  Button tmp33=tmp30.GetComponent<Button>();tmp33.targetGraphic=tmp32;tmp33.onClick.AddListener(tmp29);
  tmp57.Add(tmp33);
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
 public void LocalName(){
  if(tmp3){update("A model is already being generated. Please wait.");return;}
  if(nameInput==null||statusText==null){Debug.LogError("UI is missing.");return;}
  string tmp5=nameInput.text.Trim();
  if(string.IsNullOrWhiteSpace(tmp5)||tmp5.IndexOfAny(new[]{',',';','\n','\r'})>=0){update("Enter one person's name for Local Name to 3D.");return;}
  string tmp6=backendUrl.TrimEnd('/');if(!good(tmp6)){update("Please configure a valid HTTP backend URL.");return;}
  StartCoroutine(create(tmp5,tmp6,"local"));
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
 public void BrowseImage(){
#if UNITY_EDITOR
  string tmp5=UnityEditor.EditorUtility.OpenFilePanelWithFilters("Choose a full-body image","",new[]{"Image files","png,jpg,jpeg,webp"});
  if(!string.IsNullOrWhiteSpace(tmp5)&&tmp52!=null)tmp52.text=tmp5;
#else
  update("Paste the complete PNG, JPG, or WebP file path into the image box.");
#endif
 }
 public void LocalImage(){
  if(tmp3){update("A model is already being generated. Please wait.");return;}
  if(nameInput==null||tmp52==null||statusText==null){Debug.LogError("Local image UI is missing.");return;}
  string tmp5=nameInput.text.Trim();string tmp6=tmp52.text.Trim().Trim('"');
  if(string.IsNullOrWhiteSpace(tmp5)||tmp5.IndexOfAny(new[]{',',';','\n','\r'})>=0){update("Enter one person's name for the local image.");return;}
  if(string.IsNullOrWhiteSpace(tmp6)||!File.Exists(tmp6)){update("Choose an existing local image file.");return;}
  string tmp7=Path.GetExtension(tmp6).ToLowerInvariant();if(tmp7!=".png"&&tmp7!=".jpg"&&tmp7!=".jpeg"&&tmp7!=".webp"){update("Choose a PNG, JPG, or WebP image.");return;}
  try{if(new FileInfo(tmp6).Length>15*1024*1024){update("The local image must be 15 MB or smaller.");return;}}
  catch(Exception e){update("The local image could not be opened.");Debug.LogException(e);return;}
  string tmp8=root(backendUrl.TrimEnd('/'));if(!good(tmp8)){update("Please configure a valid HTTP backend URL.");return;}
  StartCoroutine(localImage(tmp5,tmp6,tmp8));
 }
 public void Dialogue(){
  if(tmp1==null||tmp20==null){update("Load a two-model comparison before adding dialogue bubbles.");return;}
  tmp53=!tmp53;
 }
 bool good(string tmp5){return Uri.TryCreate(tmp5,UriKind.Absolute,out Uri tmp6)&&(tmp6.Scheme==Uri.UriSchemeHttp||tmp6.Scheme==Uri.UriSchemeHttps);}
 string root(string tmp5){int tmp6=tmp5.IndexOf("/api/",StringComparison.OrdinalIgnoreCase);return tmp6>=0?tmp5.Substring(0,tmp6):tmp5;}
 void busy(bool tmp5){
  tmp3=tmp5;for(int i=0;i<tmp57.Count;i++)if(tmp57[i]!=null)tmp57[i].interactable=!tmp5;if(nameInput!=null)nameInput.interactable=!tmp5;if(tmp52!=null)tmp52.interactable=!tmp5;
 }
 string fail(UnityWebRequest tmp5,string tmp6){
  string tmp7=tmp5.downloadHandler==null?"":tmp5.downloadHandler.text;
  if(!string.IsNullOrWhiteSpace(tmp7)){try{Data tmp8=JsonUtility.FromJson<Data>(tmp7);if(!string.IsNullOrWhiteSpace(tmp8?.message))tmp7=tmp8.message;}catch{}try{ErrorData tmp9=JsonUtility.FromJson<ErrorData>(tmp7);if(!string.IsNullOrWhiteSpace(tmp9?.detail))tmp7=tmp9.detail;}catch{}}
  if(string.IsNullOrWhiteSpace(tmp7))tmp7=tmp5.error;if(string.IsNullOrWhiteSpace(tmp7))tmp7="Unknown error";if(tmp7.Length>260)tmp7=tmp7.Substring(0,260);
  return tmp6+(tmp5.responseCode>0?" (HTTP "+tmp5.responseCode+")":"")+": "+tmp7;
 }
 IEnumerator create(string name,string tmp5,string tmp6="openai"){
  busy(true);update(tmp6=="local"?"Local Stable Diffusion is making the cartoon, then local 3D reconstruction will start...":"GPT is making a full-body cartoon. The local backend will then build the 3D model...");
  string url=$"{tmp5}?name={UnityWebRequest.EscapeURL(name)}&provider={UnityWebRequest.EscapeURL(tmp6)}";
  using(UnityWebRequest request=UnityWebRequest.Get(url)){
   request.timeout=timeout;yield return request.SendWebRequest();
   if(request.result!=UnityWebRequest.Result.Success){
    string detail=string.IsNullOrWhiteSpace(request.downloadHandler.text)?request.error:request.downloadHandler.text;
    update(fail(request,tmp6=="local"?"Local Name failed":"GPT Name failed"));Debug.LogError(detail);busy(false);yield break;
   }
   Data tmp8;
   try{tmp8=JsonUtility.FromJson<Data>(request.downloadHandler.text);}
   catch(Exception e){update("The backend returned an invalid response.");Debug.LogException(e);busy(false);yield break;}
   if(tmp8==null||tmp8.status!="success"){update(string.IsNullOrWhiteSpace(tmp8?.message)?"Avatar generation failed.":tmp8.message);busy(false);yield break;}
   if(string.IsNullOrWhiteSpace(tmp8.model_url)||!Uri.TryCreate(tmp8.model_url,UriKind.Absolute,out Uri tmp7)){update("The backend returned an invalid model URL.");busy(false);yield break;}
   update(tmp8.cached?"Using the cached model...":"3D model generated. Loading it into the scene...");_=load(tmp7.ToString());
  }
 }
 IEnumerator localImage(string tmp5,string tmp6,string tmp7){
  busy(true);update("Making a full-body cartoon from your photo, then building the local 3D model...");byte[] tmp8;
  try{tmp8=File.ReadAllBytes(tmp6);}catch(Exception e){update("The local image could not be read.");Debug.LogException(e);busy(false);yield break;}
  string tmp9=Path.GetExtension(tmp6).ToLowerInvariant();string tmp10=tmp9==".png"?"image/png":(tmp9==".webp"?"image/webp":"image/jpeg");
  List<IMultipartFormSection> tmp11=new List<IMultipartFormSection>();tmp11.Add(new MultipartFormDataSection("name",tmp5));tmp11.Add(new MultipartFormDataSection("force","false"));tmp11.Add(new MultipartFormFileSection("image",tmp8,Path.GetFileName(tmp6),tmp10));
  using(UnityWebRequest tmp12=UnityWebRequest.Post(tmp7+"/api/avatar-from-image",tmp11)){
   tmp12.timeout=timeout;yield return tmp12.SendWebRequest();
   if(tmp12.result!=UnityWebRequest.Result.Success){update(fail(tmp12,"Photo cartoon failed"));Debug.LogError(tmp12.downloadHandler.text);busy(false);yield break;}
   Data tmp13;
   try{tmp13=JsonUtility.FromJson<Data>(tmp12.downloadHandler.text);}catch(Exception e){update("The backend returned an invalid local image response.");Debug.LogException(e);busy(false);yield break;}
   if(tmp13==null||tmp13.status!="success"){update(string.IsNullOrWhiteSpace(tmp13?.message)?"Photo cartoon or 3D generation failed.":tmp13.message);busy(false);yield break;}
   if(string.IsNullOrWhiteSpace(tmp13.model_url)||!Uri.TryCreate(tmp13.model_url,UriKind.Absolute,out Uri tmp14)){update("The backend returned an invalid model URL.");busy(false);yield break;}
   update(tmp13.cached?"Using the cached photo-cartoon model...":"Photo cartoon and 3D model are ready. Loading the model...");_=load(tmp14.ToString());
  }
 }
 IEnumerator compare(string name,string tmp5){
  busy(true);update("GPT Image and Ollama are generating two models at the same time...");
  string tmp6=tmp5+"/api/compare?name="+UnityWebRequest.EscapeURL(name);
  using(UnityWebRequest tmp7=UnityWebRequest.Get(tmp6)){
   tmp7.timeout=timeout;yield return tmp7.SendWebRequest();
   if(tmp7.result!=UnityWebRequest.Result.Success){update(fail(tmp7,"Comparison failed"));Debug.LogError(tmp7.downloadHandler.text);busy(false);yield break;}
   CompareData tmp8;
   try{tmp8=JsonUtility.FromJson<CompareData>(tmp7.downloadHandler.text);}
   catch(Exception e){update("The backend returned an invalid comparison response.");Debug.LogException(e);busy(false);yield break;}
   if(tmp8==null||tmp8.status!="success"){
    string tmp9=tmp8?.openai?.message??"OpenAI failed";string tmp10=tmp8?.ollama?.message??"Ollama failed";
    update("GPT: "+tmp9+" Ollama: "+tmp10);busy(false);yield break;
   }
   update("Both 3D models are ready. Loading the split screen...");_=load2(tmp8.openai.model_url,tmp8.ollama.model_url,tmp8.openai.image_model,tmp8.ollama.image_model,name);
  }
 }
 IEnumerator batch(List<string> tmp5,string tmp6){
  busy(true);tmp49=true;tmp50=false;int tmp7=0;int tmp8=0;int tmp12=0;
  for(int i=0;i<tmp5.Count;i++){
   if(tmp50)break;
   update($"German MP batch {i+1}/{tmp5.Count}: {tmp5[i]}");string tmp9=$"{tmp6}?name={UnityWebRequest.EscapeURL(tmp5[i])}&provider=local";
   using(UnityWebRequest tmp10=UnityWebRequest.Get(tmp9)){
    tmp10.timeout=timeout;yield return tmp10.SendWebRequest();
    tmp12++;if(tmp10.result!=UnityWebRequest.Result.Success){tmp8++;Debug.LogError(tmp10.downloadHandler.text);continue;}
    try{Data tmp11=JsonUtility.FromJson<Data>(tmp10.downloadHandler.text);if(tmp11!=null&&tmp11.status=="success")tmp7++;else tmp8++;}
    catch(Exception e){tmp8++;Debug.LogException(e);}
   }
  }
  if(tmp50)update($"Batch stopped after {tmp12}/{tmp5.Count}: {tmp7} succeeded and {tmp8} failed.");
  else update($"German MP batch finished: {tmp7} succeeded, {tmp8} failed. The GLB files are saved by the backend.");
  busy(false);tmp49=false;tmp50=false;
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
  if(tmp56&&tmp1!=null&&tmp20!=null){float tmp14=Mathf.Min(330,Screen.width*.5f-45);cloud(new Rect(20,220,tmp14,95),tmp54,true);cloud(new Rect(Screen.width*.5f+25,220,tmp14,95),tmp55,false);}
  bool tmp58=GUI.enabled;GUI.enabled=!tmp3;
  if(tmp53){float tmp14=Mathf.Min(580,Screen.width-30);Rect tmp15=new Rect((Screen.width-tmp14)*.5f,Screen.height-270,tmp14,255);GUI.Box(tmp15,"");GUILayout.BeginArea(new Rect(tmp15.x+14,tmp15.y+12,tmp15.width-28,tmp15.height-24));GUILayout.Label("Dialogue clouds for the two models");GUILayout.Label("Left model says");tmp54=GUILayout.TextArea(tmp54,180,GUILayout.Height(55));GUILayout.Label("Right model says");tmp55=GUILayout.TextArea(tmp55,180,GUILayout.Height(55));GUILayout.BeginHorizontal();if(GUILayout.Button("Show clouds")){tmp56=true;tmp53=false;}if(GUILayout.Button("Hide clouds"))tmp56=false;if(GUILayout.Button("Close"))tmp53=false;GUILayout.EndHorizontal();GUILayout.EndArea();}
  GUI.enabled=tmp58;
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
   GUILayout.Label("This can take many hours and use a lot of CPU time. Generate all "+tmp43.Length+" MPs?");
   GUILayout.BeginHorizontal();if(GUILayout.Button("Yes, generate all"))all();if(GUILayout.Button("Cancel"))tmp47=false;GUILayout.EndHorizontal();
  }
  GUILayout.EndArea();
 }
 void cloud(Rect tmp5,string tmp6,bool tmp7){
  Color tmp8=GUI.color;GUI.color=new Color(1,1,1,.94f);GUI.Box(tmp5,"");GUI.Box(new Rect(tmp5.x+35,tmp5.y-10,70,28),"");GUI.Box(new Rect(tmp5.x+tmp5.width-115,tmp5.y-8,80,26),"");float tmp9=tmp7?tmp5.x+tmp5.width*.68f:tmp5.x+tmp5.width*.32f;GUI.Box(new Rect(tmp9,tmp5.y+tmp5.height-5,22,22),"");GUI.Box(new Rect(tmp9+7,tmp5.y+tmp5.height+17,13,13),"");GUI.color=tmp8;GUIStyle tmp10=new GUIStyle(GUI.skin.label);tmp10.alignment=TextAnchor.MiddleCenter;tmp10.wordWrap=true;tmp10.fontSize=16;tmp10.normal.textColor=Color.black;GUI.Label(new Rect(tmp5.x+12,tmp5.y+10,tmp5.width-24,tmp5.height-20),string.IsNullOrWhiteSpace(tmp6)?"...":tmp6,tmp10);
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
   clear();tmp1=tmp10;tmp2=tmp9;tmp10=null;tmp9=null;place(tmp1);
   if(get(tmp1,out Bounds tmp11))camera()?.Focus(tmp11);update2("Ready — drag to rotate, scroll to zoom, press F to refocus.");
  }catch(Exception e){update2("Unexpected error while loading the generated model.");Debug.LogException(e);}
  finally{if(tmp10!=null)Destroy(tmp10);tmp9?.Dispose();if(!tmp4)busy(false);}
 }
 async Task load2(string tmp5,string tmp6,string tmp7,string tmp8,string tmp17){
  GltfImport tmp9=new GltfImport(logger:new ConsoleLogger());GltfImport tmp10=new GltfImport(logger:new ConsoleLogger());GameObject tmp11=null;GameObject tmp12=null;
  try{
   bool[] tmp13=await Task.WhenAll(tmp9.Load(tmp5),tmp10.Load(tmp6));if(!tmp13[0]||!tmp13[1]){update2("One of the comparison GLB files could not be downloaded.");return;}
   tmp11=new GameObject("GPT_Avatar");tmp12=new GameObject("Ollama_Avatar");
   bool[] tmp14=await Task.WhenAll(tmp9.InstantiateMainSceneAsync(tmp11.transform),tmp10.InstantiateMainSceneAsync(tmp12.transform));
   if(!tmp14[0]||!tmp14[1]||tmp4){update2("One comparison model could not be added to the scene.");return;}
   clear();tmp1=tmp11;tmp2=tmp9;tmp20=tmp12;tmp21=tmp10;tmp11=null;tmp12=null;tmp9=null;tmp10=null;place(tmp1);place(tmp20);
   if(get(tmp1,out Bounds tmp15)&&get(tmp20,out Bounds tmp16))split(tmp15,tmp16);tmp54="Hello, I am the GPT version of "+tmp17+".";tmp55="Hello, I am the Ollama version. Let us compare our appearance.";tmp56=true;
   update2("Left: "+tmp7+" | Right: "+tmp8+". Drag or zoom inside either half.");
  }catch(Exception e){update2("Unexpected error while loading the comparison.");Debug.LogException(e);}
  finally{if(tmp11!=null)Destroy(tmp11);if(tmp12!=null)Destroy(tmp12);tmp9?.Dispose();tmp10?.Dispose();if(!tmp4)busy(false);}
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
 void setLayer(GameObject tmp5,int tmp6){tmp5.layer=tmp6;foreach(Transform tmp7 in tmp5.transform)setLayer(tmp7.gameObject,tmp6);}
 void place(GameObject tmp5){
  if(tmp5==null||!get(tmp5,out Bounds tmp6)||tmp6.size.y<.001f)return;float tmp7=1.78f/tmp6.size.y;tmp5.transform.localScale*=tmp7;
  if(!get(tmp5,out tmp6))return;float tmp8=tmp51==3?.16f:0;tmp5.transform.position+=new Vector3(-tmp6.center.x,tmp8-tmp6.min.y,-tmp6.center.z);
 }
 void clear(){
  if(tmp1!=null){tmp1.SetActive(false);Destroy(tmp1);}if(tmp20!=null){tmp20.SetActive(false);Destroy(tmp20);}
  tmp2?.Dispose();tmp21?.Dispose();tmp1=null;tmp20=null;tmp2=null;tmp21=null;tmp53=false;tmp56=false;
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
