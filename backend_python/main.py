import os
import json
import sqlite3
from datetime import datetime, timezone
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import uvicorn

app = FastAPI(title="Meta-Avatar-LLM API")
# Key nicht hart kodieren - aus Umgebungsvariable lesen (nicht ins Repo committen!)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "replace with actual api key")
client = OpenAI(api_key=OPENAI_API_KEY)

# Wikimedia lehnt Requests ohne User-Agent ab (kein JSON zurueck) -> Pflicht-Header
WIKI_HEADERS = {"User-Agent": "Meta-Avatar-LLM/0.1 (Goethe-Uni course project; contact jiawei021121@gmail.com)"}

class AvatarFeatures(BaseModel):
    name: str
    gender: str
    age_estimate: int
    skin_color_hex: str          # FIX: war int - ist ein Hex-String wie "#FCD1B4"
    hair_color_hex: str
    wardrobe_suit: str
    wardrobe_hair: str           # FIX: fehlte - wird in Prompt/Fallback/Unity genutzt, sonst von response_model gefiltert
    wardrobe_glasses: str
    wardrobe_legs: str           # NEU: Unterteil (Hose) - fehlte komplett -> Avatare wurden ohne Hose gerendert. Slot "Legs" in Unity.
    # --- UMA DNA (Namen MUESSEN exakt den UMA HumanMale/Female DNA-Convertern entsprechen; C# macht dna.TryGetValue(<name>)) ---
    # Default 0.5 (= UMA-Neutralwert): wenn das LLM ein Feld auslaesst, bleibt der Avatar an der Stelle neutral statt zu crashen.
    # FIX(A-2): dna_jawWidth entfernt - diesen DNA-Namen gibt es in UMA nicht (TryGetValue schlug still fehl). Ersetzt durch jawsSize/mandibleSize.
    # Koerper / Kopf
    dna_height: float = 0.5
    dna_headSize: float = 0.5
    dna_headWidth: float = 0.5
    dna_neckThickness: float = 0.5
    dna_belly: float = 0.5
    dna_upperWeight: float = 0.5
    # Gesicht
    dna_foreheadSize: float = 0.5
    dna_cheekSize: float = 0.5
    dna_chinSize: float = 0.5
    dna_jawsSize: float = 0.5
    dna_mandibleSize: float = 0.5
    dna_mouthSize: float = 0.5
    dna_lipsSize: float = 0.5
    dna_noseSize: float = 0.5
    dna_noseWidth: float = 0.5
    dna_noseCurve: float = 0.5
    dna_eyeSize: float = 0.5
    dna_eyeSpacing: float = 0.5
    dna_earsSize: float = 0.5
    portrait_url: str = ""       # NEU: URL des offiziellen Portraits (Wikipedia-Thumbnail); wird an das LLM als Bild uebergeben und fuer die spaetere DB gespeichert

# ===================== SQLite-Persistenz (Block B) =====================
# Zweck: Avatare cachen (dient UC-02 Massengenerierung -> nicht jedes Mal Wikipedia+LLM) und
# manuelle Korrekturen speichern (UC-03). Nur Standardbibliothek, keine neue Abhaengigkeit.
# Die Tabelle wird DYNAMISCH aus AvatarFeatures.model_fields erzeugt: neue DNA/Felder brauchen
# nur die Modellklasse zu aendern (gleiche Philosophie wie der pydantic-Default in Block A-2).
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatars.db")

# Zusatzspalten, die NICHT im LLM-Schema stehen (Metadaten der DB)
DB_META_COLUMNS = ["is_manually_edited", "updated_at"]

def _sqlite_type(annotation) -> str:
    if annotation is int:
        return "INTEGER"
    if annotation is float:
        return "REAL"
    return "TEXT"

def init_db():
    cols = []
    for fname, field in AvatarFeatures.model_fields.items():
        coltype = _sqlite_type(field.annotation)
        if fname == "name":
            cols.append(f'"{fname}" {coltype} PRIMARY KEY')
        else:
            cols.append(f'"{fname}" {coltype}')
    cols.append('"is_manually_edited" INTEGER DEFAULT 0')  # 1 = von Hand korrigiert (UC-03)
    cols.append('"updated_at" TEXT')                        # ISO-8601 UTC
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f'CREATE TABLE IF NOT EXISTS avatars ({", ".join(cols)})')
    conn.commit()
    conn.close()

