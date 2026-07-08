# Frontend (Unity) — Setup & Run

> ⚠️ **Unity-Version ist verbindlich: Unity 6.0 LTS (6000.0.x).**
> **NICHT** Unity 6.1 / 6.2 / 6.5 oder irgendeinen Tech-Stream-Build verwenden!
> Diese Versionen brechen UMA (EntityId-Migration: `GetInstanceID` / `AssetDatabase.GetAssetPath(int)` /
> `Physics.BakeMesh(int)` sind dort veraltet → UMA-Quellcode kompiliert nicht, Safe Mode).
> Getestet & lauffähig mit **6000.0.78f1**.

## Voraussetzungen

- **Unity 6.0 LTS** (6000.0.78f1 empfohlen), via Unity Hub, mit macOS/Windows-Build-Modul.
- **UMA 2.14f7** — NICHT im Repo (siehe `.gitignore`). Jeder importiert es selbst:
  Asset Store → "UMA 2 - Unity Multipurpose Avatar" (kostenlos) → Package Manager → My Assets → Import.
- **Timeline** — falls Unity beim UMA-Import danach fragt: Package Manager → Unity Registry → Timeline installieren.
- Backend läuft (siehe `../backend_python/`), erreichbar unter `http://127.0.0.1:8000`.

## Erststart nach `git clone`

1. Projekt `frontend_unity/` in **Unity 6.0 LTS** öffnen.
2. **UMA 2.14f7 importieren** (siehe oben). Erst danach lösen sich die UMA-Referenzen in der Szene auf.
3. `Window → TextMeshPro → Import TMP Essential Resources` (falls TMP-Referenzen fehlen).
4. Szene `Assets/Scenes/SampleScene.unity` öffnen.
5. Prüfen, dass in der Hierarchy ein **`UMA_GLIB`**-Objekt existiert (liefert UMA Context + Generator).
   Fehlt es / kommt `Cannot find generator!`: Prefab `Assets/UMA/Getting Started/UMA_GLIB` in die Szene ziehen.
   (NICHT das veraltete `Deprecated/UMA_DCS` nehmen.)
6. Backend starten, dann Play drücken, Abgeordneten-Namen eingeben, Button klicken.

## Hinweise

- `No animation controller supplied` ist eine harmlose Warnung (Avatar steht in T-Pose). Optional
  einen Animator Controller im `DynamicCharacterAvatar` setzen.
- **Verfügbare UMA-Recipes** (nur diese Namen existieren im kostenlosen UMA-Content):
  - Race: `HumanMale` / `HumanFemale`
  - Oberteil (Slot `Chest`): `MaleHoodie_Recipe` / `FemaleTankTop_Recipe`
  - Haare (Slot `Hair`): `MaleShortHair_Recipe` / `FemaleLongHair_Recipe`
  - Brille: **nicht vorhanden** → `wardrobe_glasses` immer `"None"`.
  - Der Backend-Prompt gibt genau diese Namen aus; müssen zwischen Backend & Unity synchron bleiben.
- Kein Anzug / keine Brille im Gratis-Content → für echten Realismus (Abgeordnete im Anzug) später
  ein Business-Wardrobe-Content-Pack für UMA importieren.
