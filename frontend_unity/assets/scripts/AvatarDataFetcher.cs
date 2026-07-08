using System.Collections;
using System.Collections.Generic;  // FIX: fuer Dictionary<string, DnaSetter> (UMA GetDNA)
using System.Text;                 // FIX(A): war "System.text" - Namespaces sind case-sensitive; Encoding.UTF8 lebt hier
using UnityEngine;
using UnityEngine.Networking;
using TMPro;
using UMA.CharacterSystem;
using UMA;

[System.Serializable]
public class AvatarFeatures
{
    public string name;
    public string gender;
    public int age_estimate;          // FIX: doppeltes Feld entfernt (war string + int); Backend liefert int
    public string skin_color_hex;
    public string hair_color_hex;
    public string wardrobe_suit;
    public string wardrobe_hair;
    public string wardrobe_glasses;
    public string wardrobe_legs;   // NEU: Unterteil (Hose), Slot "Legs" - fehlte -> Avatare hatten keine Hose
    // --- UMA DNA: Feldnamen muessen exakt den JSON-Keys entsprechen (JsonUtility matcht per Name).
    //     dna_<X> -> in ApplyFeaturesToUMA wird "<X>" an dna.TryGetValue uebergeben, das MUSS ein echter UMA-DNA-Name sein.
    //     FIX(A-2): dna_jawWidth entfernt (kein gueltiger UMA-DNA-Name, wurde still ignoriert) -> jawsSize/mandibleSize. ---
    public float dna_height;
    public float dna_headSize;
    public float dna_headWidth;
    public float dna_neckThickness;
    public float dna_belly;
    public float dna_upperWeight;
    public float dna_foreheadSize;
    public float dna_cheekSize;
    public float dna_chinSize;
    public float dna_jawsSize;
    public float dna_mandibleSize;
    public float dna_mouthSize;
    public float dna_lipsSize;
    public float dna_noseSize;
    public float dna_noseWidth;
    public float dna_noseCurve;
    public float dna_eyeSize;
    public float dna_eyeSpacing;
    public float dna_earsSize;
}

public class AvatarDataFetcher : MonoBehaviour
{
    [Header("UI")]
    public TMP_InputField nameInputField;
    public TextMeshProUGUI resultText;

    [Header("UMA Model")]
    public DynamicCharacterAvatar umaAvatar;
    private string backendUrl = "http://127.0.0.1:8000/api/avatar";  // FIX: war als Markdown-Link verunstaltet
    private AvatarFeatures currentFeatures;
    public void OnGenerateButtonClicked()
    {
        string targetName = nameInputField.text;
        if(!string.IsNullOrEmpty(targetName))
        {
            StartCoroutine(FetchDataFromBackend(targetName));
        }
    }

    private IEnumerator FetchDataFromBackend(string name)
    {
        resultText.text = "Calling LLM and Fetching Data...";
        string url = $"{backendUrl}?name={UnityWebRequest.EscapeURL(name)}";
        using (UnityWebRequest webRequest = UnityWebRequest.Get(url))
        {
            yield return webRequest.SendWebRequest();

            if (webRequest.result == UnityWebRequest.Result.Success)
            {
                string jsonResponse = webRequest.downloadHandler.text;   // FIX: Tippfehler jsonReponse
                currentFeatures = JsonUtility.FromJson<AvatarFeatures>(jsonResponse);
                resultText.text = $"[Success] Name: {currentFeatures.name}\nAge: {currentFeatures.age_estimate}\nApplying to UMA...";
                ApplyFeaturesToUMA();
            }
            else
            {
                resultText.text = "Failed. Check Server";
                Debug.LogError(webRequest.error);   // FIX: war "Debut"
            }
        }
    }

    private void ApplyFeaturesToUMA()
    {
        if (currentFeatures == null || umaAvatar == null) return;
        string raceName = currentFeatures.gender.ToLower() == "female" ? "HumanFemale": "HumanMale";
        umaAvatar.ChangeRace(raceName);

        if (ColorUtility.TryParseHtmlString(currentFeatures.skin_color_hex, out Color skinCol))
            umaAvatar.SetColor("Skin", skinCol);
        if (ColorUtility.TryParseHtmlString(currentFeatures.hair_color_hex, out Color hairCol))
            umaAvatar.SetColor("Hair", hairCol);
        if (currentFeatures.wardrobe_suit != "None")
            umaAvatar.SetSlot("Chest", currentFeatures.wardrobe_suit);
        if (currentFeatures.wardrobe_legs != "None")
            umaAvatar.SetSlot("Legs", currentFeatures.wardrobe_legs);
        if (currentFeatures.wardrobe_hair != "None")
            umaAvatar.SetSlot("Hair", currentFeatures.wardrobe_hair);
        else
            umaAvatar.ClearSlot("Hair");
        if (currentFeatures.wardrobe_glasses != "None")
            umaAvatar.SetSlot("Face", currentFeatures.wardrobe_glasses);
        else umaAvatar.ClearSlot("Face");

        var dna = umaAvatar.GetDNA();
        if (dna != null)
        {
            // Koerper / Kopf
            SetUMADNA(dna, "height", currentFeatures.dna_height);
            SetUMADNA(dna, "headSize", currentFeatures.dna_headSize);
            SetUMADNA(dna, "headWidth", currentFeatures.dna_headWidth);
            SetUMADNA(dna, "neckThickness", currentFeatures.dna_neckThickness);
            SetUMADNA(dna, "belly", currentFeatures.dna_belly);
            SetUMADNA(dna, "upperWeight", currentFeatures.dna_upperWeight);
            // Gesicht
            SetUMADNA(dna, "foreheadSize", currentFeatures.dna_foreheadSize);
            SetUMADNA(dna, "cheekSize", currentFeatures.dna_cheekSize);
            SetUMADNA(dna, "chinSize", currentFeatures.dna_chinSize);
            SetUMADNA(dna, "jawsSize", currentFeatures.dna_jawsSize);
            SetUMADNA(dna, "mandibleSize", currentFeatures.dna_mandibleSize);
            SetUMADNA(dna, "mouthSize", currentFeatures.dna_mouthSize);
            SetUMADNA(dna, "lipsSize", currentFeatures.dna_lipsSize);
            SetUMADNA(dna, "noseSize", currentFeatures.dna_noseSize);
            SetUMADNA(dna, "noseWidth", currentFeatures.dna_noseWidth);
            SetUMADNA(dna, "noseCurve", currentFeatures.dna_noseCurve);
            SetUMADNA(dna, "eyeSize", currentFeatures.dna_eyeSize);
            SetUMADNA(dna, "eyeSpacing", currentFeatures.dna_eyeSpacing);
            SetUMADNA(dna, "earsSize", currentFeatures.dna_earsSize);
        }

        umaAvatar.BuildCharacter();   // FIX: Leerzeichen im Methodennamen entfernt
        resultText.text += "\nAvatar Generated Completely!";
        Debug.Log("UMA Avatar renewed via LLM data.");
    }

    // FIX: Signatur war UMADnaBase[] - GetDNA() liefert Dictionary<string, DnaSetter>
    private void SetUMADNA(Dictionary<string, DnaSetter> dna, string dnaName, float value)
    {
        if (dna.TryGetValue(dnaName, out var dnaValue))
        {
            dnaValue.Set(value);
        }
    }
}