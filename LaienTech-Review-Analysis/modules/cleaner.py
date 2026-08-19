import re
import hashlib
from datetime import datetime
from typing import Optional


REQUIRED_FIELDS = ['review_id', 'title', 'content', 'rating']


def clean_reviews(
    reviews: list[dict],
    remove_empty: bool = True,
    deduplicate: bool = True,
    normalize: bool = True,
    progress_callback=None
) -> tuple[list[dict], dict]:
    stats = {
        'input_count': len(reviews),
        'removed_empty': 0,
        'removed_duplicates': 0,
        'normalized': 0,
        'output_count': 0
    }

    cleaned = reviews.copy()

    if remove_empty:
        before = len(cleaned)
        cleaned = _remove_empty_reviews(cleaned)
        stats['removed_empty'] = before - len(cleaned)
        if progress_callback:
            progress_callback(f'移除空评论: {stats["removed_empty"]} 条')

    if deduplicate:
        before = len(cleaned)
        cleaned = _deduplicate_reviews(cleaned)
        stats['removed_duplicates'] = before - len(cleaned)
        if progress_callback:
            progress_callback(f'移除重复评论: {stats["removed_duplicates"]} 条')

    if normalize:
        before = len(cleaned)
        cleaned = _normalize_fields(cleaned)
        stats['normalized'] = before

    stats['output_count'] = len(cleaned)
    return cleaned, stats


def _remove_empty_reviews(reviews: list[dict]) -> list[dict]:
    return [r for r in reviews if _has_content(r)]


def _has_content(review: dict) -> bool:
    content = review.get('content', '').strip()
    title = review.get('title', '').strip()
    return bool(content or title)


def _deduplicate_reviews(reviews: list[dict]) -> list[dict]:
    seen_ids = set()
    seen_hashes = set()
    result = []

    for review in reviews:
        rid = str(review.get('review_id', ''))
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            result.append(review)
            continue

        content_hash = _compute_content_hash(review)
        if content_hash and content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            result.append(review)

    return result


def _compute_content_hash(review: dict) -> str:
    title = review.get('title', '').lower().strip()
    content = review.get('content', '').lower().strip()
    rating = str(review.get('rating', ''))
    combined = f'{title}|{content}|{rating}'
    return hashlib.md5(combined.encode('utf-8')).hexdigest()


def _normalize_fields(reviews: list[dict]) -> list[dict]:
    for review in reviews:
        review['rating'] = _normalize_rating(review.get('rating', 0))
        review['date'] = _normalize_date(review.get('date', ''))
        review['content'] = _normalize_text(review.get('content', ''))
        review['title'] = _normalize_text(review.get('title', ''))

        if not review.get('review_id'):
            review['review_id'] = _generate_review_id(review)

        if not review.get('author'):
            review['author'] = 'Anonymous'

        if not review.get('version'):
            review['version'] = 'Unknown'

    return reviews


def _normalize_rating(rating) -> int:
    try:
        r = int(float(rating))
        return max(1, min(5, r))
    except (ValueError, TypeError):
        return 0


def _normalize_date(date_str: str) -> str:
    if not date_str:
        return ''

    formats = [
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue

    return date_str


def _normalize_text(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text


def _generate_review_id(review: dict) -> str:
    content = review.get('content', '')
    title = review.get('title', '')
    author = review.get('author', '')
    raw = f'{title}|{content}|{author}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
