import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from requests.adapters import HTTPAdapter, Retry
from PIL import Image
import os

def images_to_pdf(folder_path, output_pdf_path):
    # Get all JPG files sorted by name (page)
    images = sorted([f for f in os.listdir(folder_path) if f.endswith(".jpg")])
    if not images:
        print(f"⚠️ No images found in {folder_path} to create the PDF.")
        return

    image_list = []
    for img_name in images:
        img_path = os.path.join(folder_path, img_name)
        img = Image.open(img_path).convert("RGB")  # Convert to RGB for PDF
        image_list.append(img)

    # Save the first image and append the rest as pages
    first_image = image_list.pop(0)
    first_image.save(output_pdf_path, save_all=True, append_images=image_list)
    print(f"📄 PDF created at: {output_pdf_path}")


# Reutilizamos una sesión con reintentos
session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("http://", adapter)
session.mount("https://", adapter)

def get_all_chapters_by_languages(manga_id, languages):
    chapters = []
    for lang in languages:
        print(f"📅 Getting chapters in language '{lang}'...")
        url = "https://api.mangadex.org/chapter"
        offset = 0
        limit = 100  # The API allows a maximum of 100 chapters per request

        while True:
            params = {
                "manga": manga_id,
                "translatedLanguage[]": lang,
                "order[chapter]": "asc",
                "limit": limit,
                "offset": offset,
            }

            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json().get("data", [])
                print(f"   🔹 {len(data)} chapters found at offset {offset}")
                chapters.extend(data)
                if len(data) < limit:
                    break
                offset += limit
                time.sleep(0.5)  # Wait half a second between requests to avoid overloading the server
            except requests.exceptions.HTTPError as e:
                print(f"❌ HTTP Error {resp.status_code} for language '{lang}': {e}")
                break
            except requests.exceptions.RequestException as e:
                print(f"❌ Network error while getting chapters in language '{lang}': {e}")
                break
            except Exception as e:
                print(f"❌ Unexpected error in language '{lang}': {e}")
                break

    return chapters



def group_best_chapters(chapters, preferred_languages):
    chapter_map = defaultdict(list)

    for chapter in chapters:
        chapter_number = chapter["attributes"].get("chapter", "0")
        lang = chapter["attributes"]["translatedLanguage"]
        chapter_map[chapter_number].append((lang, chapter))

    selected_chapters = []
    for ch_number in sorted(
        [k for k in chapter_map.keys() if k is not None],
        key=lambda x: float(x) if isinstance(x, str) and x.replace('.', '', 1).isdigit() else float('inf')
    ):
        for pref_lang in preferred_languages:
            for lang, chapter in chapter_map[ch_number]:
                if lang == pref_lang:
                    selected_chapters.append(chapter)
                    title = chapter["attributes"].get("title", "No title")
                    print(f"🗂️  Chapter {ch_number} selected in language '{lang}' - {title}")
                    break
            else:
                continue
            break

    return selected_chapters


def search_manga(title):
    url = "https://api.mangadex.org/manga"
    params = {"title": title, "limit": 10}
    resp = requests.get(url, params=params)
    return resp.json().get("data", [])

def get_image_urls(chapter_id):
    url = f"https://api.mangadex.org/at-home/server/{chapter_id}"
    resp = requests.get(url)
    json = resp.json()
    base_url = json["baseUrl"]
    chapter_data = json["chapter"]
    hash = chapter_data["hash"]
    pages = chapter_data["data"]
    return [f"{base_url}/data/{hash}/{page}" for page in pages]

def download_image(url, folder_path, index):
    file_path = os.path.join(folder_path, f"{index:03d}.jpg")
    if os.path.exists(file_path):
        return
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(response.content)
            print(f"  📅 Page {index} downloaded.")
            break
        except (requests.exceptions.RequestException, requests.exceptions.ChunkedEncodingError) as e:
            print(f"    ⚠️ Error downloading page {index} (attempt {attempt}): {e}")
            if attempt == max_retries:
                print(f"    ❌ Failed to download page {index} after {max_retries} attempts.")

