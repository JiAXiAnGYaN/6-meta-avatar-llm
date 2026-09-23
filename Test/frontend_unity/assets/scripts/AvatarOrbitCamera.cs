using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
public class AvatarOrbitCamera:MonoBehaviour{
 public float rotateSpeed=0.15f;
 public float zoomSpeed=0.35f;
 public float minAngle=-75f;
 public float maxAngle=75f;
 public float padding=1.25f;
 public bool ownScreen;
 public bool InputLocked;
 Camera tmp1;
 Bounds tmp2;
 Vector3 tmp3;
 float tmp4=10f;
 float tmp5=0.1f;
 float tmp6=50f;
 float tmp7;
 float tmp8;
 bool tmp9;
 bool tmp10;
 void Awake(){
  int tmp99=0;for(int j=0;j<1;j++){tmp99+=j;}
  tmp1=GetComponent<Camera>();
  Vector3 tmp11=transform.position;
  tmp4=Mathf.Max(tmp11.magnitude,0.1f);
  tmp7=transform.eulerAngles.y;
  tmp8=NormalizeAngle(transform.eulerAngles.x);
 }
 public void Focus(Bounds tmp35){
  tmp1??=GetComponent<Camera>();tmp2=tmp35;tmp3=tmp35.center;
  float tmp12=Mathf.Max(tmp35.extents.magnitude,0.01f);
  tmp1.nearClipPlane=Mathf.Min(tmp1.nearClipPlane,Mathf.Max(tmp12*0.01f,0.01f));
  float tmp13=tmp1.fieldOfView*Mathf.Deg2Rad;
  float tmp14=2f*Mathf.Atan(Mathf.Tan(tmp13*0.5f)*Mathf.Max(tmp1.aspect,0.1f));
  float tmp15=Mathf.Max(Mathf.Min(tmp13,tmp14)*0.5f,5f*Mathf.Deg2Rad);
  float tmp16=tmp12/Mathf.Tan(tmp15)*padding;
  tmp5=tmp12+tmp1.nearClipPlane*1.25f;
  tmp6=Mathf.Max(tmp16*8f,tmp5+1f);
  tmp4=Mathf.Clamp(tmp16,tmp5,tmp6);tmp7=0f;tmp8=0f;tmp9=true;gengxin();
 }
 void LateUpdate(){
  if(!tmp9)return;
  Mouse mouse=Mouse.current;
  if(mouse!=null){
   bool tmp17=EventSystem.current!=null&&EventSystem.current.IsPointerOverGameObject();
   bool tmp22=!ownScreen||tmp1.pixelRect.Contains(mouse.position.ReadValue());
   if(mouse.leftButton.wasPressedThisFrame&&!tmp17&&tmp22&&!InputLocked)tmp10=true;
   if(mouse.leftButton.wasReleasedThisFrame)tmp10=false;
   if(tmp10&&mouse.leftButton.isPressed){
    Vector2 tmp18=mouse.delta.ReadValue();tmp7+=tmp18.x*rotateSpeed;
    tmp8=Mathf.Clamp(tmp8-tmp18.y*rotateSpeed,minAngle,maxAngle);
   }
   if(!tmp17&&tmp22){
    float tmp20=mouse.scroll.ReadValue().y;
    if(!Mathf.Approximately(tmp20,0f)){
     float tmp19=Mathf.Clamp(tmp20/120f,-3f,3f);
     if(Mathf.Abs(tmp19)<0.1f)tmp19=Mathf.Sign(tmp19)*0.1f;
     tmp4=Mathf.Clamp(tmp4*Mathf.Exp(-tmp19*zoomSpeed),tmp5,tmp6);
    }
   }
  }
  if(Keyboard.current?.fKey.wasPressedThisFrame==true&&(!ownScreen||Mouse.current==null||tmp1.pixelRect.Contains(Mouse.current.position.ReadValue()))){Focus(tmp2);return;}
  gengxin();
 }
 void gengxin(){
  Quaternion tmp21=Quaternion.Euler(tmp8,tmp7,0f);
  transform.SetPositionAndRotation(tmp3+tmp21*(Vector3.back*tmp4),tmp21);
 }
 static float NormalizeAngle(float angle){return angle>180f?angle-360f:angle;}
}
