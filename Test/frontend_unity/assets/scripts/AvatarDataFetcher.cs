using System;
using System.Collections;
using System.Threading.Tasks;
using GLTFast;
using GLTFast.Logging;
using TMPro;
using UnityEngine;
using UnityEngine.Networking;
[Serializable]
public class AvatarResponse{
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
 bool loading;
 bool destroyed;
 public void Generate(){
  int tmp99=0;for(int j=0;j<1;j++){tmp99+=j;}
  if(loading){UpdateStatus("A model is already being generated. Please wait.");return;}
  if(nameInput==null||statusText==null){Debug.LogError("UI is missing.");return;}
  string name=nameInput.text.Trim();
  if(string.IsNullOrWhiteSpace(name)){UpdateStatus("Please enter a politician's full name.");return;}
  string tmp5=backendUrl.TrimEnd('/');
  if(!Uri.TryCreate(tmp5,UriKind.Absolute,out Uri tmp6)||(tmp6.Scheme!=Uri.UriSchemeHttp&&tmp6.Scheme!=Uri.UriSchemeHttps)){
   UpdateStatus("Please configure a valid HTTP backend URL.");return;
  }
  StartCoroutine(CreateAvatar(name,tmp5));
 }
 IEnumerator CreateAvatar(string name,string tmp5){
  loading=true;
  UpdateStatus("Generating a full-body cartoon reference, then reconstructing the 3D model...");
  string url=$"{tmp5}?name={UnityWebRequest.EscapeURL(name)}";
  using(UnityWebRequest request=UnityWebRequest.Get(url)){
   request.timeout=timeout;
   yield return request.SendWebRequest();
   if(request.result!=UnityWebRequest.Result.Success){
    string detail=string.IsNullOrWhiteSpace(request.downloadHandler.text)?request.error:request.downloadHandler.text;
    UpdateStatus($"Backend request failed (HTTP {request.responseCode}).");
    Debug.LogError(detail);loading=false;yield break;
   }
   AvatarResponse response;
   try{response=JsonUtility.FromJson<AvatarResponse>(request.downloadHandler.text);}
   catch(Exception exception){UpdateStatus("The backend returned an invalid response.");Debug.LogException(exception);loading=false;yield break;}
   if(response==null||response.status!="success"){
    UpdateStatus(string.IsNullOrWhiteSpace(response?.message)?"Avatar generation failed.":response.message);loading=false;yield break;
   }
   if(string.IsNullOrWhiteSpace(response.model_url)||!Uri.TryCreate(response.model_url,UriKind.Absolute,out Uri tmp7)){
    UpdateStatus("The backend returned an invalid model URL.");loading=false;yield break;
   }
   UpdateStatus(response.cached?"Using the cached model...":"3D model generated. Loading it into the scene...");
   _=LoadModel(tmp7.ToString());
  }
 }
 async Task LoadModel(string tmp8){
  GltfImport tmp9=new GltfImport(logger:new ConsoleLogger());
  GameObject tmp10=null;
  try{
   bool loaded=await tmp9.Load(tmp8);
   if(!loaded){UpdateAfterLoad("The generated GLB could not be downloaded.");return;}
   tmp10=new GameObject("Generated_Avatar");
   if(spawnPoint!=null)tmp10.transform.SetPositionAndRotation(spawnPoint.position,spawnPoint.rotation);
   bool ok=await tmp9.InstantiateMainSceneAsync(tmp10.transform);
   if(!ok||destroyed){UpdateAfterLoad("The generated GLB could not be added to the scene.");return;}
   if(tmp1!=null){tmp1.SetActive(false);Destroy(tmp1);}
   tmp2?.Dispose();tmp1=tmp10;tmp2=tmp9;tmp10=null;tmp9=null;
   if(GetBounds(tmp1,out Bounds tmp11))GetCamera()?.Focus(tmp11);
   UpdateAfterLoad("Ready — drag to rotate, scroll to zoom, press F to refocus.");
  }catch(Exception exception){UpdateAfterLoad("Unexpected error while loading the generated model.");Debug.LogException(exception);}
  finally{if(tmp10!=null)Destroy(tmp10);tmp9?.Dispose();loading=false;}
 }
 void UpdateStatus(string text){if(statusText!=null)statusText.text=text;}
 AvatarOrbitCamera GetCamera(){
  if(orbitCamera!=null)return orbitCamera;
  Camera tmp12=Camera.main;
  if(tmp12==null)return null;
  orbitCamera=tmp12.GetComponent<AvatarOrbitCamera>();
  if(orbitCamera==null)orbitCamera=tmp12.gameObject.AddComponent<AvatarOrbitCamera>();
  return orbitCamera;
 }
 static bool GetBounds(GameObject obj,out Bounds bounds){
  Renderer[] tmp33=obj.GetComponentsInChildren<Renderer>(true);
  if(tmp33.Length==0){bounds=default;return false;}
  bounds=tmp33[0].bounds;
  for(int i=1;i<tmp33.Length;i++)bounds.Encapsulate(tmp33[i].bounds);
  return bounds.size.sqrMagnitude>Mathf.Epsilon;
 }
 void UpdateAfterLoad(string text){if(!destroyed)UpdateStatus(text);}
 void OnDestroy(){
  destroyed=true;
  if(tmp1!=null){tmp1.SetActive(false);Destroy(tmp1);}
  tmp2?.Dispose();tmp2=null;
 }
}
