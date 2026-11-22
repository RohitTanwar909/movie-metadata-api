
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import requests
import re

# =========================================================
# CONFIGURATION - MULTIPLE SUPPORTED DOMAINS
# =========================================================

ALLOWED_DOMAINS = {
    "new1.bollyflix.tours",
    "vegamovies17.co.in",
    "filmyfly.kred",
    "new15.hdhub4u.cl",
}

BASE_URL = "https://new15.hdhub4u.cl/"

CATEGORY_PATH_MARKERS = (
    "/category/",
    "/genre/",
    "/tag/"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 25

# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="Multi-Domain Movie Metadata API",
    version="3.0.0",
    description="Movie and web-series metadata extraction from multiple domains."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# =========================================================
# URL VALIDATION
# =========================================================

def validate_source_url(url: str):

    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise HTTPException(
            status_code=400,
            detail="Only HTTPS URLs are allowed."
        )

    if parsed.hostname not in ALLOWED_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Unsupported domain",
                "allowed_domains": sorted(ALLOWED_DOMAINS)
            }
        )

    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400,
            detail="URLs containing credentials are not allowed."
        )

    return url


# =========================================================
# FETCH PAGE
# =========================================================

def fetch_soup(url: str):

    validate_source_url(url)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False
        )

        if 300 <= response.status_code < 400:
            raise HTTPException(
                status_code=502,
                detail="Source page redirected. Redirects are not followed."
            )

        response.raise_for_status()

        if urlparse(response.url).hostname not in ALLOWED_DOMAINS:
            raise HTTPException(
                status_code=502,
                detail="Unexpected source hostname."
            )

        return BeautifulSoup(response.text, "html.parser")

    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Source website request failed: {str(exc)}"
        )


# =========================================================
# GENERAL HELPERS
# =========================================================

def clean_title(text: str) -> str:

    text = re.sub(r"\s+", " ", text or "").strip()

    text = re.sub(
        r"^(download\s+)",
        "",
        text,
        flags=re.I
    )

    return text.strip()


def get_meta_content(soup, selectors):

    for selector in selectors:

        tag = soup.select_one(selector)

        if tag and tag.get("content"):
            return tag.get("content").strip()

    return None


def get_image_url(img, page_url):

    if not img:
        return None

    attributes = (
        "data-src",
        "data-lazy-src",
        "data-original",
        "data-srcset",
        "src",
    )

    for attribute in attributes:

        value = img.get(attribute)

        if not value or value.startswith("data:"):
            continue

        if attribute == "data-srcset":
            value = value.split(",")[0].strip().split()[0]

        return urljoin(page_url, value)

    srcset = img.get("srcset")

    if srcset:
        value = srcset.split(",")[0].strip().split()[0]
        return urljoin(page_url, value)

    return None


# =========================================================
# CATEGORY EXTRACTION
# =========================================================

def is_category_link(anchor):

    href = (anchor.get("href") or "").lower()

    classes = " ".join(anchor.get("class", [])).lower()

    rel = " ".join(anchor.get("rel", [])).lower()

    return (
        any(marker in href for marker in CATEGORY_PATH_MARKERS)
        or "category" in classes
        or "cat-item" in classes
        or "category" in rel
    )


def extract_categories(card, page_url):

    categories = []
    seen = set()

    if not card:
        return categories

    for anchor in card.find_all("a", href=True):

        if not is_category_link(anchor):
            continue

        name = re.sub(
            r"\s+", " ",
            anchor.get_text(" ", strip=True)
        ).strip()

        href = urljoin(page_url, anchor.get("href", ""))

        if (
            not name
            or urlparse(href).hostname not in ALLOWED_DOMAINS
        ):
            continue

        key = name.casefold()

        if key not in seen:
            seen.add(key)

            categories.append({
                "name": name,
                "url": href
            })

    return categories


