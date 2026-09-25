using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Turns a static reconstructed mesh into a skinned one so individual body parts can move.
/// TripoSR returns a single unrigged mesh, so the joints are located by scanning horizontal
/// cross sections instead of relying on fixed body proportions.
///
/// The reconstruction arrives as two glTF primitives with different vertex layouts (vertex
/// colours and a front projected texture), which glTFast instantiates as separate renderers.
/// All of them are skinned to one shared skeleton so the layers keep moving together.
/// </summary>
public class AvatarRig : MonoBehaviour
{
    public Transform root;
    public Transform spine;
    public Transform head;
    public Transform armLeft;
    public Transform armRight;
    public Transform legLeft;
    public Transform legRight;

    [Tooltip("Height fraction searched for the narrowest slice when locating the neck.")]
    public Vector2 neckSearchBand = new Vector2(0.62f, 0.95f);

    [Tooltip("Vertical blend distance around the neck, as a fraction of head height.")]
    public float neckBlend = 0.5f;

    [Tooltip("Torso half width is estimated from the hips and scaled by this before arms start.")]
    public float torsoWidthScale = 1.15f;

    [Tooltip("Horizontal blend distance where torso weights fade into arm weights.")]
    public float armBlend = 0.04f;

    [Tooltip("Vertical blend distance around the pelvis, as a fraction of body height.")]
    public float pelvisBlend = 0.08f;

    [Tooltip("Shortest separated leg section that still allows the legs to be split, " +
             "as a fraction of body height.")]
    public float minLegSpan = 0.08f;

    const int SliceCount = 100;

    public struct Landmarks
    {
        public float neckY;
        public float shoulderY;
        public float armBottomY;
        public float chestY;
        public float hipY;
        public float bodyHeight;
        public float torsoHalfWidth;
        public bool legsSplit;
        public float legHalfOffset;
        public float crotchHalfGap;
        public float legLength;
        public Bounds headBounds;
        public Bounds armLeftBounds;
        public Bounds armRightBounds;
        public Bounds torsoBounds;
        public Bounds legLeftBounds;
        public Bounds legRightBounds;
    }

    public Landmarks landmarks { get; private set; }

    public static AvatarRig Build(GameObject avatar)
    {
        if (avatar == null) return null;

        List<MeshFilter> filters = new List<MeshFilter>();
        foreach (MeshFilter filter in avatar.GetComponentsInChildren<MeshFilter>(true))
        {
            Mesh mesh = filter.sharedMesh;
            if (mesh == null) continue;
            if (!mesh.isReadable)
            {
                Debug.LogWarning($"AvatarRig: mesh '{mesh.name}' is not readable, it stays rigid.");
                continue;
            }
            filters.Add(filter);
        }

        if (filters.Count == 0)
        {
            Debug.LogWarning("AvatarRig: no readable mesh found under the loaded avatar.");
            return null;
        }

        AvatarRig rig = avatar.AddComponent<AvatarRig>();
        rig.Apply(filters);
        return rig;
    }