def get_avatar_from_db(name: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM avatars WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_avatar_to_db(features: dict, is_manually_edited: bool = False):
    field_names = list(AvatarFeatures.model_fields.keys())
    cols = field_names + DB_META_COLUMNS
    values = [features.get(f) for f in field_names]
    values += [1 if is_manually_edited else 0, datetime.now(timezone.utc).isoformat()]
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(f'"{c}"' for c in cols)
    conn = sqlite3.connect(DB_PATH)
    # INSERT OR REPLACE: name ist Primaerschluessel -> vorhandener Datensatz wird ueberschrieben (Upsert)
    conn.execute(f"INSERT OR REPLACE INTO avatars ({col_list}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()

def list_avatars_from_db():
    # Kompakte Liste fuer Uebersicht/Batch (UC-02): nicht alle 27 Spalten, nur das Wesentliche.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT name, gender, age_estimate, portrait_url, is_manually_edited, updated_at "
        "FROM avatars ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

init_db()  # Tabelle beim Start sicherstellen
# =======================================================================

def get_wikipedia_info(name: str) -> str:
    url = "https://de.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts",
        "exintro": True,
        "explaintext": True,
        "titles": name,
        "format": "json"
    }
    try:
        response = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=10)
        pages = response.json()["query"]["pages"]
        for page_id in pages:
            if page_id == "-1":               # FIX: == statt = (Seite nicht gefunden)
                return "Not available in WIKI."
            return pages[page_id].get("extract", "")
    except Exception as e:
        return f"Failed to load WIKI: {e}"

def get_wikipedia_image(name: str) -> str:
    # NEU: holt das offizielle Portrait-Thumbnail von Wikipedia, damit das LLM das Gesicht "sehen" kann.
    # Nur oeffentliche Bilder (DSGVO-konform). Leerer String, wenn kein Bild vorhanden ist.
    url = "https://de.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": 500,          # 500px reicht fuer Gesichtsanalyse, spart Tokens
        "titles": name,
        "format": "json"
    }
    try:
        response = requests.get(url, params=params, headers=WIKI_HEADERS, timeout=10)
        pages = response.json()["query"]["pages"]
        for page_id in pages:
            if page_id == "-1":                       # Seite nicht gefunden
                return ""
            thumbnail = pages[page_id].get("thumbnail")
            if thumbnail:
                return thumbnail.get("source", "")
        return ""
    except Exception as e:
        print(f"Failed to load portrait: {e}")
        return ""

def ask_features(name: str, context_text: str, portrait_url: str = "") -> dict:
    system_prompt = """
    You are an AI assistant in a virtual reality lab. Your task is to extract the physical characteristics of this German politician for use in generating a 3D avatar.
    If an official portrait IMAGE is provided, treat it as the PRIMARY source: look at the face and read off skin tone, hair color, whether the person wears glasses,
    and the facial proportions (head/jaw/nose/cheeks/chin etc.) directly from the picture. Use the background text only to fill gaps (e.g. age). Never leave a facial
    DNA value at the default 0.5 if the image lets you judge it - the whole point is a recognizable, individual face.
    The output must be strictly in pure JSON format; do not include any Markdown markup such as ```json.
    The following fields must be included:
    "name": string,
    "gender": "Male" or "Female",
    "age_estimate": integer (estimated age in years, e.g. 65),
    "skin_color_hex": "Hex color (e.g., #FCD1B4 for Caucasian)",
    "hair_color_hex": "Hex color (e.g., #b0b0b0 for gray/silver, #000000 for bald)",
    "wardrobe_suit": "MaleHoodie_Recipe" (if male) or "FemaleTankTop_Recipe" (if female),
    "wardrobe_legs": "MaleJeans" (if male) or "FemalePants1" (if female),
    "wardrobe_hair": "MaleShortHair_Recipe" (if male) or "FemaleLongHair_Recipe" (if female); use "None" if bald,
    "wardrobe_glasses": "None" (glasses assets are not available in the current UMA content, always "None"),
    All DNA values are floats in [0.0, 1.0] where 0.5 = average. Judge EACH one from the FACE in the portrait and be DECISIVE: use the full 0.3-0.7 range so that different people end up looking clearly different. If a feature is even slightly distinctive, move it at least 0.1 away from 0.5. Use exactly 0.5 only when the image truly gives no clue. Never return a face where almost all values sit at ~0.5 - that produces generic, non-recognizable faces.
    Body / head:
    "dna_height": float (0.5 average height, tall ~0.65),
    "dna_headSize": float (0.5 avg, larger head ~0.6),
    "dna_headWidth": float (0.5 avg, broad/round face wider ~0.6, narrow face ~0.4),
    "dna_neckThickness": float (0.5 avg, thick neck of older/heavier men ~0.7),
    "dna_belly": float (0.5 avg, overweight 0.7+),
    "dna_upperWeight": float (0.5 avg upper-body fullness, heavier ~0.65, slim ~0.4),
    Face:
    "dna_foreheadSize": float (0.5 avg, high/large forehead ~0.6, e.g. receding hairline),
    "dna_cheekSize": float (0.5 avg, full/round cheeks ~0.65, gaunt ~0.4),
    "dna_chinSize": float (0.5 avg, prominent chin ~0.65, small/receding ~0.4),
    "dna_jawsSize": float (0.5 avg, wide/square jaw ~0.65, narrow ~0.4),
    "dna_mandibleSize": float (0.5 avg lower-jaw length; long face ~0.6),
    "dna_mouthSize": float (0.5 avg mouth width),
    "dna_lipsSize": float (0.5 avg, full lips ~0.6, thin ~0.4),
    "dna_noseSize": float (0.5 avg, large nose ~0.65),
    "dna_noseWidth": float (0.5 avg, wide nostrils ~0.6, narrow ~0.4),
    "dna_noseCurve": float (0.5 straight bridge, convex/hooked ~0.6, upturned ~0.4),
    "dna_eyeSize": float (0.5 avg eye opening),
    "dna_eyeSpacing": float (0.5 avg, wide-set ~0.6, close-set ~0.4),
    "dna_earsSize": float (0.5 avg ear size)
    """

    user_prompt = f"Target Person: {name}\nReference Text: {context_text}\nPlease output the physical description in JSON format."

    # NEU: multimodaler Content - Text + (optional) Portrait-Bild. gpt-4o kann das Bild direkt "sehen".
    user_content = [{"type": "text", "text": user_prompt}]
    if portrait_url:
        user_content.append({"type": "image_url", "image_url": {"url": portrait_url}})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        temperature=0.1,
        # Erzwingt syntaktisch gueltiges JSON -> kein ```json-Wrapper, keine Fliesstext-Antwort mehr.
        # (Setzt voraus, dass das Wort "json" in den Messages vorkommt - steht im System-Prompt.)
        response_format={"type": "json_object"}
    )

    result_text = (response.choices[0].message.content or "").strip()
    # Defensiv: falls doch ```json ... ``` zurueckkommt (bei json_object eigentlich nicht mehr), entfernen
    if result_text.startswith("```"):
        result_text = result_text.strip("`")
        if result_text.lstrip().lower().startswith("json"):
            result_text = result_text.lstrip()[4:]
    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        # Diagnose: zeigt, was das Modell wirklich geliefert hat (leer? Fliesstext? Refusal?)
        print(f"[ask_features] Keine gueltige JSON-Antwort. Rohtext (erste 300 Zeichen): {result_text[:300]!r}")
        raise