def extract_page_categories(soup, page_url):

    categories = []
    seen = set()

    def add_category(name, href=None):

        name = re.sub(r"\s+", " ", name or "").strip()
        name = name.strip(" ,|/-")

        if not name:
            return

        if name.casefold() in {
            "category", "categories", "genre", "genres",
            "tag", "tags", "home", "uncategorized"
        }:
            return

        key = name.casefold()

        if key not in seen:
            seen.add(key)

            categories.append({
                "name": name,
                "url": urljoin(page_url, href) if href else None
            })

    selectors = [
        'a[rel~="category"]',
        'a[rel~="tag"]',
        '.cat-links a',
        '.post-categories a',
        '.tags-links a',
        '.post-category a',
        '.entry-category a',
        '.meta-category a',
        '.categories a',
        '.genres a',
        '.genre a',
        '.post-meta a'
    ]

    for selector in selectors:

        for anchor in soup.select(selector):

            href = anchor.get("href", "")

            if (
                href
                and urlparse(urljoin(page_url, href)).hostname
                in ALLOWED_DOMAINS
            ):
                add_category(
                    anchor.get_text(" ", strip=True),
                    href
                )

    container_selectors = [
        '[class*="genre"]',
        '[class*="category"]',
        '[class*="cat-links"]',
        '[class*="post-meta"]',
        '[class*="movie-meta"]'
    ]

    for selector in container_selectors:

        for container in soup.select(selector):

            for anchor in container.select("a"):

                href = anchor.get("href", "")

                if (
                    href
                    and urlparse(urljoin(page_url, href)).hostname
                    in ALLOWED_DOMAINS
                ):
                    add_category(
                        anchor.get_text(" ", strip=True),
                        href
                    )

    if not categories:

        description = get_meta_content(
            soup,
            [
                'meta[name="description"]',
                'meta[property="og:description"]'
            ]
        ) or ""

        match = re.search(
            r"based on\s+(.+?)(?:\.|$)",
            description,
            re.I
        )

        if match:

            for name in re.split(
                r"\s*,\s*|\s+and\s+",
                match.group(1)
            ):
                add_category(name)

    return categories


# =========================================================
# IMAGE EXTRACTION
# =========================================================

def extract_page_image(soup, page_url):

    image = get_meta_content(
        soup,
        [
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
            'meta[property="twitter:image"]',
        ]
    )

    if image:
        return urljoin(page_url, image)

    selectors = [
        ".post-thumbnail img",
        ".featured-image img",
        ".entry-content img",
        ".post-image img",
        "article img",
        "main img",
    ]

    for selector in selectors:

        image_tag = soup.select_one(selector)

        image_url = get_image_url(image_tag, page_url)

        if image_url:
            return image_url

    return None


# =========================================================
# LISTING SCRAPER
# =========================================================

def fetch_listing_page(page: int, base_url: str = BASE_URL):

    validate_source_url(base_url)

    base_url = base_url.rstrip("/") + "/"

    url = (
        base_url
        if page <= 1
        else urljoin(base_url, f"page/{page}/")
    )

    return fetch_soup(url), url


def scrape_listing(page: int, base_url: str = BASE_URL):

    soup, listing_url = fetch_listing_page(page, base_url)

    results = []
    seen = set()

    for heading in soup.select("h1, h2, h3, h4"):

        anchor = (
            heading.find("a", href=True)
            or heading.find_parent("a", href=True)
        )

        if not anchor:
            continue

        title = clean_title(
            anchor.get_text(" ", strip=True)
        )

        href = urljoin(listing_url, anchor.get("href", ""))

        if (
            not title
            or urlparse(href).hostname not in ALLOWED_DOMAINS
            or href in seen
        ):
            continue

        seen.add(href)

        card = (
            heading.find_parent(["article", "li", "div"])
            or heading.parent
        )

        img = card.find("img") if card else None

        poster = get_image_url(img, listing_url)

        categories = extract_categories(card, listing_url)

        results.append({
            "title": title,
            "categories": categories,
            "category_names": [
                category["name"]
                for category in categories
            ],
            "poster_url": poster,
            "featured_image_url": poster,
            "source_url": href,
            "page": page
        })

    return results, listing_url


# =========================================================
# INDIVIDUAL MOVIE / SERIES EXTRACTION
# =========================================================