    void Apply(List<MeshFilter> filters)
    {
        Transform space = transform;

        // Analysis happens in the avatar's own space so that every renderer contributes to the
        // same silhouette regardless of the transforms glTFast gave it.
        List<Vector3> combined = new List<Vector3>();
        List<Vector3[]> perMesh = new List<Vector3[]>();
        foreach (MeshFilter filter in filters)
        {
            Vector3[] local = filter.sharedMesh.vertices;
            Vector3[] converted = new Vector3[local.Length];
            for (int i = 0; i < local.Length; i++)
                converted[i] = space.InverseTransformPoint(filter.transform.TransformPoint(local[i]));
            perMesh.Add(converted);
            combined.AddRange(converted);
        }

        Landmarks marks = Analyse(combined);
        landmarks = marks;

        Transform rigRoot = new GameObject("Rig").transform;
        rigRoot.SetParent(space, false);

        // The spine pivots at the pelvis, the same height the leg weights blend into the torso.
        // A pivot above that boundary shears the mesh apart when the torso turns.
        root = CreateBone(rigRoot, "Root", space, new Vector3(0f, marks.hipY, 0f));
        spine = CreateBone(root, "Spine", space, new Vector3(0f, marks.hipY, 0f));
        head = CreateBone(spine, "Head", space, new Vector3(0f, marks.neckY, 0f));
        armLeft = CreateBone(spine, "Arm_L", space,
            new Vector3(marks.torsoHalfWidth, marks.shoulderY, 0f));
        armRight = CreateBone(spine, "Arm_R", space,
            new Vector3(-marks.torsoHalfWidth, marks.shoulderY, 0f));

        // The legs hang off the root instead of the spine so that turning the torso leaves them
        // standing. They only appear when the silhouette really splits in two: a long coat or a
        // dress merges both legs into one shape, and moving half of that would tear the mesh.
        Transform[] bones;
        if (marks.legsSplit)
        {
            legLeft = CreateBone(root, "Leg_L", space,
                new Vector3(marks.legHalfOffset, marks.hipY, 0f));
            legRight = CreateBone(root, "Leg_R", space,
                new Vector3(-marks.legHalfOffset, marks.hipY, 0f));
            bones = new[] { root, spine, head, armLeft, armRight, legLeft, legRight };
        }
        else
        {
            bones = new[] { root, spine, head, armLeft, armRight };
        }

        for (int m = 0; m < filters.Count; m++)
            Skin(filters[m], perMesh[m], bones, marks);

        AttachCollider(head, space, marks.headBounds, "Head");
        AttachCollider(armLeft, space, marks.armLeftBounds, "Arm_L");
        AttachCollider(armRight, space, marks.armRightBounds, "Arm_R");
        AttachCollider(spine, space, marks.torsoBounds, "Torso");
        if (marks.legsSplit)
        {
            AttachCollider(legLeft, space, marks.legLeftBounds, "Leg_L");
            AttachCollider(legRight, space, marks.legRightBounds, "Leg_R");
        }

        Debug.Log($"AvatarRig: skinned {filters.Count} renderer(s), neck y={marks.neckY:F4}, " +
                  $"pelvis y={marks.hipY:F4}, head height {marks.headBounds.size.y:F4}, " +
                  (marks.legsSplit
                      ? $"legs split at x=±{marks.legHalfOffset:F4}."
                      : "legs merged into one shape, they stay rigid."));
    }

    void Skin(MeshFilter filter, Vector3[] avatarSpaceVertices, Transform[] bones, Landmarks marks)
    {
        Mesh mesh = filter.sharedMesh;
        Transform meshTransform = filter.transform;

        Matrix4x4[] bindposes = new Matrix4x4[bones.Length];
        for (int i = 0; i < bones.Length; i++)
            bindposes[i] = bones[i].worldToLocalMatrix * meshTransform.localToWorldMatrix;

        mesh.boneWeights = BuildWeights(avatarSpaceVertices, marks);
        mesh.bindposes = bindposes;

        Material[] materials = null;
        MeshRenderer meshRenderer = filter.GetComponent<MeshRenderer>();
        if (meshRenderer != null)
        {
            materials = meshRenderer.sharedMaterials;
            DestroyImmediate(meshRenderer);
        }
        DestroyImmediate(filter);

        SkinnedMeshRenderer skinned = meshTransform.gameObject.AddComponent<SkinnedMeshRenderer>();
        skinned.sharedMesh = mesh;
        skinned.bones = bones;
        skinned.rootBone = bones[0];
        skinned.updateWhenOffscreen = true;
        skinned.quality = SkinQuality.Bone4;
        if (materials != null) skinned.sharedMaterials = materials;
    }

    static Transform CreateBone(Transform parent, string name, Transform space, Vector3 point)
    {
        Transform bone = new GameObject(name).transform;
        bone.SetParent(parent, false);
        bone.position = space.TransformPoint(point);
        bone.rotation = space.rotation;
        return bone;
    }

