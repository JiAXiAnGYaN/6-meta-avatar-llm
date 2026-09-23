using UnityEngine;

/// <summary>
/// Keeps a standing avatar breathing a little so it does not read as a statue. The weight shifts
/// slowly from one leg to the other while the torso leans along and the head drifts back
/// against it.
///
/// The amounts are deliberately tiny. The torso pivots at the pelvis, so a degree there travels
/// about two centimetres by the time it reaches the head, and anything that reads clearly as
/// movement while standing still looks like swaying rather than breathing. Setting every
/// amplitude to zero leaves the avatar completely still.
/// </summary>
public class AvatarIdleMotion : AvatarMotion
{
    [Tooltip("Degrees a leg swings through, measured at the hip.")]
    public float legSwing = 1.5f;

    [Tooltip("Degrees the torso leans towards the loaded leg. This one carries the whole body, " +
             "so it is the amount that decides how restless the avatar looks.")]
    public float torsoSway = 0.6f;

    [Tooltip("Degrees the head drifts against the torso.")]
    public float headDrift = 0.4f;

    protected override float DefaultCycle => 6f;

    protected override void Compose()
    {
        // The legs run half a cycle apart, which is what makes it look like weight moving across
        // rather than both legs drifting the same way.
        Drive(rig.legLeft, Vector3.right, legSwing, 0f);
        Drive(rig.legRight, Vector3.right, legSwing, Mathf.PI);
        Drive(rig.spine, Vector3.forward, torsoSway, 0f);
        Drive(rig.head, Vector3.forward, headDrift, Mathf.PI);
    }
}