def scrape_individual_page(url: str):

    soup = fetch_soup(url)

    title = get_meta_content(
        soup,
        [
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
        ]
    )

    if not title:

        title_tag = soup.select_one(
            "h1.entry-title, h1.post-title, article h1, h1"
        )

        if title_tag:
            title = title_tag.get_text(" ", strip=True)

    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    title = clean_title(title or "")

    description = get_meta_content(
        soup,
        [
            'meta[name="description"]',
            'meta[property="og:description"]',
            'meta[name="twitter:description"]',
        ]
    )

    image_url = extract_page_image(soup, url)

    categories = extract_page_categories(soup, url)

    canonical_tag = soup.select_one('link[rel="canonical"]')

    canonical_url = url

    if canonical_tag and canonical_tag.get("href"):

        candidate = urljoin(url, canonical_tag["href"])

        if urlparse(candidate).hostname in ALLOWED_DOMAINS:
            canonical_url = candidate

    return {
        "success": True,
        "title": title or None,
        "description": description,
        "poster_url": image_url,
        "featured_image_url": image_url,
        "categories": categories,
        "category_names": [
            category["name"]
            for category in categories
        ],
        "source_url": url,
        "canonical_url": canonical_url,
        "source_domain": urlparse(url).hostname
    }


# =========================================================
# API ROUTES
# =========================================================

@app.get("/")
def home():

    return {
        "name": "Multi-Domain Movie Metadata API",
        "version": "3.0.0",
        "status": "running",
        "supported_domains": sorted(ALLOWED_DOMAINS),
        "endpoints": {
            "health": "/health",
            "movies": "/movies?page=1&limit=20&domain=new15.hdhub4u.cl",
            "categories": "/categories?page=1&domain=new15.hdhub4u.cl",
            "extract": "/extract?url=YOUR_PAGE_URL",
            "bulk_extract": "/extract-multiple?urls=URL1&urls=URL2",
            "documentation": "/docs"
        }
    }


@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "Multi-Domain Movie Metadata API",
        "supported_domains": sorted(ALLOWED_DOMAINS)
    }


# =========================================================
# MOVIES ENDPOINT
# =========================================================

@app.get("/movies")
def movies(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    domain: str = Query("new15.hdhub4u.cl"),
    category: str | None = None
):

    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(400, detail="Unsupported domain.")

    base_url = f"https://{domain}/"

    items, listing_url = scrape_listing(page, base_url)

    if category:

        wanted = category.strip().casefold()

        items = [
            item for item in items
            if any(
                name.casefold() == wanted
                for name in item["category_names"]
            )
        ]

    return {
        "success": True,
        "domain": domain,
        "page": page,
        "limit": limit,
        "category_filter": category,
        "count": min(len(items), limit),
        "source_listing": listing_url,
        "items": items[:limit]
    }


# =========================================================
# CATEGORIES ENDPOINT
# =========================================================

@app.get("/categories")
def categories(
    page: int = Query(1, ge=1),
    domain: str = Query("new15.hdhub4u.cl")
):

    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(400, detail="Unsupported domain.")

    items, listing_url = scrape_listing(
        page,
        f"https://{domain}/"
    )

    collected = {}

    for item in items:

        for category in item["categories"]:
            collected[category["name"].casefold()] = category

    return {
        "success": True,
        "domain": domain,
        "page": page,
        "count": len(collected),
        "source_listing": listing_url,
        "categories": sorted(
            collected.values(),
            key=lambda value: value["name"].casefold()
        )
    }


# =========================================================
# SINGLE EXTRACTION
# =========================================================

@app.get("/extract")
def extract(
    url: str = Query(..., description="Movie or series page URL")
):

    return scrape_individual_page(url)


# =========================================================
# MULTIPLE URL EXTRACTION
# =========================================================

@app.get("/extract-multiple")
def extract_multiple(
    urls: list[str] = Query(
        ...,
        description="Provide multiple movie or series URLs",
        min_length=1,
        max_length=20
    )
):

    results = []

    for url in urls:

        try:

            validate_source_url(url)

            data = scrape_individual_page(url)

            results.append(data)

        except HTTPException as exc:

            results.append({
                "success": False,
                "source_url": url,
                "error": exc.detail
            })

        except Exception as exc:

            results.append({
                "success": False,
                "source_url": url,
                "error": str(exc)
            })

    return {
        "success": True,
        "total": len(urls),
        "successful": sum(
            1 for item in results if item["success"]
        ),
        "failed": sum(
            1 for item in results if not item["success"]
        ),
        "results": results
    }
