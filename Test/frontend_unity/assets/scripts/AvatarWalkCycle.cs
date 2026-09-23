using UnityEngine;

/// <summary>
/// Walks the avatar on the spot.
///
/// The reconstruction gives us one rigid segment per leg and no knee, so this follows the compass
/// gait model used for passive walkers: the body rides over the planted leg as if over a spoke,
/// and the pelvis drops by exactly what the swing costs in height. Without that drop the standing
/// foot would leave the ground every time the legs spread.
///
/// The legs of a reconstructed politician are short, since the joint sits below the knee, so most
/// of what reads as walking comes from the arms and the torso rather than from the stride itself.
/// </summary>
public class AvatarWalkCycle : AvatarMotion
{
    [Tooltip("Degrees a leg swings forward and back from the hip.")]
    public float legSwing = 14f;

    [Tooltip("Degrees an arm swings, against the leg on the same side.")]
    public float armSwing = 16f;

    [Tooltip("Degrees the shoulders turn against the hips.")]
    public float torsoTwist = 4f;

    [Tooltip("Degrees the head turns back, to keep it facing where the avatar walks.")]
    public float headSteady = 2f;

    Vector3 rootRest;
    bool ridesRoot;

    protected override float DefaultCycle => 1.1f;

    protected override void Compose()
    {
        Drive(rig.legLeft, Vector3.right, legSwing, 0f);
        Drive(rig.legRight, Vector3.right, legSwing, Mathf.PI);

        // An arm swings against the leg on its own side. Matching them instead reads as a march.
        Drive(rig.armLeft, Vector3.right, armSwing, Mathf.PI);
        Drive(rig.armRight, Vector3.right, armSwing, 0f);

        Drive(rig.spine, Vector3.up, torsoTwist, Mathf.PI);
        Drive(rig.head, Vector3.up, headSteady, 0f);

        ridesRoot = rig.root != null && rig.landmarks.legLength > 0f;
        if (ridesRoot) rootRest = rig.root.localPosition;
    }

    protected override void Advance(float radians)
    {
        if (!ridesRoot) return;

        // Both legs are the same length, so it does not matter which one is currently planted:
        // the height it costs depends only on how far it has swung away from vertical.
        float legAngle = Mathf.Sin(radians) * legSwing * Mathf.Deg2Rad;
        float drop = rig.landmarks.legLength * (1f - Mathf.Cos(legAngle));
        rig.root.localPosition = rootRest - new Vector3(0f, drop, 0f);
    }

    protected override void Released()
    {
        if (ridesRoot) rig.root.localPosition = rootRest;
    }
}
