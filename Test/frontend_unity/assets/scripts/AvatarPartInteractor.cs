using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;

/// <summary>
/// Routes left mouse drags to a body part when the pointer starts on one, and leaves the
/// drag to the orbit camera otherwise.
///
/// Comparison mode puts two avatars in the same place and tells them apart with layers and a
/// split screen, so the ray has to come from the camera the pointer is over and has to be
/// limited to what that camera can actually see.
/// </summary>
public class AvatarPartInteractor : MonoBehaviour
{
    public Camera targetCamera;
    public AvatarOrbitCamera orbitCamera;

    AvatarPart active;
    AvatarOrbitCamera locked;

    void Awake()
    {
        if (targetCamera == null) targetCamera = Camera.main;
        if (orbitCamera == null && targetCamera != null)
            orbitCamera = targetCamera.GetComponent<AvatarOrbitCamera>();
    }

    void Update()
    {
        Mouse mouse = Mouse.current;
        if (mouse == null) return;

        if (mouse.leftButton.wasPressedThisFrame && !PointerOverUI())
            Begin(mouse.position.ReadValue());

        if (active != null && mouse.leftButton.isPressed)
            active.Drag(mouse.delta.ReadValue());

        if (mouse.leftButton.wasReleasedThisFrame && active != null)
            End();
    }

    void Begin(Vector2 screenPosition)
    {
        Camera source = Resolve(screenPosition);
        if (source == null) return;

        Ray ray = source.ScreenPointToRay(screenPosition);
        if (!Physics.Raycast(ray, out RaycastHit hit, 1000f, source.cullingMask)) return;

        AvatarPart part = hit.collider.GetComponent<AvatarPart>();
        if (part == null) return;

        active = part;
        locked = source.GetComponent<AvatarOrbitCamera>();
        if (locked != null) locked.InputLocked = true;
    }

    void End()
    {
        active.Release();
        active = null;
        if (locked != null) locked.InputLocked = false;
        locked = null;
    }

    Camera Resolve(Vector2 screenPosition)
    {
        Camera best = null;
        foreach (Camera candidate in Camera.allCameras)
        {
            if (!candidate.pixelRect.Contains(screenPosition)) continue;
            if (best == null || candidate.depth > best.depth) best = candidate;
        }
        if (best != null) return best;
        if (targetCamera == null) targetCamera = Camera.main;
        return targetCamera;
    }

    static bool PointerOverUI()
    {
        return EventSystem.current != null && EventSystem.current.IsPointerOverGameObject();
    }

    void OnDisable()
    {
        if (active != null) End();
    }
}
