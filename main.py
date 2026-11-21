from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import requests
import re

BASE_URL = "https://new1.bollyflix.tours/"
ALLOWED_HOST = urlparse(BASE_URL).hostname
CATEGORY_PATH_MARKERS = ("/category/", "/genre/", "/tag/")

app = FastAPI(
    title="Movie Metadata API",
    version="1.1.0",
    description="Metadata-only scraper for titles, categories, and poster/featured image URLs.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MetadataBot/1.0; +https://example.org/bot)"
}


def fetch_page(page: int):
    url = BASE_URL if page <= 1 else urljoin(BASE_URL, f"page/{page}/")
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Source site request failed: {exc}")
    return BeautifulSoup(response.text, "html.parser"), url


def clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return re.sub(r"^(download\s+)?", "", text, flags=re.I).strip()


def is_category_link(anchor) -> bool:
    href = (anchor.get("href") or "").lower()
    classes = " ".join(anchor.get("class", [])).lower()
    rel = " ".join(anchor.get("rel", [])).lower()
    return (
        any(marker in href for marker in CATEGORY_PATH_MARKERS)
        or "category" in classes
        or "cat-item" in classes
        or "category" in rel
    )


def extract_categories(card, listing_url: str):
    categories = []
    seen = set()
    if not card:
        return categories

    # Prefer explicit category/taxonomy links found within the listing card.
    for anchor in card.find_all("a", href=True):
        if not is_category_link(anchor):
            continue
        name = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = urljoin(listing_url, anchor.get("href", ""))
        if not name or urlparse(href).hostname != ALLOWED_HOST:
            continue
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            categories.append({"name": name, "url": href})

    # Some WordPress themes expose category names as plain taxonomy labels.
    if not categories:
        for node in card.select(
            '[class*="cat-links"] a, [class*="post-category"] a, '
            '[class*="category"] a, a[rel~="category tag"]'
        ):
            name = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            href = urljoin(listing_url, node.get("href", ""))
            if name and urlparse(href).hostname == ALLOWED_HOST and name.casefold() not in seen:
                seen.add(name.casefold())
                categories.append({"name": name, "url": href})

    return categories


def scrape_listing(page: int):
    soup, listing_url = fetch_page(page)
    results, seen = [], set()

    for heading in soup.select("h1, h2, h3, h4"):
        anchor = heading.find("a", href=True) or heading.find_parent("a", href=True)
        if not anchor:
            continue

        title = clean_title(anchor.get_text(" ", strip=True))
        href = urljoin(listing_url, anchor.get("href", ""))
        if not title or not href or urlparse(href).hostname != ALLOWED_HOST or href in seen:
            continue

        seen.add(href)
        card = heading.find_parent(["article", "li", "div"]) or heading.parent
        img = card.find("img") if card else None
        poster = None
        if img:
            for key in ("data-src", "data-lazy-src", "data-original", "data-srcset", "src"):
                value = img.get(key)
                if value and not value.startswith("data:"):
                    if key == "data-srcset":
                        value = value.split(",")[0].strip().split()[0]
                    poster = urljoin(listing_url, value)
                    break
            if not poster and img.get("srcset"):
                poster = urljoin(listing_url, img["srcset"].split(",")[0].strip().split()[0])

        categories = extract_categories(card, listing_url)
        results.append({
            "title": title,
            "categories": categories,
            "category_names": [category["name"] for category in categories],
            "poster_url": poster,
            "featured_image_url": poster,
            "source_url": href,
            "page": page,
        })

    return results, listing_url


@app.get("/")
def home():
    return {
        "name": "Movie Metadata API",
        "version": "1.1.0",
        "endpoints": [
            "/health",
            "/movies?page=1&limit=20",
            "/movies?category=Action",
            "/categories?page=1",
            "/docs",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/movies")
def movies(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = Query(None, description="Filter by category name"),
):
    items, listing_url = scrape_listing(page)

    if category:
        wanted = category.strip().casefold()
        items = [
            item for item in items
            if any(name.casefold() == wanted for name in item["category_names"])
        ]

    return {
        "page": page,
        "limit": limit,
        "category_filter": category,
        "count": min(len(items), limit),
        "source_listing": listing_url,
        "items": items[:limit],
    }


@app.get("/categories")
def categories(page: int = Query(1, ge=1)):
    items, listing_url = scrape_listing(page)
    collected = {}
    for item in items:
        for category in item["categories"]:
            collected[category["name"].casefold()] = category

    return {
        "page": page,
        "count": len(collected),
        "source_listing": listing_url,
        "categories": sorted(collected.values(), key=lambda value: value["name"].casefold()),
    }
