# Movie Metadata API

A small FastAPI service that reads publicly accessible listing pages and returns post titles, category names/URLs, poster or featured-image URLs, and the listing article URL. It does not crawl article/download pages or extract download links.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs`.

## Deploy to Render

1. Upload this project to a GitHub repository.
2. On Render, create **New + Web Service**, then connect the repository.
3. Runtime: Python.
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Deploy. Render will provide your service URL.

## Endpoints

- `GET /` — API information
- `GET /health` — health check
- `GET /movies?page=1&limit=20` — listing posts with categories and images
- `GET /movies?page=1&limit=20&category=Action` — filter the current listing page by category name
- `GET /categories?page=1` — unique categories found on that listing page
- `GET /docs` — interactive API documentation

## Example post object

```json
{
  "title": "Example Movie (2026)",
  "categories": [
    {"name": "Action", "url": "https://example.com/category/action/"}
  ],
  "category_names": ["Action"],
  "poster_url": "https://example.com/poster.jpg",
  "featured_image_url": "https://example.com/poster.jpg",
  "source_url": "https://example.com/movie-page/",
  "page": 1
}
```

## Notes

Category detection is based on common WordPress taxonomy links and theme CSS classes. If the source theme uses different markup or displays categories only on individual post pages, selectors will need adjustment. The category filter searches the categories detected on the requested listing page; it is not a site-wide category archive crawler. Scrape only where permitted and respect the source site's terms and rate limits.
