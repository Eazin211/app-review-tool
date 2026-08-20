import os
import json
import re
from typing import Optional
from collections import Counter

from dotenv import load_dotenv

load_dotenv()


class ReviewAnalyzer:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY', '')
        self.base_url = base_url or os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')
        self.model = model or os.getenv('OPENAI_MODEL', 'gpt-4o')
        self.client = None
        self._init_client()

    def _init_client(self):
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            except ImportError:
                self.client = None
            except Exception:
                self.client = None

    def analyze_reviews(
        self,
        reviews: list[dict],
        goals: list[str] = None,
        max_batch_size: int = 30,
        progress_callback=None
    ) -> dict:
        if not reviews:
            return {'themes': [], 'findings': [], 'statistics': {}, 'model_used': False}

        goals = goals or ['general']

        if progress_callback:
            progress_callback('Starting AI dynamic analysis...')

        statistics = self._compute_statistics(reviews)

        if self.client and self.api_key:
            if progress_callback:
                progress_callback('Using LLM model for theme discovery...')
            themes, findings = self._llm_theme_discovery(reviews, goals, max_batch_size, progress_callback)
            model_used = True
        else:
            if progress_callback:
                progress_callback('API key not configured, using statistical baseline...')
            themes, findings = self._statistical_baseline_analysis(reviews, goals)
            model_used = False

        findings = self._enrich_findings_with_stats(findings, reviews)
        contradictions = self._detect_contradictions(findings)

        return {
            'themes': themes,
            'findings': findings,
            'statistics': statistics,
            'contradictions': contradictions,
            'model_used': model_used,
            'total_reviews_analyzed': len(reviews),
            'goals': goals
        }

    def _compute_statistics(self, reviews: list[dict]) -> dict:
        if not reviews:
            return {}

        ratings = [r.get('rating', 0) for r in reviews]
        rating_dist = Counter(ratings)

        versions = Counter(r.get('version', 'Unknown') for r in reviews)

        return {
            'total_reviews': len(reviews),
            'average_rating': sum(ratings) / len(ratings) if ratings else 0,
            'rating_distribution': dict(rating_dist),
            'version_distribution': dict(versions),
            'rating_breakdown': {
                'positive': sum(1 for r in ratings if r >= 4),
                'neutral': sum(1 for r in ratings if r == 3),
                'negative': sum(1 for r in ratings if r <= 2)
            }
        }

    def _llm_theme_discovery(
        self,
        reviews: list[dict],
        goals: list[str],
        max_batch_size: int,
        progress_callback=None
    ) -> tuple[list[dict], list[dict]]:
        batches = self._create_batches(reviews, max_batch_size)
        all_themes = []
        all_findings = []

        for i, batch in enumerate(batches):
            if progress_callback:
                progress_callback(f'Analyzing batch {i+1}/{len(batches)} ({len(batch)} reviews)...')

            try:
                themes, findings = self._analyze_batch_with_llm(batch, goals, progress_callback)
                all_themes.extend(themes)
                all_findings.extend(findings)
            except Exception as e:
                if progress_callback:
                    progress_callback(f'Batch {i+1} LLM analysis failed: {type(e).__name__} — using statistical fallback for this batch')
                themes, findings = self._statistical_baseline_analysis(batch, goals)
                all_themes.extend(themes)
                all_findings.extend(findings)

        if not all_themes and not all_findings:
            if progress_callback:
                progress_callback('All LLM batches failed, using full statistical baseline')
            all_themes, all_findings = self._statistical_baseline_analysis(reviews, goals)

        merged_themes = self._merge_themes(all_themes)
        merged_findings = self._merge_findings(all_findings)

        return merged_themes, merged_findings

    def _create_batches(self, reviews: list[dict], max_size: int) -> list[list[dict]]:
        batches = []
        for i in range(0, len(reviews), max_size):
            batch = reviews[i:i + max_size]
            batches.append(batch)
        return batches

    def _analyze_batch_with_llm(self, reviews: list[dict], goals: list[str], progress_callback=None) -> tuple[list[dict], list[dict]]:
        reviews_text = self._format_reviews_for_llm(reviews)

        goal_text = ', '.join(goals) if goals else 'general feedback'

        prompt = f"""You are a product analyst. Analyze the following app reviews and identify:
1. Key themes or topics discussed by users
2. Specific problems, issues, or feature requests
3. Positive feedback and what users like
4. Any patterns related to these goals: {goal_text}

For each finding, provide:
- A concise label/theme name
- The type (problem, feature_request, positive_feedback, question)
- Severity (high, medium, low)
- Source review IDs (reference the review numbers)
- A brief summary of the evidence

Respond ONLY with valid JSON in this exact format:
{{
  "themes": [
    {{
      "name": "theme name",
      "description": "brief description",
      "source_review_ids": ["review_1", "review_2"],
      "related_goals": ["goal1"]
    }}
  ],
  "findings": [
    {{
      "label": "finding label",
      "type": "problem|feature_request|positive_feedback|question",
      "severity": "high|medium|low",
      "description": "detailed description",
      "source_review_ids": ["review_1", "review_2"],
      "support_count": 0,
      "confidence": 0.0
    }}
  ]
}}

Reviews to analyze:
{reviews_text}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': 'You are a product analyst that extracts structured insights from app reviews. Always respond with valid JSON only.'},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )

            response_text = response.choices[0].message.content.strip()
            response_text = re.sub(r'^```json\s*', '', response_text)
            response_text = re.sub(r'^```\s*', '', response_text)
            response_text = re.sub(r'\s*```$', '', response_text)

            parsed = json.loads(response_text)
            themes = parsed.get('themes', [])
            findings = parsed.get('findings', [])

            if progress_callback:
                progress_callback(f'LLM returned {len(themes)} themes, {len(findings)} findings for batch')

            return themes, findings

        except json.JSONDecodeError as e:
            if progress_callback:
                progress_callback(f'LLM JSON parse error: {str(e)} — falling back to statistical baseline')
            raise
        except Exception as e:
            if progress_callback:
                progress_callback(f'LLM call failed: {type(e).__name__}: {str(e)} — falling back to statistical baseline')
            raise

    def _format_reviews_for_llm(self, reviews: list[dict]) -> str:
        lines = []
        for i, r in enumerate(reviews):
            review_id = r.get('review_id', f'review_{i+1}')
            title = r.get('title', '')
            content = r.get('content', '')
            rating = r.get('rating', 'N/A')
            version = r.get('version', '')
            line = f'[ID: {review_id}] [Rating: {rating}/5] [Version: {version}]'
            if title:
                line += f'\nTitle: {title}'
            if content:
                line += f'\nContent: {content}'
            lines.append(line)

        return '\n---\n'.join(lines)

    def _merge_themes(self, themes: list[dict]) -> list[dict]:
        if not themes:
            return []

        merged = {}
        for theme in themes:
            name = theme.get('name', '').lower().strip()
            if name not in merged:
                merged[name] = {
                    'name': theme.get('name', ''),
                    'description': theme.get('description', ''),
                    'source_review_ids': set(),
                    'related_goals': set()
                }
            merged[name]['source_review_ids'].update(theme.get('source_review_ids', []))
            merged[name]['related_goals'].update(theme.get('related_goals', []))

        result = []
        for theme in merged.values():
            theme['source_review_ids'] = list(theme['source_review_ids'])
            theme['related_goals'] = list(theme['related_goals'])
            result.append(theme)

        return result

    def _merge_findings(self, findings: list[dict]) -> list[dict]:
        if not findings:
            return []

        merged = {}
        for finding in findings:
            label = finding.get('label', '').lower().strip()
            if label and label not in merged:
                merged[label] = {
                    'label': finding.get('label', ''),
                    'type': finding.get('type', 'problem'),
                    'severity': finding.get('severity', 'medium'),
                    'description': finding.get('description', ''),
                    'source_review_ids': set(),
                    'support_count': 0,
                    'confidence': 0.0
                }
            if label in merged:
                merged[label]['source_review_ids'].update(finding.get('source_review_ids', []))

        result = []
        for finding in merged.values():
            finding['source_review_ids'] = list(finding['source_review_ids'])
            finding['support_count'] = len(finding['source_review_ids'])
            finding['confidence'] = min(1.0, finding['support_count'] / 5.0)
            result.append(finding)

        return result

    def _statistical_baseline_analysis(self, reviews: list[dict], goals: list[str]) -> tuple[list[dict], list[dict]]:
        themes = []
        findings = []

        negative_reviews = [r for r in reviews if r.get('rating', 5) <= 2]
        positive_reviews = [r for r in reviews if r.get('rating', 5) >= 4]

        if negative_reviews:
            themes.append({
                'name': 'Negative Feedback',
                'description': f'{len(negative_reviews)} reviews with 1-2 star ratings',
                'source_review_ids': [r.get('review_id', '') for r in negative_reviews[:10]],
                'related_goals': goals
            })
            findings.append({
                'label': 'Low Rating Issues',
                'type': 'problem',
                'severity': 'high',
                'description': f'{len(negative_reviews)} users expressed dissatisfaction with 1-2 star ratings',
                'source_review_ids': [r.get('review_id', '') for r in negative_reviews[:10]],
                'support_count': len(negative_reviews),
                'confidence': min(1.0, len(negative_reviews) / 5.0)
            })

        if positive_reviews:
            themes.append({
                'name': 'Positive Feedback',
                'description': f'{len(positive_reviews)} reviews with 4-5 star ratings',
                'source_review_ids': [r.get('review_id', '') for r in positive_reviews[:10]],
                'related_goals': goals
            })
            findings.append({
                'label': 'Positive User Sentiment',
                'type': 'positive_feedback',
                'severity': 'low',
                'description': f'{len(positive_reviews)} users gave 4-5 star ratings',
                'source_review_ids': [r.get('review_id', '') for r in positive_reviews[:10]],
                'support_count': len(positive_reviews),
                'confidence': min(1.0, len(positive_reviews) / 5.0)
            })

        return themes, findings

    def _enrich_findings_with_stats(self, findings: list[dict], reviews: list[dict]) -> list[dict]:
        review_map = {r.get('review_id', ''): r for r in reviews}

        for finding in findings:
            source_ids = finding.get('source_review_ids', [])
            finding['support_count'] = len(source_ids)

            ratings = []
            for sid in source_ids:
                if sid in review_map:
                    ratings.append(review_map[sid].get('rating', 0))

            if ratings:
                finding['source_avg_rating'] = sum(ratings) / len(ratings)
            else:
                finding['source_avg_rating'] = 0

            finding['confidence'] = self._compute_confidence(len(source_ids), len(reviews))

        return findings

    def _compute_confidence(self, support_count: int, total_reviews: int) -> float:
        if total_reviews == 0:
            return 0.0
        ratio = support_count / total_reviews
        base_confidence = min(1.0, support_count / 3.0)
        statistical_factor = min(1.0, ratio * 2)
        return round(min(1.0, base_confidence * 0.7 + statistical_factor * 0.3), 3)

    def _detect_contradictions(self, findings: list[dict]) -> list[dict]:
        contradictions = []
        positive_ids = set()
        negative_ids = set()

        for finding in findings:
            if finding.get('type') == 'positive_feedback':
                positive_ids.update(finding.get('source_review_ids', []))
            elif finding.get('type') == 'problem':
                negative_ids.update(finding.get('source_review_ids', []))

        overlap = positive_ids & negative_ids
        if overlap:
            contradictions.append({
                'description': f'{len(overlap)} reviews appear in both positive and problem findings',
                'review_ids': list(overlap),
                'severity': 'medium'
            })

        return contradictions