@app.get("/api/avatar", response_model=AvatarFeatures)
async def generate_real_avatar(name: str, refresh: bool = False):
    # Cache-first (Block B): existiert der Avatar schon in der DB, direkt zurueckgeben.
    # ?refresh=true erzwingt Neu-Generierung (verwirft auch eine manuelle Korrektur, is_manually_edited -> 0).
    if not refresh:
        cached = get_avatar_from_db(name)
        if cached:
            print(f"Cache hit: {name} (manually_edited={cached.get('is_manually_edited')})")
            return cached  # response_model filtert Meta-Spalten (is_manually_edited/updated_at) raus

    print("Getting Data")
    wiki_text = get_wikipedia_info(name)
    portrait_url = get_wikipedia_image(name)
    print(f"Portrait: {portrait_url or 'none found'}")
    print("Calling LLM with Data")
    try:
        features_dict = ask_features(name, wiki_text, portrait_url)
        features_dict["portrait_url"] = portrait_url   # von uns gesetzt, nicht vom LLM erfunden
        save_avatar_to_db(features_dict, is_manually_edited=False)  # in DB cachen
        print("Return to Unity")
        return features_dict
    except Exception as e:
        print(f"Load Fail: {e}")
        return {
            "name": name,
            "gender": "Male",
            "age_estimate": 50,
            "skin_color_hex": "#FFD1B3",
            "hair_color_hex": "#555555",
            "wardrobe_suit": "MaleHoodie_Recipe",
            "wardrobe_legs": "MaleJeans",
            "wardrobe_hair": "MaleShortHair_Recipe",
            "wardrobe_glasses": "None",
            # dna_*: bewusst weggelassen -> pydantic-Default 0.5 (neutraler Avatar). So muss beim Erweitern der DNA nur die Modellklasse geaendert werden.
            "portrait_url": portrait_url
        }

@app.put("/api/avatar", response_model=AvatarFeatures)
async def update_avatar(features: AvatarFeatures):
    # UC-03: manuelle Korrektur der LLM-Ausgabe. Der Client schickt die vollstaendigen (korrigierten)
    # Features; wir speichern sie mit is_manually_edited=1, damit ein spaeteres normales GET sie
    # bevorzugt (nicht vom LLM ueberschrieben) zurueckgibt.
    save_avatar_to_db(features.model_dump(), is_manually_edited=True)
    print(f"Manually updated: {features.name}")
    return features

@app.get("/api/avatars")
async def list_avatars():
    # UC-02: Uebersicht aller gecachten Avatare (kompakte Felder). Dient Batch/Parlaments-Szene.
    return list_avatars_from_db()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