    /// <summary>
    /// Locates the joints by slicing the mesh along its vertical axis. The neck is the narrowest
    /// slice in the upper body, the shoulders are where the silhouette widens again below it,
    /// and the arms end where the width drops back to the leg width.
    /// </summary>
    Landmarks Analyse(List<Vector3> vertices)
    {
        float minY = float.MaxValue, maxY = float.MinValue;
        for (int i = 0; i < vertices.Count; i++)
        {
            float y = vertices[i].y;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        }

        float height = Mathf.Max(maxY - minY, 1e-5f);
        float[] minX = new float[SliceCount];
        float[] maxX = new float[SliceCount];
        int[] counts = new int[SliceCount];
        for (int s = 0; s < SliceCount; s++)
        {
            minX[s] = float.MaxValue;
            maxX[s] = float.MinValue;
        }

        for (int i = 0; i < vertices.Count; i++)
        {
            int s = Mathf.Clamp((int)((vertices[i].y - minY) / height * SliceCount), 0, SliceCount - 1);
            float x = vertices[i].x;
            if (x < minX[s]) minX[s] = x;
            if (x > maxX[s]) maxX[s] = x;
            counts[s]++;
        }

        float[] width = new float[SliceCount];
        for (int s = 0; s < SliceCount; s++)
            width[s] = counts[s] >= 3 ? maxX[s] - minX[s] : 0f;

        int neckSlice = -1;
        float narrowest = float.MaxValue;
        int bandLow = Mathf.Clamp(Mathf.RoundToInt(neckSearchBand.x * SliceCount), 1, SliceCount - 2);
        int bandHigh = Mathf.Clamp(Mathf.RoundToInt(neckSearchBand.y * SliceCount), bandLow + 1, SliceCount - 1);
        for (int s = bandLow; s <= bandHigh; s++)
        {
            if (width[s] <= 0f || width[s] >= narrowest) continue;
            narrowest = width[s];
            neckSlice = s;
        }
        if (neckSlice < 0) neckSlice = Mathf.RoundToInt(0.82f * SliceCount);

        int shoulderSlice = neckSlice;
        for (int s = neckSlice - 1; s >= bandLow / 2; s--)
        {
            if (width[s] <= 0f) continue;
            if (width[s] > narrowest * 1.6f) { shoulderSlice = s; break; }
        }

        float hipWidth = MedianWidth(width, Mathf.RoundToInt(0.15f * SliceCount), Mathf.RoundToInt(0.30f * SliceCount));

        // The pelvis sits where the two legs merge into one silhouette: scanning downwards, it is
        // the highest slice that still has a gap on the centre line.
        float centreBand = height * 0.02f;
        bool[] hasCentre = new bool[SliceCount];
        for (int i = 0; i < vertices.Count; i++)
        {
            if (Mathf.Abs(vertices[i].x) >= centreBand) continue;
            int s = Mathf.Clamp((int)((vertices[i].y - minY) / height * SliceCount), 0, SliceCount - 1);
            hasCentre[s] = true;
        }
        int hipSlice = Mathf.RoundToInt(0.22f * SliceCount);
        for (int s = Mathf.RoundToInt(0.60f * SliceCount); s >= Mathf.RoundToInt(0.05f * SliceCount); s--)
        {
            if (counts[s] < 5 || hasCentre[s]) continue;
            hipSlice = s;
            break;
        }

        // How far below the pelvis the centre line stays empty decides whether the legs can be
        // driven separately at all. Trousers keep a gap all the way down; a coat closes it after
        // a few slices and the split has to be abandoned.
        int legBottomSlice = hipSlice;
        for (int s = hipSlice; s >= 0; s--)
        {
            if (counts[s] < 5 || hasCentre[s]) break;
            legBottomSlice = s;
        }
        bool legsSplit = hipSlice - legBottomSlice >= Mathf.RoundToInt(minLegSpan * SliceCount);

        float legHalfOffset = 0f;
        float crotchHalfGap = centreBand;
        if (legsSplit)
        {
            // Sorted distances from the centre line describe both numbers at once: the closest
            // ones are the inner edge of the gap, the middle one is where a leg's centre runs.
            float legTopY = minY + (hipSlice + 0.5f) / SliceCount * height;
            float legBottomY = minY + (legBottomSlice + 0.5f) / SliceCount * height;
            List<float> offsets = new List<float>();
            for (int i = 0; i < vertices.Count; i++)
            {
                float y = vertices[i].y;
                if (y > legTopY || y < legBottomY) continue;
                offsets.Add(Mathf.Abs(vertices[i].x));
            }
            offsets.Sort();
            if (offsets.Count >= 20)
            {
                crotchHalfGap = Mathf.Max(offsets[offsets.Count / 20], centreBand);
                legHalfOffset = offsets[offsets.Count / 2];
            }
            else legsSplit = false;
        }

        int armBottomSlice = hipSlice;
        float steepest = 0f;
        int scanLow = Mathf.RoundToInt(0.15f * SliceCount);
        int scanHigh = Mathf.RoundToInt(0.60f * SliceCount);
        for (int s = scanLow; s <= scanHigh; s++)
        {
            if (width[s] <= 0f || width[s + 1] <= 0f) continue;
            float drop = width[s + 1] - width[s];
            if (drop > steepest) { steepest = drop; armBottomSlice = s; }
        }

        float SliceToY(int s) => minY + (s + 0.5f) / SliceCount * height;

        Landmarks marks = new Landmarks
        {
            neckY = SliceToY(neckSlice),
            shoulderY = SliceToY(shoulderSlice),
            armBottomY = SliceToY(armBottomSlice),
            hipY = SliceToY(hipSlice),
            bodyHeight = height,
            torsoHalfWidth = Mathf.Max(hipWidth * 0.5f * torsoWidthScale, 1e-4f),
            legsSplit = legsSplit,
            legHalfOffset = legHalfOffset,
            crotchHalfGap = crotchHalfGap
        };
        marks.chestY = Mathf.Lerp(marks.hipY, marks.shoulderY, 0.7f);

        marks.headBounds = RegionBounds(vertices, v => v.y >= marks.neckY);
        marks.armLeftBounds = RegionBounds(vertices,
            v => v.y > marks.armBottomY && v.y < marks.shoulderY && v.x > marks.torsoHalfWidth);
        marks.armRightBounds = RegionBounds(vertices,
            v => v.y > marks.armBottomY && v.y < marks.shoulderY && v.x < -marks.torsoHalfWidth);
        marks.torsoBounds = RegionBounds(vertices,
            v => v.y < marks.neckY && v.y > marks.hipY && Mathf.Abs(v.x) <= marks.torsoHalfWidth);
        if (marks.legsSplit)
        {
            marks.legLeftBounds = RegionBounds(vertices,
                v => v.y < marks.hipY && v.x > marks.crotchHalfGap);
            marks.legRightBounds = RegionBounds(vertices,
                v => v.y < marks.hipY && v.x < -marks.crotchHalfGap);

            // Distance from the joint down to the sole, which is what a swing costs in height.
            marks.legLength = marks.hipY -
                Mathf.Min(marks.legLeftBounds.min.y, marks.legRightBounds.min.y);
        }
        return marks;
    }

