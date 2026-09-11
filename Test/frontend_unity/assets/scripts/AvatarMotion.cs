using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Shared plumbing for the cyclic motions that play on a rigged avatar. Every channel drives one
/// bone with a sine, and yields that bone the moment someone drags the matching
/// <see cref="AvatarPart"/>, so a pose set by hand always wins over the animation.
///
/// Enabling a motion composes its channels and disabling it puts the bones back, which makes the
/// components safe to switch between at runtime.
/// </summary>
[RequireComponent(typeof(AvatarRig))]
public abstract class AvatarMotion : MonoBehaviour
{
    [Tooltip("Seconds for one full cycle. Left at zero, the motion picks its own pace.")]
    public float cycle;

    protected struct Channel
    {
        public AvatarPart part;
        public Vector3 axis;
        public float amplitude;
        public float phase;
    }

    protected AvatarRig rig;

    readonly List<Channel> channels = new List<Channel>();
    float elapsed;

    /// <summary>The pace this motion runs at unless <see cref="cycle"/> has been set by hand.</summary>
    protected abstract float DefaultCycle { get; }

    /// <summary>Declares the channels this motion drives, by calling <see cref="Drive"/>.</summary>
    protected abstract void Compose();

    /// <summary>Runs each frame after the channels, for motion that is not a bone rotation.</summary>
    protected virtual void Advance(float radians) { }

    /// <summary>Undoes anything <see cref="Advance"/> changed, when the motion is switched off.</summary>
    protected virtual void Released() { }

    protected void Drive(Transform bone, Vector3 axis, float amplitude, float phase)
    {
        if (bone == null || amplitude <= 0f) return;

        AvatarPart part = Find(bone);
        if (part == null) return;

        channels.Add(new Channel { part = part, axis = axis, amplitude = amplitude, phase = phase });
    }

    AvatarPart Find(Transform bone)
    {
        foreach (AvatarPart part in GetComponentsInChildren<AvatarPart>(true))
            if (part.bone == bone) return part;
        return null;
    }

    void OnEnable()
    {
        rig = GetComponent<AvatarRig>();
        if (cycle <= 0f) cycle = DefaultCycle;
        channels.Clear();
        elapsed = 0f;
        Compose();
    }

    void OnDisable()
    {
        foreach (Channel channel in channels)
            if (channel.part != null && channel.part.bone != null && !channel.part.Engaged)
                channel.part.bone.localRotation = channel.part.RestRotation;

        channels.Clear();
        Released();
    }

    void LateUpdate()
    {
        if (channels.Count == 0 || cycle <= 0f) return;

        elapsed += Time.deltaTime;
        float radians = elapsed / cycle * Mathf.PI * 2f;

        for (int i = 0; i < channels.Count; i++)
        {
            Channel channel = channels[i];
            if (channel.part.Engaged) continue;

            float angle = Mathf.Sin(radians + channel.phase) * channel.amplitude;
            channel.part.bone.localRotation =
                channel.part.RestRotation * Quaternion.AngleAxis(angle, channel.axis);
        }

        Advance(radians);
    }
}
