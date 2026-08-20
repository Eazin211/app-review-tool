import os
import json
import re
from typing import Optional
from datetime import datetime


class PRDGenerator:
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

    def generate_prd(
        self,
        analysis: dict,
        app_info: dict = None,
        goals: list[str] = None,
        progress_callback=None
    ) -> dict:
        app_info = app_info or {}
        goals = goals or ['general']

        if progress_callback:
            progress_callback('Generating PRD document...')

        findings = analysis.get('findings', [])
        themes = analysis.get('themes', [])
        statistics = analysis.get('statistics', {})
        contradictions = analysis.get('contradictions', [])

        if self.client and self.api_key and findings:
            if progress_callback:
                progress_callback('Using LLM to generate requirements...')
            requirements = self._llm_requirement_generation(findings, themes, goals, app_info)
        else:
            if progress_callback:
                progress_callback('Using rule-based requirements...')
            requirements = self._rule_based_requirements(findings, themes, goals)

        requirements = self._prioritize_requirements(requirements)

        versions = self._plan_versions(requirements, progress_callback)

        prd = {
            'title': f'Product Requirements Document for {app_info.get("app_name", "the app")}',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'app_info': app_info,
            'goals': goals,
            'executive_summary': self._generate_executive_summary(analysis, app_info, goals),
            'statistics': statistics,
            'requirements': requirements,
            'versions': versions,
            'contradictions': contradictions,
            'assumptions_and_limitations': self._generate_limitations(analysis),
            'model_used': self.client is not None and bool(self.api_key)
        }

        return prd

    def _generate_executive_summary(self, analysis: dict, app_info: dict, goals: list[str]) -> str:
        total = analysis.get('total_reviews_analyzed', 0)
        stats = analysis.get('statistics', {})
        avg_rating = stats.get('average_rating', 0)
        findings_count = len(analysis.get('findings', []))
        themes_count = len(analysis.get('themes', []))

        lines = [
            f"Executive Summary:",
            f"This PRD is based on the analysis of {total} reviews for {app_info.get('app_name', 'the app')}.",
            f"The average rating is {avg_rating:.1f}/5.",
            f"Analysis identified {themes_count} themes and {findings_count} key findings.",
        ]

        if goals and goals != ['general']:
            lines.append(f"Primary analysis goals: {', '.join(goals)}")

        return ' '.join(lines)

    def _llm_requirement_generation(
        self,
        findings: list[dict],
        themes: list[dict],
        goals: list[str],
        app_info: dict
    ) -> list[dict]:
        findings_text = json.dumps(findings[:20], indent=2, ensure_ascii=False)
        goals_text = ', '.join(goals)
        app_name = app_info.get('app_name', 'the app')

        prompt = f"""You are a product manager. Based on the following analysis findings from app reviews, generate a structured list of product requirements.

For each requirement, provide:
- A unique ID (REQ-001, REQ-002, etc.)
- A clear requirement statement
- Priority (Must Have, Should Have, Nice to Have)
- Type (bug_fix, feature, improvement, ui_ux)
- Source finding labels that inspired this requirement
- Source review IDs for traceability
- Rationale (why this matters)
- Acceptance criteria (how to verify)

Respond ONLY with valid JSON array.

Analysis findings:
{findings_text}

Goals: {goals_text}
App: {app_name}

Requirements:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': 'You are a product manager. Generate structured product requirements from user review analysis. Always respond with valid JSON.'},
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
            if isinstance(parsed, list):
                requirements = parsed
            elif isinstance(parsed, dict) and 'requirements' in parsed:
                requirements = parsed['requirements']
            else:
                requirements = []

            for i, req in enumerate(requirements):
                if 'id' not in req:
                    req['id'] = f'REQ-{i+1:03d}'
                if 'source_review_ids' not in req:
                    req['source_review_ids'] = []
                if 'source_findings' not in req:
                    req['source_findings'] = []

            return requirements

        except (json.JSONDecodeError, Exception):
            return self._rule_based_requirements(findings, themes, goals)

    def _rule_based_requirements(
        self,
        findings: list[dict],
        themes: list[dict],
        goals: list[str]
    ) -> list[dict]:
        requirements = []
        req_id = 1

        for finding in findings:
            finding_type = finding.get('type', 'problem')
            severity = finding.get('severity', 'medium')
            label = finding.get('label', '')
            description = finding.get('description', '')
            source_ids = finding.get('source_review_ids', [])

            req_type = self._map_finding_to_requirement_type(finding_type)
            priority = self._map_severity_to_priority(severity)

            requirement = {
                'id': f'REQ-{req_id:03d}',
                'statement': f'Address: {label} - {description}',
                'priority': priority,
                'type': req_type,
                'source_findings': [label],
                'source_review_ids': source_ids,
                'rationale': f'Based on {len(source_ids)} user reviews indicating this issue.',
                'acceptance_criteria': [
                    f'User feedback related to "{label}" is addressed',
                    f'Related issue severity reduced or eliminated',
                    f'At least {min(3, len(source_ids))} users who reported this issue would consider it resolved'
                ]
            }
            requirements.append(requirement)
            req_id += 1

        return requirements

    def _map_finding_to_requirement_type(self, finding_type: str) -> str:
        mapping = {
            'problem': 'bug_fix',
            'feature_request': 'feature',
            'positive_feedback': 'improvement',
            'question': 'improvement'
        }
        return mapping.get(finding_type, 'improvement')

    def _map_severity_to_priority(self, severity: str) -> str:
        mapping = {
            'high': 'Must Have',
            'medium': 'Should Have',
            'low': 'Nice to Have'
        }
        return mapping.get(severity, 'Should Have')

    def _prioritize_requirements(self, requirements: list[dict]) -> list[dict]:
        priority_order = {'Must Have': 0, 'Should Have': 1, 'Nice to Have': 2}

        for req in requirements:
            if 'source_review_ids' in req:
                support = len(req.get('source_review_ids', []))
                if support >= 5 and req['priority'] != 'Must Have':
                    if req['priority'] == 'Nice to Have':
                        req['priority'] = 'Should Have'

        requirements.sort(key=lambda r: priority_order.get(r.get('priority', 'Nice to Have'), 3))
        return requirements

    def _plan_versions(self, requirements: list[dict], progress_callback=None) -> list[dict]:
        must_have = [r for r in requirements if r.get('priority') == 'Must Have']
        should_have = [r for r in requirements if r.get('priority') == 'Should Have']
        nice_to_have = [r for r in requirements if r.get('priority') == 'Nice to Have']

        versions = []
        version_num = 1

        if must_have:
            versions.append({
                'version': f'v{version_num}',
                'name': f'Phase {version_num}: Critical Fixes',
                'description': 'Address critical issues with highest user impact',
                'requirements': [r['id'] for r in must_have],
                'estimated_effort': 'High'
            })
            version_num += 1

        if should_have:
            versions.append({
                'version': f'v{version_num}',
                'name': f'Phase {version_num}: Core Improvements',
                'description': 'Implement important feature improvements',
                'requirements': [r['id'] for r in should_have],
                'estimated_effort': 'Medium'
            })
            version_num += 1

        if nice_to_have:
            versions.append({
                'version': f'v{version_num}',
                'name': f'Phase {version_num}: Enhancements',
                'description': 'Add nice-to-have features and polish',
                'requirements': [r['id'] for r in nice_to_have],
                'estimated_effort': 'Low'
            })

        if not versions:
            versions.append({
                'version': 'v1',
                'name': 'Phase 1: General Improvements',
                'description': 'Review and address user feedback',
                'requirements': [r['id'] for r in requirements],
                'estimated_effort': 'Medium'
            })

        return versions

    def _generate_limitations(self, analysis: dict) -> list[str]:
        limitations = []
        total = analysis.get('total_reviews_analyzed', 0)

        if total < 10:
            limitations.append('Limited review volume may affect statistical significance.')
        elif total < 50:
            limitations.append('Moderate review volume; some findings may have limited confidence.')

        contradictions = analysis.get('contradictions', [])
        if contradictions:
            limitations.append(f'{len(contradictions)} contradictions detected in review sentiment.')

        if not analysis.get('model_used'):
            limitations.append('LLM not used for analysis; findings based on statistical baseline only.')

        return limitations