    static float MedianWidth(float[] width, int from, int to)
    {
        List<float> values = new List<float>();
        for (int s = Mathf.Max(from, 0); s <= Mathf.Min(to, width.Length - 1); s++)
            if (width[s] > 0f) values.Add(width[s]);
        if (values.Count == 0) return 0.2f;
        values.Sort();
        return values[values.Count / 2];
    }

    static Bounds RegionBounds(List<Vector3> vertices, System.Func<Vector3, bool> inside)
    {
        bool any = false;
        Bounds bounds = new Bounds();
        for (int i = 0; i < vertices.Count; i++)
        {
            if (!inside(vertices[i])) continue;
            if (!any) { bounds = new Bounds(vertices[i], Vector3.zero); any = true; }
            else bounds.Encapsulate(vertices[i]);
        }
        return bounds;
    }

    BoneWeight[] BuildWeights(Vector3[] vertices, Landmarks marks)
    {
        float headHeight = Mathf.Max(marks.headBounds.size.y, 1e-4f);
        float blend = Mathf.Max(headHeight * neckBlend, 1e-4f);
        float pelvisBand = Mathf.Max(marks.bodyHeight * pelvisBlend, 1e-4f);
        float crotchBand = Mathf.Max(marks.crotchHalfGap, 1e-4f);
        BoneWeight[] weights = new BoneWeight[vertices.Length];

        for (int i = 0; i < vertices.Length; i++)
        {
            Vector3 v = vertices[i];
            float headAmount = SmoothStep(marks.neckY - blend, marks.neckY + blend, v.y);

            float armAmount = 0f;
            if (headAmount < 0.5f && v.y > marks.armBottomY && v.y < marks.shoulderY)
            {
                armAmount = SmoothStep(marks.torsoHalfWidth,
                    marks.torsoHalfWidth + Mathf.Max(armBlend, 1e-4f), Mathf.Abs(v.x));
                armAmount *= 1f - headAmount;
            }

            if (armAmount > 0f)
            {
                weights[i] = Pack(v.x > 0f ? 3 : 4, armAmount, 1, 1f - armAmount, 0, 0f);
                continue;
            }

            if (headAmount > 0f)
            {
                weights[i] = Pack(2, headAmount, 1, 1f - headAmount, 0, 0f);
                continue;
            }

            // Legs fade into the torso across the pelvis instead of switching bone at a
            // single height, which would tear the mesh open as soon as the torso moves.
            float upper = SmoothStep(marks.hipY - pelvisBand, marks.hipY + pelvisBand, v.y);
            if (!marks.legsSplit)
            {
                weights[i] = Pack(1, upper, 0, 1f - upper, 0, 0f);
                continue;
            }

            // Whatever the torso does not claim goes to the leg the vertex belongs to. The
            // crossover spans the gap between the legs, so the inner faces blend instead of
            // snapping from one leg to the other.
            float side = SmoothStep(-crotchBand, crotchBand, v.x);
            weights[i] = Pack(1, upper, 5, (1f - upper) * side, 6, (1f - upper) * (1f - side));
        }
        return weights;
    }

