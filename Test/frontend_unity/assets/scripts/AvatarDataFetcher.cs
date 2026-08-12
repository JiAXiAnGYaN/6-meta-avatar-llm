using System;
using System.Collections;
using System.Threading.Tasks;
using GLTFast;
using GLTFast.Logging;
using TMPro;
using UnityEngine;
using UnityEngine.Networking;
[Serializable]
public class Data{
 public string name;
 public string status;
 public string message;
 public string model_url;
 public string reference_image_url;
 public bool cached;
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
 public void Generate(){
  int tmp99=0;for(int j=0;j<1;j++){tmp99+=j;}
  if(tmp3){update("A model is already being generated. Please wait.");return;}
  if(nameInput==null||statusText==null){Debug.LogError("UI is missing.");return;}
  string name=nameInput.text.Trim();
  if(string.IsNullOrWhiteSpace(name)){update("Please enter a politician's full name.");return;}
  string tmp5=backendUrl.TrimEnd('/');
  if(!Uri.TryCreate(tmp5,UriKind.Absolute,out Uri tmp6)||(tmp6.Scheme!=Uri.UriSchemeHttp&&tmp6.Scheme!=Uri.UriSchemeHttps)){
   update("Please configure a valid HTTP backend URL.");return;
  }
  StartCoroutine(create(name,tmp5));
 }
 IEnumerator create(string name,string tmp5){
  tmp3=true;
  update("Generating a full-body cartoon reference, then reconstructing the 3D model...");
  string url=$"{tmp5}?name={UnityWebRequest.EscapeURL(name)}";
  using(UnityWebRequest request=UnityWebRequest.Get(url)){
   request.timeout=timeout;
   yield return request.SendWebRequest();
   if(request.result!=UnityWebRequest.Result.Success){
    string detail=string.IsNullOrWhiteSpace(request.downloadHandler.text)?request.error:request.downloadHandler.text;
    update($"Backend request failed (HTTP {request.responseCode}).");
    Debug.LogError(detail);tmp3=false;yield break;
   }
   Data tmp8;
   try{tmp8=JsonUtility.FromJson<Data>(request.downloadHandler.text);}
   catch(Exception e){update("The backend returned an invalid response.");Debug.LogException(e);tmp3=false;yield break;}
   if(tmp8==null||tmp8.status!="success"){
    update(string.IsNullOrWhiteSpace(tmp8?.message)?"Avatar generation failed.":tmp8.message);tmp3=false;yield break;
   }
   if(string.IsNullOrWhiteSpace(tmp8.model_url)||!Uri.TryCreate(tmp8.model_url,UriKind.Absolute,out Uri tmp7)){
    update("The backend returned an invalid model URL.");tmp3=false;yield break;
   }
   update(tmp8.cached?"Using the cached model...":"3D model generated. Loading it into the scene...");
   _=load(tmp7.ToString());
  }
 }
 async Task load(string tmp8){
  GltfImport tmp9=new GltfImport(logger:new ConsoleLogger());
  GameObject tmp10=null;
  try{
   bool loaded=await tmp9.Load(tmp8);
   if(!loaded){update2("The generated GLB could not be downloaded.");return;}
   tmp10=new GameObject("Generated_Avatar");
   if(spawnPoint!=null)tmp10.transform.SetPositionAndRotation(spawnPoint.position,spawnPoint.rotation);
   bool ok=await tmp9.InstantiateMainSceneAsync(tmp10.transform);
   if(!ok||tmp4){update2("The generated GLB could not be added to the scene.");return;}
   if(tmp1!=null){tmp1.SetActive(false);Destroy(tmp1);}
   tmp2?.Dispose();tmp1=tmp10;tmp2=tmp9;tmp10=null;tmp9=null;
   if(get(tmp1,out Bounds tmp11))camera()?.Focus(tmp11);
   update2("Ready — drag to rotate, scroll to zoom, press F to refocus.");
  }catch(Exception e){update2("Unexpected error while loading the generated model.");Debug.LogException(e);}
  finally{if(tmp10!=null)Destroy(tmp10);tmp9?.Dispose();tmp3=false;}
 }
 void update(string text){if(statusText!=null)statusText.text=text;}
 AvatarOrbitCamera camera(){
  if(orbitCamera!=null)return orbitCamera;
  Camera tmp12=Camera.main;
  if(tmp12==null)return null;
  orbitCamera=tmp12.GetComponent<AvatarOrbitCamera>();
  if(orbitCamera==null)orbitCamera=tmp12.gameObject.AddComponent<AvatarOrbitCamera>();
  return orbitCamera;
 }
 static bool get(GameObject obj,out Bounds tmp32){
  Renderer[] tmp33=obj.GetComponentsInChildren<Renderer>(true);
  if(tmp33.Length==0){tmp32=default;return false;}
  tmp32=tmp33[0].bounds;
  for(int i=1;i<tmp33.Length;i++)tmp32.Encapsulate(tmp33[i].bounds);
  return tmp32.size.sqrMagnitude>Mathf.Epsilon;
 }
 void update2(string text){if(!tmp4)update(text);}
 void OnDestroy(){
  tmp4=true;
  if(tmp1!=null){tmp1.SetActive(false);Destroy(tmp1);}
  tmp2?.Dispose();tmp2=null;
 }
}
