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


def fetch_reviews(
    app_id: str,
    country: str = 'us',
    max_pages: int = 10,
    delay: float = 0.5,
    progress_callback=None
) -> list[dict]:
    all_reviews = []
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    for page in range(1, max_pages + 1):
        url = f'https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/page={page}/json'

        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            if progress_callback:
                progress_callback(f'分页 {page} 请求失败: {str(e)}')
            break
        except json.JSONDecodeError:
            if progress_callback:
                progress_callback(f'分页 {page} 响应解析失败')
            break

        feed_entry = data.get('feed', {}).get('entry', [])
        if not feed_entry or not isinstance(feed_entry, list):
            if progress_callback:
                progress_callback(f'分页 {page} 无更多数据，停止抓取')
            break

        for entry in feed_entry:
            if isinstance(entry, dict) and 'content' in entry:
                review = _parse_rss_entry(entry, app_id, country)
                if review:
                    all_reviews.append(review)

        if progress_callback:
            progress_callback(f'已抓取 {len(all_reviews)} 条评论 (分页 {page})')

        if page < max_pages:
            time.sleep(delay)

    return all_reviews


def _parse_rss_entry(entry: dict, app_id: str, country: str) -> Optional[dict]:
    try:
        review_id = str(entry.get('id', {}).get('attributes', {}).get('im:bundleVersionId', ''))
        if not review_id:
            review_id = str(entry.get('id', {}).get('label', ''))

        title = entry.get('title', {}).get('label', '')
        content = entry.get('content', {}).get('label', '')
        rating = int(entry.get('im:rating', {}).get('label', '0'))
        author = entry.get('author', {}).get('name', {}).get('label', 'Unknown')
        version = entry.get('im:version', {}).get('label', '')
        date = entry.get('updated', {}).get('label', '')
        is_edited = entry.get('im:userVideoUrl', {}).get('attributes', {}).get('im:appExternalVersion', '') != ''

        app_name = entry.get('im:collectionName', {}).get('label', '')

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