    /// <summary>
    /// Sorts up to three influences into the descending order Unity expects for a bone weight.
    /// </summary>
    static BoneWeight Pack(int index0, float weight0, int index1, float weight1,
                           int index2, float weight2)
    {
        if (weight1 < weight2)
        {
            (index1, index2) = (index2, index1);
            (weight1, weight2) = (weight2, weight1);
        }
        if (weight0 < weight1)
        {
            (index0, index1) = (index1, index0);
            (weight0, weight1) = (weight1, weight0);
        }
        if (weight1 < weight2)
        {
            (index1, index2) = (index2, index1);
            (weight1, weight2) = (weight2, weight1);
        }

        return new BoneWeight
        {
            boneIndex0 = index0,
            weight0 = weight0,
            boneIndex1 = weight1 > 0f ? index1 : 0,
            weight1 = Mathf.Max(weight1, 0f),
            boneIndex2 = weight2 > 0f ? index2 : 0,
            weight2 = Mathf.Max(weight2, 0f)
        };
    }

    static float SmoothStep(float from, float to, float value)
    {
        if (to - from <= 1e-6f) return value >= to ? 1f : 0f;
        float t = Mathf.Clamp01((value - from) / (to - from));
        return t * t * (3f - 2f * t);
    }

    void AttachCollider(Transform bone, Transform space, Bounds bounds, string label)
    {
        if (bone == null || bounds.size == Vector3.zero) return;

        GameObject holder = new GameObject(label + "_Hit");
        holder.transform.SetParent(bone, false);
        holder.transform.position = space.TransformPoint(bounds.center);
        holder.transform.rotation = bone.rotation;

        // The bones carry the avatar's own scale, so the avatar-space size can be used directly.
        holder.AddComponent<BoxCollider>().size = bounds.size;
        holder.AddComponent<AvatarPart>().Initialize(bone, label);
    }
}
