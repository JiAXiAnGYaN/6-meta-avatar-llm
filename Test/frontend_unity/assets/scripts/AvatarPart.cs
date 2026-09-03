using UnityEngine;

/// <summary>
/// Marks a clickable region of the avatar and keeps the rotation its bone is allowed to take.
/// </summary>
public class AvatarPart : MonoBehaviour
{
    public Transform bone;
    public string label = "Part";

    public Vector3 yawAxis = Vector3.up;
    public Vector3 pitchAxis = Vector3.right;
    public float yawLimit = 70f;
    public float pitchLimit = 35f;

    [Tooltip("Degrees per pixel of mouse movement.")]
    public float sensitivity = 0.4f;

    [Tooltip("Seconds to ease back to the rest pose after releasing. Zero keeps the pose.")]
    public float returnDuration = 0.45f;

    Quaternion restRotation;
    float yaw;
    float pitch;
    float returnTimer = -1f;
    Quaternion returnFrom;

    public void Initialize(Transform target, string partLabel)
    {
        bone = target;
        label = partLabel;
        ApplyDefaultLimits();
        if (bone != null) restRotation = bone.localRotation;
    }

    void ApplyDefaultLimits()
    {
        switch (label)
        {
            // The texture is a projection taken from the front, so it only reads correctly while
            // a part stays roughly front facing. The limits keep the motion inside that range.
            case "Head":
                yawAxis = Vector3.up; pitchAxis = Vector3.right;
                yawLimit = 45f; pitchLimit = 25f;
                break;
            case "Arm_L":
                yawAxis = Vector3.forward; pitchAxis = Vector3.right;
                yawLimit = 80f; pitchLimit = 55f;
                break;
            case "Arm_R":
                yawAxis = -Vector3.forward; pitchAxis = Vector3.right;
                yawLimit = 80f; pitchLimit = 55f;
                break;
            case "Torso":
                yawAxis = Vector3.up; pitchAxis = Vector3.right;
                yawLimit = 30f; pitchLimit = 15f;
                break;
        }
    }

    public void Drag(Vector2 delta)
    {
        if (bone == null) return;
        returnTimer = -1f;
        yaw = Mathf.Clamp(yaw + delta.x * sensitivity, -yawLimit, yawLimit);
        pitch = Mathf.Clamp(pitch - delta.y * sensitivity, -pitchLimit, pitchLimit);
        bone.localRotation = restRotation
            * Quaternion.AngleAxis(yaw, yawAxis.normalized)
            * Quaternion.AngleAxis(pitch, pitchAxis.normalized);
    }

    public void Release()
    {
        if (bone == null || returnDuration <= 0f) return;
        returnFrom = bone.localRotation;
        returnTimer = 0f;
    }

    void Update()
    {
        if (returnTimer < 0f || bone == null) return;
        returnTimer += Time.deltaTime;
        float t = Mathf.Clamp01(returnTimer / returnDuration);
        bone.localRotation = Quaternion.Slerp(returnFrom, restRotation, t * t * (3f - 2f * t));
        if (t >= 1f)
        {
            returnTimer = -1f;
            yaw = 0f;
            pitch = 0f;
        }
    }
}
