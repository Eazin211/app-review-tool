import os
import json
import re
from typing import Optional


class TestCaseGenerator:
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

    def generate_test_cases(
        self,
        prd: dict,
        analysis: dict,
        progress_callback=None
    ) -> dict:
        if progress_callback:
            progress_callback('生成测试用例...')

        requirements = prd.get('requirements', [])
        reviews_map = self._build_reviews_map(analysis)

        if self.client and self.api_key and requirements:
            if progress_callback:
                progress_callback('使用LLM生成测试用例...')
            test_cases = self._llm_test_case_generation(requirements, reviews_map, prd)
        else:
            if progress_callback:
                progress_callback('使用规则基线生成测试用例...')
            test_cases = self._rule_based_test_cases(requirements, reviews_map)

        test_cases = self._enrich_test_cases(test_cases, requirements)

        coverage = self._compute_coverage(test_cases, requirements)

        return {
            'test_cases': test_cases,
            'coverage': coverage,
            'total_test_cases': len(test_cases),
            'requirements_covered': coverage['requirements_covered'],
            'requirements_total': coverage['requirements_total'],
            'model_used': self.client is not None and bool(self.api_key)
        }

    def _build_reviews_map(self, analysis: dict) -> dict:
        reviews_map = {}
        findings = analysis.get('findings', [])
        for finding in findings:
            for rid in finding.get('source_review_ids', []):
                if rid not in reviews_map:
                    reviews_map[rid] = {
                        'review_id': rid,
                        'finding_label': finding.get('label', ''),
                        'finding_type': finding.get('type', ''),
                        'severity': finding.get('severity', '')
                    }
        return reviews_map

    def _llm_test_case_generation(
        self,
        requirements: list[dict],
        reviews_map: dict,
        prd: dict
    ) -> list[dict]:
        req_text = json.dumps(requirements[:15], indent=2, ensure_ascii=False)

        prompt = f"""You are a quality assurance engineer. Generate detailed test cases for the following product requirements.

For each requirement, generate 1-3 test cases. Each test case should include:
- A unique ID (TC-001, TC-002, etc.)
- Test case title
- Requirement ID it maps to
- Type (functional, ui, performance, regression)
- Priority (high, medium, low)
- Preconditions
- Test steps (numbered)
- Expected results
- Source review IDs that motivate this test

Respond ONLY with valid JSON array.

Requirements:
{req_text}

Generate test cases:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': 'You are a QA engineer. Generate structured test cases from product requirements. Always respond with valid JSON.'},
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
                test_cases = parsed
            elif isinstance(parsed, dict) and 'test_cases' in parsed:
                test_cases = parsed['test_cases']
            else:
                test_cases = []

            return test_cases

        except (json.JSONDecodeError, Exception):
            return self._rule_based_test_cases(requirements, reviews_map)

    def _rule_based_test_cases(
        self,
        requirements: list[dict],
        reviews_map: dict
    ) -> list[dict]:
        test_cases = []
        tc_id = 1

        for req in requirements:
            req_id = req.get('id', '')
            req_statement = req.get('statement', '')
            req_type = req.get('type', 'improvement')
            priority = req.get('priority', 'Should Have')
            source_reviews = req.get('source_review_ids', [])

            tc_type = self._map_requirement_to_test_type(req_type)
            tc_priority = self._map_priority_to_test_priority(priority)

            test_case = {
                'id': f'TC-{tc_id:03d}',
                'title': f'Verify: {req_statement[:80]}',
                'requirement_id': req_id,
                'type': tc_type,
                'priority': tc_priority,
                'preconditions': [
                    'Application is installed and running',
                    'User has appropriate permissions'
                ],
                'steps': [
                    f'Navigate to the relevant feature area related to: {req_statement[:60]}',
                    'Perform the action described in the requirement',
                    'Observe the system response'
                ],
                'expected_results': [
                    f'The system addresses the issue: {req_statement[:80]}',
                    'User experience is improved or issue is resolved',
                    'No regressions in related functionality'
                ],
                'source_review_ids': source_reviews,
                'automation_feasible': tc_type != 'ui'
            }

            test_cases.append(test_case)
            tc_id += 1

            if priority == 'Must Have':
                edge_case = {
                    'id': f'TC-{tc_id:03d}',
                    'title': f'Edge case: {req_statement[:60]}',
                    'requirement_id': req_id,
                    'type': tc_type,
                    'priority': 'medium',
                    'preconditions': [
                        'Same as primary test case',
                        'Additional edge case conditions identified'
                    ],
                    'steps': [
                        'Test with boundary conditions',
                        'Test with invalid inputs',
                        'Test with network interruptions if applicable'
                    ],
                    'expected_results': [
                        'System handles edge cases gracefully',
                        'No data loss or corruption',
                        'Appropriate error messages displayed'
                    ],
                    'source_review_ids': source_reviews,
                    'automation_feasible': True
                }
                test_cases.append(edge_case)
                tc_id += 1

        return test_cases

    def _map_requirement_to_test_type(self, req_type: str) -> str:
        mapping = {
            'bug_fix': 'regression',
            'feature': 'functional',
            'improvement': 'functional',
            'ui_ux': 'ui'
        }
        return mapping.get(req_type, 'functional')

    def _map_priority_to_test_priority(self, priority: str) -> str:
        mapping = {
            'Must Have': 'high',
            'Should Have': 'medium',
            'Nice to Have': 'low'
        }
        return mapping.get(priority, 'medium')

    def _enrich_test_cases(self, test_cases: list[dict], requirements: list[dict]) -> list[dict]:
        req_map = {r['id']: r for r in requirements}

        for tc in test_cases:
            req_id = tc.get('requirement_id', '')
            if req_id in req_map:
                req = req_map[req_id]
                if not tc.get('source_review_ids'):
                    tc['source_review_ids'] = req.get('source_review_ids', [])
                if 'acceptance_criteria' not in tc:
                    tc['acceptance_criteria'] = req.get('acceptance_criteria', [])

        return test_cases

    def _compute_coverage(self, test_cases: list[dict], requirements: list[dict]) -> dict:
        req_ids_with_tests = set()
        for tc in test_cases:
            req_id = tc.get('requirement_id', '')
            if req_id:
                req_ids_with_tests.add(req_id)

        all_req_ids = {r['id'] for r in requirements}

        covered = len(req_ids_with_tests & all_req_ids)
        total = len(all_req_ids)

        return {
            'requirements_covered': covered,
            'requirements_total': total,
            'coverage_rate': covered / total if total > 0 else 0.0,
            'uncovered_requirements': list(all_req_ids - req_ids_with_tests)
        }