def download_chapter_images(image_urls, folder_path):
    os.makedirs(folder_path, exist_ok=True)
    existing_pages = len([f for f in os.listdir(folder_path) if f.endswith(".jpg")])
    if existing_pages >= len(image_urls):
        print("  ✅ Chapter already fully downloaded.")
        return

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(download_image, url, folder_path, i) for i, url in enumerate(image_urls, 1)]
        for future in as_completed(futures):
            future.result()

def parse_chapter_selection(selection_text):
    result = set()
    parts = selection_text.split(",")
    for part in parts:
        if "-" in part:
            start, end = part.split("-")
            try:
                start = float(start)
                end = float(end)
                current = start
                while current <= end:
                    result.add(str(int(current)) if current.is_integer() else str(current))
                    current += 1 if current.is_integer() and end.is_integer() else 0.1
                    current = round(current, 1)
            except ValueError:
                continue
        else:
            result.add(part.strip())
    return result

def main():
    print("🔎 Search manga in MangaDex")
    title = input("Enter the manga title: ").strip()
    results = search_manga(title)

    if not results:
        print("❌ No results found.")
        return

    print("\nResults found:")
    for i, manga in enumerate(results, 1):
        title_data = manga["attributes"]["title"]
        title_str = title_data.get("es") or title_data.get("es-la") or title_data.get("en") or "Unknown title"
        print(f"{i}. {title_str}")

    selection = int(input("Select a manga number: ")) - 1
    selected_manga = results[selection]
    manga_id = selected_manga["id"]
    manga_title = selected_manga["attributes"]["title"].get("en", "manga").replace(" ", "_")

    available_langs = selected_manga["attributes"].get("availableTranslatedLanguages", [])
    print(f"🌐 Available languages for this manga: {', '.join(available_langs)}")
    selected_langs = input("Select languages separated by comma (e.g.: es,es-la,en): ").strip().split(",")
    selected_langs = [lang.strip() for lang in selected_langs if lang.strip() in available_langs]

    if not selected_langs:
        print("❌ No valid languages selected.")
        return

    print("\n📅 Getting chapters in selected languages...")
    all_chapters = get_all_chapters_by_languages(manga_id, selected_langs)
    if not all_chapters:
        print("❌ No chapters found.")
        return

    chapters = group_best_chapters(all_chapters, selected_langs)
    chapter_map = {chapter["attributes"]["chapter"]: chapter for chapter in chapters if chapter["attributes"].get("chapter")}

    print("\nAvailable chapters:")
    for number in sorted(chapter_map.keys(), key=lambda x: float(x) if x.replace(".", "", 1).isdigit() else x):
        title = chapter_map[number]["attributes"].get("title", "")
        print(f"- Chapter {number}: {title}")

    selection = input("Enter chapters (e.g.: 5,6,10-15) or 'all': ").strip().lower()
    if selection == "all":
        selected_numbers = list(chapter_map.keys())
    else:
        selected_numbers = parse_chapter_selection(selection)
        selected_numbers = [num for num in selected_numbers if num in chapter_map]

    if not selected_numbers:
        print("❌ No valid chapters found in selection.")
        return

    for number in selected_numbers:
        chapter = chapter_map[number]
        chapter_id = chapter["id"]
        chapter_title = chapter["attributes"].get("title", "No title")
        print(f"\n⬇️  Downloading chapter {number}: {chapter_title}")
        image_urls = get_image_urls(chapter_id)
        folder = os.path.join("mangas", manga_title, f"chapter_{number}")
        download_chapter_images(image_urls, folder)
        print(f"✅ Chapter {number} saved in '{folder}'")

        # Convert images to PDF
        pdf_path = os.path.join("mangas", manga_title, f"chapter_{number}-{chapter_title}.pdf")
        images_to_pdf(folder, pdf_path)

    print("✅ Process completed.")

if __name__ == "__main__":
    main()