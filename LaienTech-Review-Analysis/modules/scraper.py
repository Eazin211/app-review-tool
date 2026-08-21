import re
import time
import json
import csv
import os
from typing import Optional
from dataclasses import dataclass, asdict

import requests


@dataclass
class Review:
    review_id: str
    title: str
    content: str
    rating: int
    author: str
    country: str
    app_id: str
    app_name: str
    version: str
    date: str
    is_edited: bool = False

    def to_dict(self):
        return asdict(self)


def parse_app_store_url(url: str) -> tuple[Optional[str], Optional[str]]:
    match = re.search(r'/app/[^/]+/id(\d+)', url)
    app_id = match.group(1) if match else None

    country_match = re.search(r'apps\.apple\.com/([a-z]{2})/', url)
    country = country_match.group(1) if country_match else 'us'

    return app_id, country


MAX_RSS_PAGES = 10
REVIEWS_PER_PAGE = 50
MAX_RSS_REVIEWS = MAX_RSS_PAGES * REVIEWS_PER_PAGE


def fetch_reviews(
    app_id: str,
    country: str = 'us',
    max_pages: int = 10,
    delay: float = 0.5,
    progress_callback=None
) -> tuple[list[dict], dict]:
    all_reviews = []
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    rss_limit_reached = False
    effective_pages = min(max_pages, MAX_RSS_PAGES)

    for page in range(1, effective_pages + 1):
        url = f'https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/page={page}/json'

        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            if progress_callback:
                progress_callback(f'Page {page} request failed: {str(e)}')
            break
        except json.JSONDecodeError:
            if progress_callback:
                progress_callback(f'Page {page} response parse failed')
            break

        feed_entry = data.get('feed', {}).get('entry', [])
        if not feed_entry or not isinstance(feed_entry, list):
            if progress_callback:
                progress_callback(f'Page {page} no more data, stopping')
            break

        for entry in feed_entry:
            if isinstance(entry, dict) and 'content' in entry:
                review = _parse_rss_entry(entry, app_id, country)
                if review:
                    all_reviews.append(review)

        if progress_callback:
            progress_callback(f'Fetched {len(all_reviews)} reviews (page {page})')

        if len(all_reviews) >= MAX_RSS_REVIEWS:
            rss_limit_reached = True
            if progress_callback:
                progress_callback(f'Reached iTunes RSS 500-review limit on page {page}')
            break

        if page < effective_pages:
            time.sleep(delay)

    metadata = {
        'source': 'rss',
        'rss_limit_reached': rss_limit_reached,
        'rss_max_reviews': MAX_RSS_REVIEWS,
        'rss_max_pages': MAX_RSS_PAGES,
        'effective_pages_used': page if all_reviews else 0,
        'country_requested': country,
        'rss_empty': False,
        'note': ''
    }

    if not all_reviews:
        metadata['rss_empty'] = True
        metadata['note'] = 'iTunes RSS API currently returns no reviews for this app. The API has been progressively deprecated by Apple since 2026. Please try importing local data or using sample data.'
        if progress_callback:
            progress_callback('RSS returned 0 reviews — iTunes API may be deprecated for this app')
        return all_reviews, metadata

    if rss_limit_reached:
        metadata['note'] = 'current data source only provides the latest 500 reviews'
    elif effective_pages < max_pages:
        metadata['note'] = f'iTunes RSS API capped at {MAX_RSS_PAGES} pages (500 reviews max)'

    return all_reviews, metadata


def _parse_rss_entry(entry: dict, app_id: str, country: str) -> Optional[dict]:
    try:
        review_id = str(entry.get('id', {}).get('label', ''))

        title = entry.get('title', {}).get('label', '')
        content = entry.get('content', {}).get('label', '')

        rating_str = entry.get('im:rating', {}).get('label', '0')
        rating = int(float(rating_str))

        author = entry.get('author', {}).get('name', {}).get('label', 'Unknown')
        version = entry.get('im:version', {}).get('label', '')
        date = entry.get('updated', {}).get('label', '')
        is_edited = False

        link_bundle_id = entry.get('link', {}).get('attributes', {}).get('im:bundleVersionId', '')
        app_name = ''
        if link_bundle_id:
            pass

        return {
            'review_id': review_id,
            'title': title,
            'content': content,
            'rating': rating,
            'author': author,
            'country': country,
            'app_id': app_id,
            'app_name': app_name,
            'version': version,
            'date': date,
            'is_edited': is_edited
        }
    except (KeyError, ValueError, TypeError):
        return None


def import_from_json(file_path: str) -> list[dict]:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and 'reviews' in data:
        return data['reviews']
    return []


def import_from_csv(file_path: str) -> list[dict]:
    reviews = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['rating'] = int(row.get('rating', 0))
            reviews.append(row)
    return reviews


def load_sample_data() -> list[dict]:
    sample_path = os.path.join(os.path.dirname(__file__), '..', 'sample_data', 'sample_reviews.json')
    if os.path.exists(sample_path):
        return import_from_json(sample_path)
    return []
