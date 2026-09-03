using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;

/// <summary>
/// Routes left mouse drags to a body part when the pointer starts on one, and leaves the
/// drag to the orbit camera otherwise.
/// </summary>
public class AvatarPartInteractor : MonoBehaviour
{
    public Camera targetCamera;
    public AvatarOrbitCamera orbitCamera;

    AvatarPart active;

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

        if (targetCamera == null)
        {
            targetCamera = Camera.main;
            if (targetCamera == null) return;
        }

        if (mouse.leftButton.wasPressedThisFrame && !PointerOverUI())
            Begin(mouse.position.ReadValue());

        if (active != null && mouse.leftButton.isPressed)
            active.Drag(mouse.delta.ReadValue());

        if (mouse.leftButton.wasReleasedThisFrame && active != null)
            End();
    }

    void Begin(Vector2 screenPosition)
    {
        Ray ray = targetCamera.ScreenPointToRay(screenPosition);
        if (!Physics.Raycast(ray, out RaycastHit hit, 1000f)) return;

        AvatarPart part = hit.collider.GetComponent<AvatarPart>();
        if (part == null) return;

        active = part;
        if (orbitCamera != null) orbitCamera.InputLocked = true;
    }

    void End()
    {
        active.Release();
        active = null;
        if (orbitCamera != null) orbitCamera.InputLocked = false;
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
